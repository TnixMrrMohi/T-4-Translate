"""آزمون دسته‌بندی بالن؛ تصاویر مصنوعی‌اند و کادرهای OCR دستی ساخته می‌شوند."""
import math
import random
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app import bubbles


def _page(path: Path, draw_shapes, size=(600, 800)) -> Path:
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    draw_shapes(draw, size)
    image.save(path)
    return path


def _line(quad):
    return {"text": "x", "confidence": 0.9,
            "quad": [[quad[0], quad[1]], [quad[2], quad[1]], [quad[2], quad[3]], [quad[0], quad[3]]]}


def _text_lines(cx, cy, count=2, width=120, height=22):
    lines = []
    for index in range(count):
        top = cy - (count * (height + 8)) // 2 + index * (height + 8)
        lines.append(_line([cx - width // 2, top, cx + width // 2, top + height]))
    return lines


def _analyze(tmp_path, path, lines):
    return bubbles.analyze(path, lines)


def test_ellipse_bubble_is_speech(tmp_path):
    def shapes(draw, size):
        draw.ellipse([150, 250, 450, 550], outline=0, width=4)
        draw.ellipse([440, 400, 470, 430], fill=0)  # دنبالهٔ بالن
    page = _page(tmp_path / "speech.png", shapes)
    result = _analyze(tmp_path, page, _text_lines(300, 400))
    assert result["bubbles"], result
    bubble = result["bubbles"][0]
    assert bubble["kind"] == "speech", bubble
    assert bubble["lines"] == [1, 2]
    assert bubble["fonts"] == ["Koodak Bold", "Roya Bold"]
    assert bubble["style"]["bold"] is True


def test_rectangle_bubble_is_square(tmp_path):
    def shapes(draw, size):
        draw.rectangle([120, 200, 480, 500], outline=0, width=4)
    page = _page(tmp_path / "square.png", shapes)
    result = _analyze(tmp_path, page, _text_lines(300, 350))
    assert result["bubbles"][0]["kind"] == "square", result["bubbles"][0]


def test_hexagon_bubble_is_hexagon(tmp_path):
    def shapes(draw, size):
        points = []
        for index in range(6):
            angle = math.radians(60 * index - 30)
            points.append((300 + 180 * math.cos(angle), 350 + 170 * math.sin(angle)))
        draw.polygon(points, outline=0, width=4)
    page = _page(tmp_path / "hex.png", shapes)
    result = _analyze(tmp_path, page, _text_lines(300, 350))
    assert result["bubbles"][0]["kind"] == "hexagon", result["bubbles"][0]


def test_spiky_bubble_is_shout(tmp_path):
    def shapes(draw, size):
        points = []
        for index in range(20):
            radius = 200 if index % 2 == 0 else 110
            angle = math.radians(18 * index)
            points.append((300 + radius * math.cos(angle), 350 + radius * math.sin(angle)))
        draw.polygon(points, outline=0, width=3)
    page = _page(tmp_path / "shout.png", shapes)
    result = _analyze(tmp_path, page, _text_lines(300, 350))
    assert result["bubbles"][0]["kind"] in {"shout", "solar", "monster"}, result["bubbles"][0]


def test_thought_dots_make_thought_bubble(tmp_path):
    def shapes(draw, size):
        draw.ellipse([220, 250, 480, 470], outline=0, width=4)
        draw.ellipse([170, 490, 196, 516], outline=0, width=3)
        draw.ellipse([130, 530, 150, 550], outline=0, width=3)
    page = _page(tmp_path / "thought.png", shapes)
    result = _analyze(tmp_path, page, _text_lines(350, 360, count=1))
    assert result["bubbles"][0]["kind"] == "thought_bubble", result["bubbles"][0]


def test_text_without_bubble_is_outside(tmp_path):
    def shapes(draw, size):
        for index in range(3):
            draw.rectangle([100, 100 + index * 40, 500, 125 + index * 40], fill=0)
    page = _page(tmp_path / "outside.png", shapes)
    lines = [_line([100, 100 + index * 40, 500, 125 + index * 40]) for index in range(3)]
    result = _analyze(tmp_path, page, lines)
    assert len(result["bubbles"]) == 1
    bubble = result["bubbles"][0]
    assert bubble["kind"] == "outside"
    assert bubble["lines"] == [1, 2, 3]
    assert {variant["id"] for variant in bubble["variants"]} >= {"outside_whisper", "system"}


def test_trembling_edge_is_fear(tmp_path):
    def shapes(draw, size):
        random.seed(7)
        points = []
        for index in range(160):
            angle = math.radians(index * 360 / 160)
            radius = 170 + random.uniform(-9, 9)
            points.append((300 + radius * math.cos(angle), 350 + radius * math.sin(angle)))
        draw.polygon(points, outline=0, width=3)
    page = _page(tmp_path / "fear.png", shapes)
    kind = _analyze(tmp_path, page, _text_lines(300, 350))["bubbles"][0]["kind"]
    assert kind in {"fear", "speech"}, kind


def test_two_bubbles_get_separate_entries(tmp_path):
    def shapes(draw, size):
        draw.ellipse([60, 80, 260, 260], outline=0, width=4)
        draw.rectangle([320, 420, 560, 620], outline=0, width=4)
    page = _page(tmp_path / "two.png", shapes)
    lines = _text_lines(160, 170, count=1) + _text_lines(440, 520, count=1)
    result = _analyze(tmp_path, page, lines)
    kinds = sorted(bubble["kind"] for bubble in result["bubbles"])
    assert kinds == ["speech", "square"], result["bubbles"]
    assert sorted(number for bubble in result["bubbles"] for number in bubble["lines"]) == [1, 2]


def test_catalog_matches_the_pdf_lists():
    assert bubbles.BUBBLE_TYPES["shout"]["fonts"][0] == "Afsaneh"
    assert "B Morvarid" in bubbles.BUBBLE_TYPES["thought_bubble"]["fonts"]
    assert bubbles.BUBBLE_TYPES["hexagon"]["fonts"] == ["Farnaz"]
    assert "Dast Nevis" in bubbles.BUBBLE_TYPES["outside"]["variants"]["outside_whisper"]["fonts"]
    assert "Dima Abdi" in bubbles.BUBBLE_TYPES["outside"]["variants"]["technique"]["fonts"]
    assert bubbles.BUBBLE_TYPES["solar"]["style"]["italic"] is True


def test_overlay_draws_every_bubble(tmp_path):
    def shapes(draw, size):
        draw.ellipse([150, 250, 450, 550], outline=0, width=4)
    page = _page(tmp_path / "overlay.png", shapes)
    document = _analyze(tmp_path, page, _text_lines(300, 400))
    image = bubbles.overlay(page, document, max_side=400)
    assert image.width <= 400 and image.height <= 400
    assert image.getbbox() is not None


def test_invalid_quad_goes_outside(tmp_path):
    def shapes(draw, size):
        draw.ellipse([150, 250, 450, 550], outline=0, width=4)
    page = _page(tmp_path / "bad.png", shapes)
    result = bubbles.analyze(page, [{"text": "x", "quad": [[0, 0], [1, 1]]}, _line([250, 380, 350, 420])])
    outside = [bubble for bubble in result["bubbles"] if bubble["kind"] == "outside"][0]
    assert outside["lines"] == [1]


def test_missing_file_raises(tmp_path):
    with pytest.raises(bubbles.BubbleError):
        bubbles.analyze(tmp_path / "nope.png", [])
