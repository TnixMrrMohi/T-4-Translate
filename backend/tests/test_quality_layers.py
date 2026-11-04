"""لایهٔ کیفیت: وابستگی‌های سنگین اختیاری‌اند و در نبودشان رفتار قبلی حفظ می‌شود."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app import bubbles, cleaning, inpaint, ocr, rendering, textdet


def test_inpaint_reports_unavailable_and_returns_input(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_MODELS_DIR", str(tmp_path / "models"))
    assert inpaint.available() is False
    image = np.full((24, 24, 3), 200, np.uint8)
    masks = [np.zeros((24, 24), bool)]
    assert inpaint.refine(image, image.copy(), masks) is not None
    assert inpaint._session() is None


def test_ocr_uses_bundled_model_when_server_model_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_MODELS_DIR", str(tmp_path / "models"))
    assert ocr._model_options() == {}


def test_smart_masks_narrows_to_glyphs_and_falls_back(tmp_path, monkeypatch):
    image = np.full((60, 80, 3), 255, np.uint8)
    fallback = [np.ones((60, 80), bool)]
    glyphs = np.zeros((60, 80), bool)
    glyphs[10:20, 10:30] = True          # فقط جای حروف
    monkeypatch.setattr(textdet, "available", lambda: True)
    monkeypatch.setattr(textdet, "masks", lambda array: {"text": glyphs, "bubble": None})

    narrowed = cleaning._smart_masks(np, __import__("cv2"), image, [(5, 5, 40, 25)], fallback)
    assert len(narrowed) == 1
    mask = narrowed[0]
    assert mask[15, 15] and not mask[50, 70]          # بیرون از کادر دست‌نخورده
    assert int(mask.sum()) < int(fallback[0].sum())    # نازک‌تر از ماسک کادر

    # کادری که مدل در آن متنی ندید: همان ماسک پیش‌فرض.
    assert cleaning._smart_masks(np, __import__("cv2"), image, [(45, 40, 70, 58)], fallback) is fallback


def test_smart_masks_without_detector_returns_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_MODELS_DIR", str(tmp_path / "models"))
    image = np.full((20, 20, 3), 255, np.uint8)
    fallback = [np.zeros((20, 20), bool)]
    assert cleaning._smart_masks(np, __import__("cv2"), image, [(0, 0, 10, 10)], fallback) is fallback


def test_detector_places_outside_lines_inside_its_bubble(tmp_path, monkeypatch):
    import cv2

    page = tmp_path / "page.png"
    Image.new("RGB", (200, 200), "white").save(page)
    bubble_mask = np.zeros((200, 200), np.uint8)
    cv2.ellipse(bubble_mask, (100, 100), (60, 40), 0, 0, 360, color=1, thickness=-1)
    bubble_mask = bubble_mask.astype(bool)
    monkeypatch.setattr(textdet, "available", lambda: True)
    monkeypatch.setattr(textdet, "masks", lambda array: {"text": None, "bubble": bubble_mask})

    lines = [
        {"text": "inside", "quad": [[80, 90], [120, 90], [120, 110], [80, 110]]},
        {"text": "outside", "quad": [[5, 5], [25, 5], [25, 20], [5, 20]]},
    ]
    placed: list = []
    remaining = bubbles._detector_place(lines, placed, [1, 2], page, np, cv2)

    assert remaining == [2]                      # خط بیرونِ حباب همان‌جا می‌ماند
    assert len(placed) == 1
    bubble = placed[0]
    assert bubble["lines"] == [1]
    assert bubble["kind"] == "speech"
    assert bubble["features"]["detector"] == "comic-text-detector"
    assert 40 <= bubble["bbox"][2] <= 130        # پهنای همان بیضی، نه کل صفحه


def test_detector_place_is_noop_without_model(tmp_path, monkeypatch):
    import cv2

    monkeypatch.setattr(textdet, "available", lambda: False)
    page = tmp_path / "page.png"
    Image.new("RGB", (50, 50), "white").save(page)
    lines = [{"text": "x", "quad": [[1, 1], [9, 1], [9, 9], [1, 9]]}]
    assert bubbles._detector_place(lines, [], [1], page, np, cv2) == [1]


def test_rendering_falls_back_without_raqm(monkeypatch):
    monkeypatch.setattr(rendering, "has_raqm", lambda: False)
    rendering.shape_text.cache_clear()
    rendering._font.cache_clear()
    assert rendering.shape_text("سلام") != "سلام"     # ترتیب نمایشی
    font = rendering._font(18)
    assert rendering.text_width(font, "سلام") > 0
    rendering.shape_text.cache_clear()
    rendering._font.cache_clear()


def test_rendering_keeps_logical_text_with_raqm(monkeypatch):
    monkeypatch.setattr(rendering, "has_raqm", lambda: True)
    rendering.shape_text.cache_clear()
    assert rendering.shape_text("سلام") == "سلام"
    assert rendering._rtl_kwargs("سلام") == {"direction": "rtl", "language": "fa"}
    assert rendering._rtl_kwargs("Hello") == {}
    rendering.shape_text.cache_clear()


def test_detector_input_size_prefers_fixed_shape():
    assert textdet._input_size([1, 3, 1024, 1024], 800, 500) == (1024, 1024)
    height, width = textdet._input_size([1, 3, "height", "width"], 1000, 750)
    assert height % 32 == 0 and width % 32 == 0
    assert height <= 1536 and width <= 1536
    # نبودِ شکل هم مشکلی نمی‌سازد.
    assert textdet._input_size([], 100, 100) == (96, 96)


def test_detector_outputs_are_chosen_by_name_and_thickness():
    import cv2

    size = 96
    bubble = np.zeros((1, 1, size, size), np.float32)
    cv2.circle(bubble[0, 0], (48, 48), 30, 1.0, -1)
    text = np.zeros((1, 1, size, size), np.float32)
    cv2.line(text[0, 0], (20, 48), (76, 48), 1.0, 3)
    block = np.zeros((1, 2, size, size), np.float32)

    # نام‌ها شناخته‌شده‌اند.
    chosen = textdet._choose(np, ["blk", "seg", "det"], [block, bubble, text], size, size)
    assert chosen["text"].sum() < chosen["bubble"].sum()
    assert np.array_equal(chosen["text"], text[0, 0] > 0.5)

    # نام‌ها بی‌معنی‌اند: نازک‌ترین ماسک متن حساب می‌شود.
    nameless = textdet._choose(np, ["o1", "o2", "o3"], [block, bubble, text], size, size)
    assert nameless["text"].sum() < nameless["bubble"].sum()

    # خروجی لاگیت (منفی) هم درست آستانه می‌خورد.
    logits = (text[0, 0] * 20.0 - 10.0)[None, None]
    assert textdet._as_mask(np, logits, size, size).any()


def test_detector_ignores_non_mask_outputs():
    vector = np.zeros((1, 6), np.float32)
    assert textdet._as_mask(np, vector, 32, 32) is None
    assert textdet._choose(np, ["a"], [vector], 32, 32) == {}


def test_inpaint_binds_second_input_as_mask():
    class FakeSession:
        def __init__(self):
            self.seen = None

        def run(self, outputs, feeds):
            self.seen = feeds
            return [np.full((1, 3, 8, 8), 128, np.uint8)]

    session = FakeSession()
    image = np.full((8, 8, 3), 200, np.uint8)
    mask = np.zeros((8, 8), bool)
    mask[2:5, 2:5] = True
    inpaint._session_cache.update(session=session, failed=False,
                                  inputs=["image", "mask_image"], output="out")
    try:
        out = inpaint._run(np, __import__("cv2"), image, mask.astype(np.uint8) * 255)
    finally:
        inpaint._session_cache.update(session=None, failed=False, inputs=[], output=None)
    assert out is not None and out.shape == (8, 8, 3)
    assert set(session.seen) == {"image", "mask_image"}
    # ماسکِ صفر و یک (نه ۰..۲۵۵) به مدل داده می‌شود.
    assert float(session.seen["mask_image"].max()) == 1.0


def test_ocr_model_options_point_to_installed_server_model(tmp_path, monkeypatch):
    """وقتی مدل دقیق نصب است، مسیر هر سه فایل (det/rec/فهرست نویسه‌ها) داده می‌شود."""
    import json

    monkeypatch.setenv("T4_MODELS_DIR", str(tmp_path / "models"))
    root = tmp_path / "models" / "ocr-server" / "1"
    root.mkdir(parents=True)
    names = ["ch_PP-OCRv4_det_server_infer.onnx", "ch_PP-OCRv4_rec_server_infer.onnx", "ch_dict.txt"]
    for name in names:
        (root / name).write_bytes(b"x")
    (tmp_path / "models" / "ocr-server" / "installed.json").write_text(json.dumps({
        "revision": "1",
        "files": {name: {"size": 1, "sha256": "0" * 64} for name in names},
    }), encoding="utf-8")

    options = ocr._model_options()
    assert set(options) == {"det_model_path", "rec_model_path", "rec_keys_path"}
    assert options["rec_keys_path"].endswith("ch_dict.txt")

    # نصفه‌کاره (بدون فهرست نویسه‌ها) هم کار می‌کند ولی rec_keys_path ندارد.
    (root / "ch_dict.txt").unlink()
    trimmed = ocr._model_options()
    assert "rec_keys_path" not in trimmed and len(trimmed) == 2


def test_ocr_engine_uses_detailed_model_and_falls_back(tmp_path, monkeypatch):
    import sys
    import types

    calls: list[dict] = []

    class FakeRapid:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            if 'det_model_path' in kwargs:
                raise RuntimeError("مدل دقیق بارگذاری نشد")

    module = types.ModuleType("rapidocr_onnxruntime")
    module.RapidOCR = FakeRapid
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", module)
    monkeypatch.setattr(ocr, "_model_options", lambda: {"det_model_path": "d", "rec_model_path": "r"})
    getattr(ocr._engine, "cache_clear", lambda: None)()
    engine = ocr._engine()
    assert isinstance(engine, FakeRapid)
    # اول با مدل دقیق تلاش شد، بعد مدل پیش‌فرض ساخته شد.
    assert calls[0]['det_model_path']=='d' and calls[0]['rec_model_path']=='r'
    assert 'det_model_path' not in calls[1] and 'rec_model_path' not in calls[1]
    assert calls[1]['intra_op_num_threads']==4
    assert calls[1]['inter_op_num_threads']==1
    getattr(ocr._engine, "cache_clear", lambda: None)()
