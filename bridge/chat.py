"""Minimal stdlib WebSocket client for PicoClaw's Pico channel (/pico/ws).

No third-party packages: the phone deployment must stay stdlib-only.
PicoClaw speaks newline-free JSON frames: {"type": ..., "payload": {...}}.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import time
import urllib.parse

PICO_HOST = os.environ.get("PICO_HOST", "127.0.0.1")
PICO_PORT = int(os.environ.get("PICO_PORT", "18790"))


def _load_token() -> str:
    """Env first, then the token file PicoClaw writes (it can rewrite it)."""
    token = os.environ.get("PICO_TOKEN", "").strip()
    if token:
        return token
    path = os.environ.get("PICO_TOKEN_FILE", "/var/crm/pico.token")
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


PICO_TOKEN = _load_token()


class WsError(Exception):
    pass


def _handshake(path: str, headers: dict[str, str], timeout: float = 10.0) -> socket.socket:
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {PICO_HOST}:{PICO_PORT}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
    )
    for name, value in headers.items():
        request += f"{name}: {value}\r\n"
    request += "\r\n"
    sock = socket.create_connection((PICO_HOST, PICO_PORT), timeout=timeout)
    sock.sendall(request.encode())
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            break
        response += chunk
    head = response.split(b"\r\n", 1)[0].decode("latin1", "replace")
    if "101" not in head:
        raise WsError(f"handshake failed: {head} {response[:200]!r}")
    return sock


def _send_frame(sock: socket.socket, opcode: int, payload: bytes) -> None:
    """Client frames must be masked (RFC 6455) or the server drops the connection."""
    header = bytearray([0x80 | opcode])
    mask = os.urandom(4)
    size = len(payload)
    if size < 126:
        header.append(0x80 | size)
    elif size < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", size)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", size)
    header += mask
    masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    sock.sendall(bytes(header) + masked)


def _send_text(sock: socket.socket, text: str) -> None:
    _send_frame(sock, 0x1, text.encode())


def _recv_frame(sock: socket.socket) -> tuple[int, str]:
    def read_exact(n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise WsError("connection closed")
            buf += chunk
        return buf

    b1, b2 = read_exact(2)
    opcode = b1 & 0x0F
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack(">H", read_exact(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", read_exact(8))[0]
    mask = read_exact(4) if (b2 & 0x80) else None
    data = read_exact(length) if length else b""
    if mask:
        data = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
    return opcode, data.decode("utf-8", "replace")


def ask(text: str, session_id: str = "", timeout: float = 120.0,
        raw_log: list | None = None, settle: float = 4.0) -> str:
    """Send one user message and return the assistant's final answer.

    PicoClaw streams frames and does not always mark a `final` flag, so the
    turn ends when the socket has been idle for `settle` seconds after the
    first answer chunk (or on an explicit final flag / close).
    """
    query: dict[str, str] = {}
    if PICO_TOKEN:
        query["token"] = PICO_TOKEN
    if session_id:
        query["session_id"] = session_id
    path = "/pico/ws"
    if query:
        path += "?" + urllib.parse.urlencode(query)
    headers = {"Authorization": f"Bearer {PICO_TOKEN}"} if PICO_TOKEN else {}
    sock = _handshake(path, headers)
    sock.settimeout(1.0)
    deadline = time.monotonic() + timeout
    chunks: list[str] = []
    last_content_at = 0.0
    try:
        _send_text(sock, json.dumps({
            "type": "message.send",
            "payload": {"content": text},
        }, ensure_ascii=False))
        while time.monotonic() < deadline:
            try:
                opcode, raw = _recv_frame(sock)
            except socket.timeout:
                if chunks and last_content_at and (time.monotonic() - last_content_at) >= settle:
                    break
                continue
            except WsError:
                break
            if opcode == 0x8:
                break
            if opcode == 0x9:
                _send_frame(sock, 0xA, raw.encode() if isinstance(raw, str) else b"")
                continue
            if raw_log is not None:
                raw_log.append(raw)
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if frame.get("type") != "message.create":
                continue
            payload = frame.get("payload") or {}
            kind = payload.get("kind") or ""
            content = payload.get("content") or ""
            if content and kind in ("", "message", "assistant"):
                chunks.append(content)
                last_content_at = time.monotonic()
            if payload.get("final"):
                break
        return "".join(chunks).strip()
    finally:
        try:
            sock.close()
        except OSError:
            pass
