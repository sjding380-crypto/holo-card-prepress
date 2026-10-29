"""Behavior checks for source-faithful prepress exports; no model or network needed."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageChops, ImageDraw


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepress.py"


class PrepressTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "Missing reusable annotation/export helper")
        spec = importlib.util.spec_from_file_location("prepress", SCRIPT)
        self.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.api)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.png"
        im = Image.new("RGBA", (120, 180), (19, 42, 71, 255))
        draw = ImageDraw.Draw(im)
        draw.rectangle((10, 10, 70, 35), fill=(255, 185, 30, 255))
        draw.ellipse((35, 60, 85, 115), fill=(230, 181, 145, 255))
        im.save(self.source)
        self.source_bytes = self.source.read_bytes()
        self.plan = self.root / "plan.json"
        self.plan.write_text(json.dumps({"elements": [
            {"id": "F01", "label": "标题", "treatment": "foil",
             "reason": "建立上部视觉焦点", "polygon": [[10, 10], [70, 10], [70, 35], [10, 35]]},
            {"id": "P01", "label": "脸部", "treatment": "protect",
             "reason": "保护肤色", "polygon": [[35, 60], [85, 60], [85, 115], [35, 115]]}
        ]}, ensure_ascii=False), encoding="utf-8")
        self.job = self.root / "job"
        self.masks = self.root / "masks"
        self.masks.mkdir()

    def annotate(self):
        self.api.annotate(self.source, self.plan, self.job)

    def approve(self):
        self.api.approve(self.job, ["F01"], "用户明确回复：同意 F01 发闪，P01 保持白墨。")

    def make_mask(self, size=(120, 180)):
        mask = Image.new("L", size, 0)
        ImageDraw.Draw(mask).rectangle((10, 10, 70, 35), fill=255)
        mask.save(self.masks / "F01.png")
        return mask

    def test_annotation_only_produces_review_and_preserves_source(self):
        self.annotate()
        self.assertTrue((self.job / "01_annotation.png").is_file())
        self.assertFalse((self.job / "delivery" / "01_color.png").exists())
        self.assertEqual(self.source.read_bytes(), self.source_bytes)
        with Image.open(self.job / "01_annotation.png") as preview:
            self.assertGreater(preview.width, 120)

    def test_cmyk_is_not_exported_with_an_incompatible_rgb_pixel_mode(self):
        path = self.root / "cmyk.jpg"
        Image.new("CMYK", (120, 180), (10, 20, 30, 0)).save(path)
        with self.assertRaisesRegex(ValueError, "RGB|CMYK"):
            self.api.annotate(path, self.plan, self.job)
        self.assertFalse((self.job / "01_annotation.png").exists())

    def test_export_requires_recorded_user_confirmation(self):
        self.annotate()
        self.make_mask()
        with self.assertRaisesRegex(ValueError, "confirm|确认"):
            self.api.export(self.job, self.masks)
        self.assertFalse((self.job / "delivery").exists())

    def test_approval_rejects_protected_or_unknown_elements(self):
        self.annotate()
        for ids in (["P01"], ["F99"]):
            with self.assertRaises(ValueError):
                self.api.approve(self.job, ids, "用户确认")

    def test_color_source_mask_polarity_cutout_and_alignment(self):
        self.annotate()
        self.approve()
        mask = self.make_mask()
        self.api.export(self.job, self.masks)
        d = self.job / "delivery"
        with Image.open(self.source) as source, Image.open(d / "01_color.png") as color:
            self.assertEqual(color.size, source.size)
            self.assertEqual(color.convert("RGBA").tobytes(), source.convert("RGBA").tobytes())
        with Image.open(d / "02_white_ink_rgba.png") as white:
            self.assertEqual(white.getpixel((20, 20)), (255, 255, 255, 0))
            self.assertEqual(white.getpixel((60, 80)), (255, 255, 255, 255))
            self.assertEqual(ImageChops.add(white.getchannel("A"), mask).getextrema(), (255, 255))
        with Image.open(d / "cutouts" / "F01_color.png") as cutout:
            self.assertEqual(cutout.size, (120, 180))
            self.assertEqual(cutout.getpixel((20, 20)), (255, 185, 30, 255))
            self.assertEqual(cutout.getpixel((60, 80))[3], 0)
        self.assertEqual(self.source.read_bytes(), self.source_bytes)

    def test_edited_plan_invalidates_old_confirmation_even_after_reannotation(self):
        self.annotate()
        self.approve()
        data = json.loads(self.plan.read_text(encoding="utf-8"))
        data["elements"][0]["label"] = "更改后的标题范围"
        self.plan.write_text(json.dumps(data), encoding="utf-8")
        self.annotate()
        self.make_mask()
        with self.assertRaisesRegex(ValueError, "changed|变化|失效"):
            self.api.export(self.job, self.masks)

    def test_changed_source_invalidates_confirmation(self):
        self.annotate()
        self.approve()
        Image.new("RGB", (120, 180), "red").save(self.source)
        self.make_mask()
        with self.assertRaisesRegex(ValueError, "changed|变化|失效"):
            self.api.export(self.job, self.masks)

    def test_wrong_mask_size_fails_without_partial_delivery(self):
        self.annotate()
        self.approve()
        self.make_mask((60, 90))
        with self.assertRaisesRegex(ValueError, "size|尺寸"):
            self.api.export(self.job, self.masks)
        self.assertFalse((self.job / "delivery").exists())

    def test_missing_final_mask_does_not_fall_back_to_rough_polygon(self):
        self.annotate()
        self.approve()
        with self.assertRaisesRegex(ValueError, "mask|蒙版"):
            self.api.export(self.job, self.masks)
        self.assertFalse((self.job / "delivery").exists())

    def test_final_requires_proof_confirmation(self):
        self.annotate()
        self.approve()
        self.make_mask()
        self.api.export(self.job, self.masks)
        with self.assertRaisesRegex(ValueError, "proof|确认"):
            self.api.review(self.job, "final", "approve", "可以定稿")
        self.api.review(self.job, "proof", "approve", "炫彩位置满意，继续")
        final = self.api.review(self.job, "final", "approve", "此版可以定稿")
        self.assertEqual(final["decision"], "approve")

    def test_modified_files_invalidate_effect_review(self):
        self.annotate()
        self.approve()
        self.make_mask()
        self.api.export(self.job, self.masks)
        self.api.review(self.job, "proof", "approve", "满意")
        Image.new("RGBA", (120, 180), "white").save(self.job / "delivery" / "02_white_ink_rgba.png")
        with self.assertRaisesRegex(ValueError, "changed|确认|变化"):
            self.api.review(self.job, "final", "approve", "可以")

    def test_revision_request_is_not_approval(self):
        self.annotate()
        self.approve()
        self.make_mask()
        self.api.export(self.job, self.masks)
        self.api.review(self.job, "proof", "revise", "缩小标题发闪范围")
        with self.assertRaises(ValueError):
            self.api.review(self.job, "final", "approve", "可以")

    def test_antialias_and_original_alpha_are_preserved(self):
        im = Image.open(self.source).convert("RGBA")
        im.putpixel((20, 20), (255, 185, 30, 128))
        im.save(self.source)
        self.annotate()
        self.approve()
        mask = self.make_mask()
        mask.putpixel((20, 20), 128)
        mask.save(self.masks / "F01.png")
        self.api.export(self.job, self.masks)
        with Image.open(self.job / "delivery" / "02_white_ink_rgba.png") as white:
            self.assertIn(white.getpixel((20, 20))[3], (63, 64))
        with Image.open(self.job / "delivery" / "cutouts" / "F01_color.png") as cutout:
            self.assertIn(cutout.getpixel((20, 20))[3], (63, 64))


if __name__ == "__main__":
    unittest.main(verbosity=2)
