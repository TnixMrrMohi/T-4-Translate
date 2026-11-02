"""آزمون ابزار ساخت فهرست آپدیت و بستهٔ تغییرات (packaging/update_manifest.py)."""
import importlib.util
import json
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "packaging" / "update_manifest.py"


def _load():
    spec = importlib.util.spec_from_file_location("update_manifest", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def _app(root: Path, files: dict[str, bytes]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for relative, payload in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return root


def test_manifest_lists_every_file_and_skips_temp_files(tmp_path):
    module = _load()
    dist = _app(tmp_path / "dist", {
        "T4Translate.exe": b"exe",
        "web/index.html": b"<div id=root></div>",
        "web/app.js": b"js",
        "notes.log": b"log",
        "version.json": b"{}",
    })
    (dist / "web" / "half.tmp").write_bytes(b"tmp")
    files = module.collect(dist)
    paths = [item["path"] for item in files]
    assert paths == ["T4Translate.exe", "version.json", "web/app.js", "web/index.html"]
    assert all(len(item["sha256"]) == 64 for item in files)


def test_manifest_and_delta_only_include_changed_files(tmp_path):
    module = _load()
    old = _app(tmp_path / "old", {"app.exe": b"v1", "web/a.js": b"a", "web/gone.js": b"x"})
    previous = {"version": "1.0.0", "files": module.collect(old), "removed": []}
    previous_path = tmp_path / "previous.json"
    previous_path.write_text(json.dumps(previous), encoding="utf-8")

    dist = _app(tmp_path / "dist", {"app.exe": b"v2", "web/a.js": b"a", "web/new.js": b"n"})
    out = tmp_path / "update-manifest.json"
    delta = tmp_path / "update-v1.1.0.zip"
    assert module.main(["--dist", str(dist), "--version", "1.1.0", "--out", str(out),
                        "--previous", str(previous_path), "--delta", str(delta)]) == 0

    manifest = json.loads(out.read_text(encoding="utf-8"))
    assert manifest["version"] == "1.1.0"
    assert manifest["removed"] == ["web/gone.js"]
    with zipfile.ZipFile(delta) as bundle:
        names = sorted(bundle.namelist())
        assert names == ["app.exe", "web/new.js"]
        assert bundle.read("app.exe") == b"v2"
        # فایل دست‌نخورده دوباره در بستهٔ تغییرات نمی‌آید (همان «فقط آپدیت»).
        assert "web/a.js" not in names


def test_first_release_has_full_manifest_and_delta(tmp_path):
    module = _load()
    dist = _app(tmp_path / "dist", {"app.exe": b"v1", "web/a.js": b"a"})
    out = tmp_path / "manifest.json"
    delta = tmp_path / "delta.zip"
    assert module.main(["--dist", str(dist), "--version", "1.0.0", "--out", str(out),
                        "--delta", str(delta)]) == 0
    manifest = json.loads(out.read_text(encoding="utf-8"))
    assert manifest["removed"] == []
    assert {item["path"] for item in manifest["files"]} == {"app.exe", "web/a.js"}
    with zipfile.ZipFile(delta) as bundle:
        assert sorted(bundle.namelist()) == ["app.exe", "web/a.js"]


def test_missing_dist_is_an_error(tmp_path):
    module = _load()
    assert module.main(["--dist", str(tmp_path / "nope"), "--version", "1.0.0",
                        "--out", str(tmp_path / "m.json")]) == 2
