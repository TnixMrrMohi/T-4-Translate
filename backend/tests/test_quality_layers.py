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
