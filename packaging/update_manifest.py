"""ساخت فهرست فایل‌های برنامه و بستهٔ تغییرات برای به‌روزرسانی خودکار.

دو خروجی:

* `update-manifest.json` — فهرست همهٔ فایل‌های نصب با هش sha256 و اندازه. برنامه با
  مقایسهٔ همین فهرست با فایل‌های نصب‌شده می‌فهمد چه چیزی عوض شده است.
* `update-<tag>.zip` — فقط فایل‌های تغییرکرده/تازه نسبت به فهرست ریلیز قبلی.

اجرا در CI (ویندوز):

    python packaging/update_manifest.py --dist dist/T4Translate --version 1.4.0 \
        --out dist/update-manifest.json --previous previous/update-manifest.json \
        --delta dist/update-v1.4.0.zip
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# این فایل‌ها هرگز جزء آپدیت نیستند: فایل موقت دانلود/اعمال و لاگ‌های محلی.
SKIP_NAMES = {".ds_store", "thumbs.db"}
SKIP_SUFFIXES = {".tmp", ".log", ".pyc"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect(dist: Path) -> list[dict]:
    """همهٔ فایل‌های پوشهٔ نصب با مسیر نسبی و هش."""
    files = []
    for path in sorted(dist.rglob("*")):
        if not path.is_file():
            continue
        if path.name.lower() in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        relative = path.relative_to(dist).as_posix()
        files.append({"path": relative, "size": path.stat().st_size, "sha256": sha256(path)})
    return files


def diff(current: list[dict], previous: dict | None) -> tuple[list[dict], list[str]]:
    """فایل‌های تغییرکرده/تازه و فایل‌های حذف‌شده نسبت به فهرست قبلی."""
    if not previous:
        return current, []
    old = {str(item.get("path")): str(item.get("sha256")) for item in previous.get("files") or []
           if isinstance(item, dict)}
    changed = [item for item in current if old.get(item["path"]) != item["sha256"]]
    removed = sorted(set(old) - {item["path"] for item in current})
    return changed, removed


def write_delta(dist: Path, changed: list[dict], destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for item in changed:
            bundle.write(dist / item["path"], item["path"])
    return destination.stat().st_size


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ساخت فهرست آپدیت T-4 Translate")
    parser.add_argument("--dist", required=True, type=Path, help="پوشهٔ نصب ساخته‌شده")
    parser.add_argument("--version", required=True, help="نسخهٔ همین ساخت")
    parser.add_argument("--out", required=True, type=Path, help="مسیر update-manifest.json")
    parser.add_argument("--previous", type=Path, help="فهرست ریلیز قبلی برای محاسبهٔ تغییرات")
    parser.add_argument("--delta", type=Path, help="مسیر بستهٔ تغییرات (update-<tag>.zip)")
    parser.add_argument("--summary", type=Path, help="خلاصهٔ JSON برای گزارش CI")
    args = parser.parse_args(argv)

    dist: Path = args.dist
    if not dist.is_dir():
        print(f"dist directory not found: {dist}", file=sys.stderr)
        return 2
    current = collect(dist)
    if not current:
        print("no files to publish", file=sys.stderr)
        return 2

    previous = None
    if args.previous and args.previous.is_file():
        try:
            previous = json.loads(args.previous.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = None

    changed, removed = diff(current, previous)
    manifest = {
        "version": args.version,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": current,
        "removed": removed,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    delta_bytes = 0
    if args.delta:
        delta_bytes = write_delta(dist, changed, args.delta)

    total_bytes = sum(item["size"] for item in current)
    changed_bytes = sum(item["size"] for item in changed)
    summary = {
        "version": args.version,
        "files": len(current),
        "totalBytes": total_bytes,
        "changed": len(changed),
        "changedBytes": changed_bytes,
        "removed": removed,
        "deltaBytes": delta_bytes,
        "previousVersion": (previous or {}).get("version"),
    }
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
