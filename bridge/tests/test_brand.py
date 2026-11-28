"""Brand editing, the visual spec, and lint rules that keep media on-brand."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as bridge_app  # noqa: E402
from crm import CrmClient  # noqa: E402
from store import Store  # noqa: E402


class BrandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "t.db"))
        self.crm = CrmClient(self.store)

    def tearDown(self):
        self.store.close()

    def test_edit_bumps_the_version(self):
        before = self.crm.get_brand()["version"]
        after = self.crm.set_brand({"palette": {"gold": "#B08A3E"}})
        self.assertEqual(after["version"], before + 1)
        self.assertTrue(after["updated_at"])
        self.assertEqual(after["palette"]["deep"], "#2A3A31")

    def test_visual_spec_resolves_roles_to_hex(self):
        spec = self.crm.visual_spec("image", "منتج جديد")
        self.assertEqual(spec["colors"]["background"], "#2A3A31")
        self.assertEqual(spec["colors"]["text"], "#F5F1E9")
        self.assertEqual(spec["colors"]["accent"], "#C5A059")
        self.assertEqual(spec["format"], "1080x1080")
        self.assertIn("شعار شخصي", spec["never"])
        self.assertIn("لا شعار", " ".join(spec["rules"]))

    def test_media_without_a_brief_is_flagged(self):
        post = self.crm.create_channel_post({
            "channel_jid": "1@newsletter", "title": "صورة", "body": "نص",
            "status": "draft", "media_type": "image"})
        codes = {i["code"] for i in self.crm.lint_post(post["id"])["issues"]}
        self.assertIn("visual_brief_missing", codes)

    def test_off_brand_brief_is_flagged(self):
        post = self.crm.create_channel_post({
            "channel_jid": "1@newsletter", "title": "صورة", "body": "نص",
            "status": "draft", "media_type": "image",
            "meta": json.dumps({"visual_brief": {
                "colors": {"background": "#000000", "text": "#FFFFFF"},
                "note": "ضع شعار شخصي في الزاوية"}})})
        codes = {i["code"] for i in self.crm.lint_post(post["id"])["issues"]}
        self.assertIn("brand_violation", codes)
        self.assertIn("off_palette", codes)

    def test_on_brand_brief_passes(self):
        spec = self.crm.visual_spec("image")
        post = self.crm.create_channel_post({
            "channel_jid": "1@newsletter", "title": "صورة", "body": "نص",
            "status": "draft", "media_type": "image",
            "meta": json.dumps({"visual_brief": spec})})
        codes = {i["code"] for i in self.crm.lint_post(post["id"])["issues"]}
        self.assertNotIn("brand_violation", codes)
        self.assertNotIn("off_palette", codes)

    def test_form_patch_is_validated(self):
        bad, problem = bridge_app._brand_patch({"palette_gold": "ذهبي"})
        self.assertEqual(problem, "invalid")
        self.assertEqual(bad, {})
        good, problem = bridge_app._brand_patch({
            "palette_gold": "#b08a3e", "name": "قناة", "tone": "هادئة",
            "font_display": "Tajawal", "dos": "سطر أول\nسطر ثانٍ",
            "limit_chars": "1500", "format_image": "1080x1350",
            "logo_mode": "text_name_only", "visual_never": "ختم\nتوقيع",
            "text_max_words": "6"})
        self.assertEqual(problem, "")
        self.assertEqual(good["palette"]["gold"], "#B08A3E")
        self.assertEqual(good["limits"]["max_chars"], 1500)
        self.assertEqual(good["visual"]["formats"]["image"], "1080x1350")
        self.assertEqual(good["visual"]["logo"]["never"], ["ختم", "توقيع"])
        self.assertEqual(good["visual"]["text_on_image"]["max_words"], 6)

    def test_bad_format_is_rejected(self):
        _, problem = bridge_app._brand_patch({"format_image": "كبير"})
        self.assertEqual(problem, "invalid")


if __name__ == "__main__":
    unittest.main()
