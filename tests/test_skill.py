#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from PIL import Image

import vision
from vlib import config, images, ledger, runs


class JsonExtraction(unittest.TestCase):
    def test_plain_object_and_array(self):
        self.assertEqual(runs.extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(runs.extract_json("[1, 2]"), [1, 2])

    def test_fenced_block(self):
        self.assertEqual(runs.extract_json('```json\n{"a": 2}\n```'), {"a": 2})

    def test_lead_in_prose(self):
        self.assertEqual(runs.extract_json('Here is the JSON:\n{"a": 3}\nAnything else?'), {"a": 3})

    def test_scalar_and_garbage(self):
        self.assertIsNone(runs.extract_json("42"))
        self.assertIsNone(runs.extract_json("no json at all"))
        self.assertIsNone(runs.extract_json('{"a": NaN}'))


class Money(unittest.TestCase):
    def test_scale_resolution(self):
        self.assertEqual(ledger.money(None), "unknown")
        self.assertEqual(ledger.money(0.000214), "$0.000214")
        self.assertEqual(ledger.money(0.0123), "$0.0123")
        self.assertEqual(ledger.money(0.6123), "$0.6123")
        self.assertEqual(ledger.money(983.3218), "$983.32")


class TokenBudget(unittest.TestCase):
    def test_defaults_follow_effort(self):
        self.assertEqual(vision.resolve_tokens("high", 0), 6000)
        self.assertEqual(vision.resolve_tokens("medium", 0), 6000)
        self.assertEqual(vision.resolve_tokens("low", 0), 2000)
        self.assertEqual(vision.resolve_tokens("high", 1200), 1200)


class Prep(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vision_test_"))

    def test_auto_format_follows_source(self):
        png = self.tmp / "shot.png"
        Image.new("RGB", (40, 30), (10, 120, 200)).save(png)
        jpg = self.tmp / "photo.jpg"
        Image.new("RGB", (40, 30), (10, 120, 200)).save(jpg, "JPEG")
        out = self.tmp / "out"
        manifest = self.tmp / "manifest.json"
        variants = images.variant_list("full", long_edge=20, name="small")
        results = images.prepare(png, out, variants, manifest=manifest)
        self.assertTrue(results[0]["path"].endswith(".png"))
        self.assertTrue(Path(results[0]["path"]).is_file())
        written = json.loads(manifest.read_text())
        self.assertEqual(list(written), ["variants"])
        self.assertEqual(written["variants"][0]["path"], results[0]["path"])
        jpeg_results = images.prepare(jpg, self.tmp / "out2", variants)
        self.assertTrue(jpeg_results[0]["path"].endswith(".jpg"))

    def test_forcing_png_for_a_photo(self):
        jpg = self.tmp / "photo.jpg"
        Image.new("RGB", (20, 20), (1, 2, 3)).save(jpg, "JPEG")
        results = images.prepare(jpg, self.tmp / "out", images.variant_list("full", long_edge=10), format="png")
        with Image.open(results[0]["path"]) as check:
            self.assertEqual(check.format, "PNG")


class ThreadSnapshots(unittest.TestCase):
    def test_snapshots_are_sent_verbatim(self):
        tmp = Path(tempfile.mkdtemp(prefix="vision_test_"))
        cfg = config.Config(api_key="test", state_dir=tmp)
        photo = tmp / "photo.jpg"
        Image.new("RGB", (64, 48), (200, 40, 40)).save(photo, "JPEG", quality=95)
        first = runs.snapshot_turn_images(cfg, "t", 1, [photo])
        first_path = runs.resolve_saved_path(first[0], cfg)
        first_bytes = first_path.read_bytes()
        self.assertEqual(images.upload_bytes(str(first_path))[1], first_bytes)
        # A later turn that reuses the snapshot must not add another JPEG generation.
        second = runs.snapshot_turn_images(cfg, "t", 2, [str(first_path)])
        self.assertEqual(runs.resolve_saved_path(second[0], cfg).read_bytes(), first_bytes)

    def test_plain_jpeg_is_renormalized(self):
        tmp = Path(tempfile.mkdtemp(prefix="vision_test_"))
        photo = tmp / "photo.jpg"
        Image.new("RGB", (64, 48), (200, 40, 40)).save(photo, "JPEG", quality=100)
        self.assertNotEqual(images.upload_bytes(photo)[1], photo.read_bytes())


class Completion(unittest.TestCase):
    def cfg(self):
        return config.Config(api_key="test", state_dir=Path(tempfile.mkdtemp(prefix="vision_test_")))

    def image(self, cfg):
        path = cfg.state_dir / "card.png"
        Image.new("RGB", (32, 24), (5, 5, 5)).save(path)
        return str(path)

    def body(self, content, finish):
        return {
            "id": "gen-test",
            "model": "google/gemini-4-neon",
            "provider": "Google AI Studio",
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "cost": 0.0002},
        }

    def call(self, cfg, body, request):
        with mock.patch.object(vision.client, "chat", return_value=body):
            return vision.do_call(cfg, request, quiet=True)

    def request(self, cfg, json_mode=False):
        return vision.Request(model="google/gemini-4-neon", prompt="What number?", image_paths=[self.image(cfg)], effort="low", max_tokens=500, tag="unit", json_mode=json_mode)

    def test_missing_finish_reason_with_an_answer_succeeds(self):
        cfg = self.cfg()
        result = self.call(cfg, self.body("42", None), self.request(cfg))
        self.assertTrue(result["meta"]["success"])
        self.assertFalse(result["skipped"])

    def test_length_finish_fails_even_with_content(self):
        cfg = self.cfg()
        with self.assertRaises(ValueError):
            self.call(cfg, self.body("42", "length"), self.request(cfg))

    def test_structured_answer_needs_parseable_json(self):
        cfg = self.cfg()
        with self.assertRaises(ValueError):
            self.call(cfg, self.body("not json", "stop"), self.request(cfg, json_mode=True))
        cfg = self.cfg()
        result = self.call(cfg, self.body('Sure:\n{"n": 42}', "stop"), self.request(cfg, json_mode=True))
        self.assertEqual(result["parsed"], {"n": 42})


class BatchAccounting(unittest.TestCase):
    def test_resumed_rows_are_not_reported_as_new_calls(self):
        rows = [
            {"tag": "a", "cost": 0.01, "skipped": False},
            {"tag": "b", "cost": 0.02, "skipped": True},
            {"tag": "c", "error": "boom", "cost": None, "skipped": False},
        ]
        summary = vision.batch_summary(rows, 4)
        self.assertEqual(summary["completed"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["resumed"], 1)
        self.assertEqual(summary["new_calls"], 1)
        self.assertAlmostEqual(summary["new_cost"], 0.01)
        self.assertAlmostEqual(vision.budget_spent(rows), 0.01)


if __name__ == "__main__":
    unittest.main()
