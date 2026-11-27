from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo

import build_index


def make_png(path: Path, size: tuple[int, int] = (64, 32), color=(20, 40, 80, 255), text: str | None = None) -> None:
    image = Image.new("RGBA", size, color)
    info = PngInfo()
    if text:
        info.add_text("Comment", text)
    image.save(path, format="PNG", pnginfo=info)


def read_index(root: Path) -> dict:
    return json.loads((root / "index.json").read_text(encoding="utf-8"))


class BuildIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "uploads").mkdir()
        (self.root / "capes").mkdir()
        (self.root / "uploads" / ".gitkeep").write_text("", encoding="utf-8")
        (self.root / "index.json").write_text(
            json.dumps({"version": 1, "generated": "old", "uuids": {}, "names": {}}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_name_upload_is_cleaned_and_indexed(self) -> None:
        source = self.root / "uploads" / "name-Steve.png"
        make_png(source, text="remove me")

        self.assertEqual(build_index.main(self.root), 0)

        index = read_index(self.root)
        self.assertEqual(index["version"], 1)
        self.assertEqual(set(index["names"]), {"steve"})
        self.assertNotEqual(index["generated"], "old")
        hash16 = index["names"]["steve"]
        self.assertRegex(hash16, r"^[0-9a-f]{16}$")
        cape = self.root / "capes" / f"{hash16}.png"
        self.assertTrue(cape.exists())
        self.assertEqual(hashlib.sha256(cape.read_bytes()).hexdigest()[:16], hash16)
        self.assertNotIn(b"tEXt", cape.read_bytes())
        self.assertFalse(source.exists())
        self.assertTrue((self.root / "uploads" / ".gitkeep").exists())

    def test_uuid_upload_is_normalized(self) -> None:
        source = self.root / "uploads" / "uuid-069A79F4-44E9-4726-A5BE-FCA90E38AAF5.png"
        make_png(source, size=(128, 64))

        self.assertEqual(build_index.main(self.root), 0)

        index = read_index(self.root)
        self.assertEqual(set(index["uuids"]), {"069a79f444e94726a5befca90e38aaf5"})
        self.assertNotIn("069A79F4-44E9-4726-A5BE-FCA90E38AAF5", index["uuids"])

    def test_invalid_upload_leaves_everything_unchanged(self) -> None:
        source = self.root / "uploads" / "name-Steve.png"
        make_png(source, size=(16, 16))
        before_index = (self.root / "index.json").read_text(encoding="utf-8")

        self.assertEqual(build_index.main(self.root), 1)
        self.assertEqual((self.root / "index.json").read_text(encoding="utf-8"), before_index)
        self.assertTrue(source.exists())
        self.assertEqual(list((self.root / "capes").iterdir()), [])

    def test_non_png_and_bad_names_are_rejected(self) -> None:
        bad = self.root / "uploads" / "name-not a name.png"
        bad.write_bytes(b"not a png")
        before_index = (self.root / "index.json").read_text(encoding="utf-8")

        self.assertEqual(build_index.main(self.root), 1)
        self.assertEqual((self.root / "index.json").read_text(encoding="utf-8"), before_index)
        self.assertTrue(bad.exists())

    def test_non_png_with_valid_name_is_rejected(self) -> None:
        bad = self.root / "uploads" / "name-Steve.png"
        bad.write_bytes(b"not a png")
        before_index = (self.root / "index.json").read_text(encoding="utf-8")

        self.assertEqual(build_index.main(self.root), 1)
        self.assertEqual((self.root / "index.json").read_text(encoding="utf-8"), before_index)
        self.assertTrue(bad.exists())

    def test_oversized_upload_is_rejected(self) -> None:
        source = self.root / "uploads" / "name-Steve.png"
        make_png(source, text="x" * 22000)
        self.assertGreater(source.stat().st_size, 20 * 1024)
        before_index = (self.root / "index.json").read_text(encoding="utf-8")

        self.assertEqual(build_index.main(self.root), 1)
        self.assertEqual((self.root / "index.json").read_text(encoding="utf-8"), before_index)
        self.assertTrue(source.exists())

    def test_good_and_bad_uploads_are_all_or_nothing(self) -> None:
        good = self.root / "uploads" / "name-good.png"
        bad = self.root / "uploads" / "name-bad.png"
        make_png(good)
        make_png(bad, size=(10, 10))
        before_index = (self.root / "index.json").read_text(encoding="utf-8")

        self.assertEqual(build_index.main(self.root), 1)
        self.assertEqual((self.root / "index.json").read_text(encoding="utf-8"), before_index)
        self.assertTrue(good.exists())
        self.assertTrue(bad.exists())
        self.assertEqual(list((self.root / "capes").iterdir()), [])

    def test_remove_entries_and_orphans(self) -> None:
        for name, data in {"aaaaaaaaaaaaaaaa": b"one", "bbbbbbbbbbbbbbbb": b"two"}.items():
            (self.root / "capes" / f"{name}.png").write_bytes(data)
        (self.root / "capes" / "orphan0000000000.png").write_bytes(b"orphan")
        (self.root / "index.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "generated": "old",
                    "uuids": {"069a79f444e94726a5befca90e38aaf5": "aaaaaaaaaaaaaaaa"},
                    "names": {"steve": "bbbbbbbbbbbbbbbb"},
                }
            ),
            encoding="utf-8",
        )
        (self.root / "uploads" / "remove.txt").write_text(
            "uuid-069a79f4-44e9-4726-a5be-fca90e38aaf5\nname-Steve\n", encoding="utf-8"
        )

        self.assertEqual(build_index.main(self.root), 0)

        index = read_index(self.root)
        self.assertEqual(index["uuids"], {})
        self.assertEqual(index["names"], {})
        self.assertEqual(list((self.root / "capes").iterdir()), [])
        self.assertFalse((self.root / "uploads" / "remove.txt").exists())

    def test_empty_run_does_not_rewrite_index(self) -> None:
        before = (self.root / "index.json").read_bytes()
        before_mtime = (self.root / "index.json").stat().st_mtime_ns

        self.assertEqual(build_index.main(self.root), 0)

        self.assertEqual((self.root / "index.json").read_bytes(), before)
        self.assertEqual((self.root / "index.json").stat().st_mtime_ns, before_mtime)

    def test_invalid_remove_key_aborts(self) -> None:
        (self.root / "uploads" / "remove.txt").write_text("name-not a name\n", encoding="utf-8")
        before_index = (self.root / "index.json").read_text(encoding="utf-8")

        self.assertEqual(build_index.main(self.root), 1)
        self.assertEqual((self.root / "index.json").read_text(encoding="utf-8"), before_index)
        self.assertTrue((self.root / "uploads" / "remove.txt").exists())

    def test_unsupported_index_version_aborts(self) -> None:
        (self.root / "index.json").write_text('{"version": 2}', encoding="utf-8")
        before = (self.root / "index.json").read_text(encoding="utf-8")
        make_png(self.root / "uploads" / "name-Steve.png")

        self.assertEqual(build_index.main(self.root), 1)
        self.assertEqual((self.root / "index.json").read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
