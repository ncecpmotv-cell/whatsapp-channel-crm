## What changed

<!-- One paragraph. Link the issue if there is one. -->

## Why

<!-- The user-visible problem this solves. -->

## How it was verified

- [ ] `cd bridge && python3 -m unittest discover -s tests -v`
- [ ] `python3 scripts/e2e_local.py`
- [ ] `BASE=http://127.0.0.1:8085 bash scripts/audit.sh` (if a running instance was available)
- [ ] UI change: 360 px screenshot attached, Lighthouse not lower than before

## Documentation contract

- [ ] `docs/features/000N-<slug>.md` added or updated (Why / How / Verify / Limits)
- [ ] The page is linked from `docs/features/README.md`
- [ ] Its roadmap id exists in `ROADMAP.md` (and the row moved if it shipped)
- [ ] `python3 scripts/check_docs.py` passes locally

## Checklist

- [ ] No new runtime dependency (or the PR body justifies it with impact, cost and the alternative)
- [ ] Forms still work without JavaScript
- [ ] New routes have auth + CSRF and a line in `docs/API-MCP.md`
- [ ] No secrets, tokens or real phone numbers in the diff
