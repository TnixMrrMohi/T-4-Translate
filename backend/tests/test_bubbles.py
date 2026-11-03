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


def _merged_page(path):
    """دو بالن که هم را لمس کرده‌اند (مثل «I'VE SLOWED…» و «WE MAY CONVERSE…»)."""
    def shapes(draw, size):
        draw.ellipse([60, 80, 330, 330], outline=0, width=4)
        draw.ellipse([240, 260, 560, 560], outline=0, width=4)
    return _page(path, shapes, size=(600, 700))


def test_touching_bubbles_are_split_into_two(tmp_path):
    page = _merged_page(tmp_path / "merged.png")
    lines = (_text_lines(190, 165, count=1, width=120)
             + _text_lines(190, 200, count=1, width=140)
             + _text_lines(390, 380, count=1, width=120)
             + _text_lines(390, 420, count=1, width=130))
    result = bubbles.analyze(page, lines)
    bubbles_found = [bubble for bubble in result["bubbles"] if bubble["kind"] != "outside"]
    assert len(bubbles_found) == 2, result["bubbles"]
    assert sorted(bubble["lines"] for bubble in bubbles_found) == [[1, 2], [3, 4]]
    # هر بالن یک بلوک جدا با متن خودش می‌شود.
    blocks = bubbles.blocks(result, lines)
    assert len(blocks) == 2
    assert [block["lines"] for block in blocks] == [[1, 2], [3, 4]]


def test_single_bubble_with_two_lines_is_not_split(tmp_path):
    def shapes(draw, size):
        draw.ellipse([150, 250, 450, 550], outline=0, width=4)
    page = _page(tmp_path / "one.png", shapes)
    lines = _text_lines(300, 380, count=2)
    result = bubbles.analyze(page, lines)
    bubbles_found = [bubble for bubble in result["bubbles"] if bubble["kind"] != "outside"]
    assert len(bubbles_found) == 1
    assert bubbles_found[0]["lines"] == [1, 2]


def test_block_bbox_uses_bubble_geometry_only_when_it_contains_the_text():
    """کادر [x,y,w,h] بالن باید به [چپ، بالا، راست، پایین] تبدیل و با کادر خطوط تلاقی شود."""
    by_number = {1: {"text": "hello", "quad": [[150, 200], [250, 200], [250, 240], [150, 240]]}}

    # کادر شکل (x, y, w, h) بزرگ‌تر از متن است.
    block = bubbles._block([1], by_number, "speech", [100, 150, 200, 300])
    assert block["bbox"] == [150, 200, 250, 240]

    # کادر شکل با مبدأ جابه‌جا (باگ قبلی: w/h به‌جای راست/پایین استفاده می‌شد).
    block = bubbles._block([1], by_number, "speech", [140, 190, 120, 60])
    left, top, right, bottom = block["bbox"]
    assert right - left < 200 and bottom - top < 200
    assert left <= 150 and top <= 200 and right >= 250 and bottom >= 240


def test_split_uses_page_origin_of_the_mask():
    """رگرسیون: کادر خطوط صفحه‌ای است ولی ماسک محلی؛ بدون تبدیل، هیچ بالنِ چسبیده جدا نمی‌شد."""
    import cv2
    import numpy as np

    mask = np.zeros((200, 260), np.uint8)
    cv2.ellipse(mask, (80, 90), (70, 70), 0, 0, 360, 1, -1)
    cv2.ellipse(mask, (180, 130), (65, 60), 0, 0, 360, 1, -1)
    boxes = {1: (360, 380, 150, 210), 2: (420, 440, 250, 310)}  # (بالا، پایین، چپ، راست) صفحه
    parts = bubbles._split_bubbles(mask, boxes, (100, 300))
    assert len(parts) == 2
    assert sorted(part_lines for _, part_lines in parts) == [[1], [2]]


def test_growth_reaches_far_edge_of_a_wide_bubble():
    """رگرسیون: پنجرهٔ متقارن، لبهٔ دورِ بالنِ پهن را می‌برید و خط را «بیرون بالن» می‌کرد."""
    import cv2
    import numpy as np

    bright = np.zeros((300, 900), np.uint8)
    cv2.ellipse(bright, (450, 150), (390, 130), 0, 0, 360, 1, -1)
    blob, origin, enclosed = bubbles._grow_from((820, 150), bright, 300, 900)
    assert enclosed
    assert blob is not None
    assert origin[0] <= 61 and blob.shape[1] >= 770


def test_seed_point_ignores_tiny_bright_specks():
    """رگرسیون: پیکسل روشنِ ریز داخل حرف، رشد ۱۶ پیکسلی می‌داد و خط بیرون بالن شمرده می‌شد."""
    import numpy as np

    bright = np.ones((120, 120), np.uint8)
    bright[40:80, 40:80] = 0      # حرف تیره
    bright[58:61, 58:61] = 1      # لکهٔ روشن ۳×۳ داخل حرف
    seed = bubbles._seed_point(bright, [30, 30, 90, 90])
    blob, _, _ = bubbles._grow_from(seed, bright, 120, 120)
    assert blob is not None and int(blob.sum()) > 1000


def test_block_area_is_the_bubble_geometry_for_font_sizing():
    """کادر شکل (area) جدا از کادر متن نگه داشته می‌شود تا اندازهٔ قلم به بالن بستگی داشته باشد."""
    by_number = {1: {"text": "hello", "quad": [[150, 200], [250, 200], [250, 240], [150, 240]]}}
    block = bubbles._block([1], by_number, "speech", [100, 150, 200, 300])
    assert block["bbox"] == [150, 200, 250, 240]           # کادر متن
    assert block["area"] == [100, 150, 300, 450]            # کادر شکل بالن

    # کادری که کادر متن را در بر نمی‌گیرد قابل اعتماد نیست.
    block = bubbles._block([1], by_number, "speech", [220, 210, 40, 20])
    assert block["bbox"] == [150, 200, 250, 240]
    assert block["area"] is None

    # کادر بی‌اندازه بزرگ (تشخیص نادرست) هم نادیده گرفته می‌شود.
    block = bubbles._block([1], by_number, "speech", [0, 0, 600, 800])
    assert block["area"] is None

    # بالن بزرگ با متن OCR کم‌ارتفاعِ ۸ پیکسلی نباید به‌خاطر نسبت ارتفاع/مساحت حذف شود.
    tiny_line = {1: {"text": "...", "quad": [[145, 140], [265, 140], [265, 148], [145, 148]]}}
    block = bubbles._block([1], tiny_line, "speech", [50, 30, 310, 230])
    assert block["bbox"] == [145, 140, 265, 148]
    assert block["area"] == [50, 30, 360, 260]

    # بدون بالن (مثلاً متن بیرون بالن) کادر شکل وجود ندارد.
    block = bubbles._block([1], by_number, "outside", [])
    assert block["bbox"] == [150, 200, 250, 240]
    assert block["area"] is None
