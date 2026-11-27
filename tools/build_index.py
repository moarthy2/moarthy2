#!/usr/bin/env python3
"""Validate uploads, write cleaned capes, and rebuild index.json."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")
UPLOAD_RE = re.compile(r"^(uuid|name)-(.+)$")
MAX_UPLOAD_BYTES = 20 * 1024
SIZES = {(64, 32), (128, 64)}


class BuildError(Exception):
    pass


def empty_index() -> dict:
    return {"version": 1, "generated": "", "uuids": {}, "names": {}}


def normalize_uuid(value: str) -> str:
    try:
        return uuid.UUID(value).hex
    except ValueError as error:
        raise BuildError(f"invalid UUID {value!r}") from error


def normalize_name(value: str) -> str:
    if not NAME_RE.fullmatch(value):
        raise BuildError(f"invalid name {value!r}")
    return value.lower()


def parse_key(value: str) -> tuple[str, str]:
    match = UPLOAD_RE.fullmatch(value)
    if not match:
        raise BuildError(f"invalid upload key {value!r}")
    kind, rest = match.groups()
    if kind == "uuid":
        return "uuid", normalize_uuid(rest)
    return "name", normalize_name(rest)


def load_index(root: Path) -> dict:
    path = root / "index.json"
    if not path.exists():
        return empty_index()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError(f"index.json is not valid JSON: {error}") from error
    if data.get("version") != 1:
        raise BuildError("index.json has an unsupported version")
    uuids = data.get("uuids", {})
    names = data.get("names", {})
    if not isinstance(uuids, dict) or not isinstance(names, dict):
        raise BuildError("index.json uuids and names must be objects")
    for key, value in uuids.items():
        normalize_uuid(key)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{16}", value):
            raise BuildError("index.json has an invalid uuid hash")
    for key, value in names.items():
        normalize_name(key)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{16}", value):
            raise BuildError("index.json has an invalid name hash")
    return {
        "version": 1,
        "generated": data.get("generated", ""),
        "uuids": {normalize_uuid(key): value.lower() for key, value in uuids.items()},
        "names": {normalize_name(key): value.lower() for key, value in names.items()},
    }


def clean_png(source: Path, destination: Path) -> bytes:
    if source.stat().st_size > MAX_UPLOAD_BYTES:
        raise BuildError(f"{source.name}: file is larger than 20 KB")
    try:
        with Image.open(source) as image:
            image.verify()
        with Image.open(source) as image:
            if image.format != "PNG":
                raise BuildError(f"{source.name}: not a PNG")
            if getattr(image, "n_frames", 1) != 1:
                raise BuildError(f"{source.name}: animated PNGs are not accepted")
            if image.size not in SIZES:
                raise BuildError(f"{source.name}: expected 64x32 or 128x64, got {image.size[0]}x{image.size[1]}")
            image.load()
            cleaned = image.convert("RGBA")
            cleaned.info = {}
            cleaned.save(destination, format="PNG", optimize=True, compress_level=9)
    except BuildError:
        raise
    except Exception as error:
        raise BuildError(f"{source.name}: not a readable PNG: {error}") from error
    if destination.stat().st_size > MAX_UPLOAD_BYTES:
        raise BuildError(f"{source.name}: cleaned PNG is larger than 20 KB")
    with Image.open(destination) as check:
        if check.size not in SIZES:
            raise BuildError(f"{source.name}: cleaned PNG changed dimensions")
    data = destination.read_bytes()
    return data


def prepare_uploads(root: Path, temp: Path) -> list[tuple[str, str, str, bytes, Path]]:
    uploads = root / "uploads"
    if not uploads.exists():
        return []
    prepared: list[tuple[str, str, str, bytes, Path]] = []
    for source in sorted(uploads.iterdir()):
        if source.name in {".gitkeep", "remove.txt"}:
            if not source.is_file():
                raise BuildError(f"{source.name}: must be a regular file")
            continue
        if not source.is_file():
            raise BuildError(f"{source.name}: must be a regular file")
        if source.suffix != ".png":
            raise BuildError(f"{source.name}: uploads must end in .png")
        kind, key = parse_key(source.stem)
        destination = temp / f"{source.stem}.png"
        data = clean_png(source, destination)
        hash16 = hashlib.sha256(data).hexdigest()[:16]
        prepared.append((kind, key, hash16, data, source))
    return prepared


def parse_remove(root: Path) -> list[tuple[str, str]]:
    path = root / "uploads" / "remove.txt"
    if not path.exists():
        return []
    removed: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        removed.append(parse_key(line))
    return removed


def write_index(root: Path, index: dict) -> None:
    index["version"] = 1
    index["generated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    index["uuids"] = dict(sorted(index["uuids"].items()))
    index["names"] = dict(sorted(index["names"].items()))
    text = json.dumps(index, indent=2, ensure_ascii=True) + "\n"
    (root / "index.json").write_text(text, encoding="utf-8")


def main(root: Path | None = None) -> int:
    root = root or ROOT
    uploads = root / "uploads"
    capes = root / "capes"
    try:
        remove = parse_remove(root)
        with TemporaryDirectory() as directory:
            prepared = prepare_uploads(root, Path(directory))
        if not prepared and not remove:
            print("nothing to do")
            return 0

        index = load_index(root)
        capes.mkdir(parents=True, exist_ok=True)
        for kind, key, hash16, data, _source in prepared:
            target = capes / f"{hash16}.png"
            target.write_bytes(data)
            if kind == "uuid":
                index["uuids"][key] = hash16
            else:
                index["names"][key] = hash16
        for kind, key in remove:
            if kind == "uuid":
                index["uuids"].pop(key, None)
            else:
                index["names"].pop(key, None)

        referenced = set(index["uuids"].values()) | set(index["names"].values())
        for path in capes.glob("*.png"):
            if path.stem not in referenced:
                path.unlink()

        for _kind, _key, _hash16, _data, source in prepared:
            source.unlink()
        remove_file = uploads / "remove.txt"
        if remove_file.exists():
            remove_file.unlink()
        (uploads / ".gitkeep").touch()

        write_index(root, index)
        print(f"wrote {len(index['uuids'])} uuid entries, {len(index['names'])} name entries")
        return 0
    except BuildError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
