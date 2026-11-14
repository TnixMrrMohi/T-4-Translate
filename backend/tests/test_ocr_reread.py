"""بازخوانی خط‌به‌خط: کادر از موتور تشخیص، متن از تکهٔ صاف‌شدهٔ همان کادر.

ریشهٔ باگ واقعی: روی عکس کاربر، موتور دسته‌ای «THIS IS MY» را با اطمینان ۰٫۹۷ به
«KW SI SIHI» تبدیل می‌کرد، چون همهٔ کادرها را با نسبتِ یکسانِ دسته به مدل بازشناسی
می‌داد. این تست‌ها همان سناریو را با موتور جعلی بازسازی می‌کنند: تشخیص درست،
خواندن دسته‌ای غلط، خواندن تک‌تکه درست.
"""
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from app import ocr


class FakeEngine:
    """موتور جعلی: تشخیص را درست می‌دهد و بازشناسیِ دسته‌ای را غلط."""

    def __init__(self, boxes, batch_text="KW SI SIHI", line_text="THIS IS MY",
                 line_confidence=0.97, batch_confidence=0.94):
        self.boxes = boxes
        self.batch_text = batch_text
        self.line_text = line_text
        self.line_confidence = line_confidence
        self.batch_confidence = batch_confidence
        self.det_calls = 0
        self.batch_calls = 0
        self.rec_inputs: list[np.ndarray] = []

    def __call__(self, image, use_det=None, use_cls=None, use_rec=None):
        if use_rec is False:
            self.det_calls += 1
            return [list(box) for box in self.boxes], [0.01]
        # مسیر دسته‌ای: همان نتیجه‌ای که روی عکس واقعی خراب می‌خواند.
        self.batch_calls += 1
        return [(list(box), self.batch_text, self.batch_confidence) for box in self.boxes], [0.07]

    def text_rec(self, crops):
        crop = crops[0]
        self.rec_inputs.append(crop)
        return [(self.line_text, self.line_confidence)], [0.02]


def sample_image(path, size=(470, 341)):
    Image.new("RGB", size, "white").save(path)
    return path


def boxes_for_three_lines():
    return [
        [[199, 98], [282, 98], [282, 136], [199, 136]],
        [[129, 141], [353, 140], [353, 179], [130, 180]],
        [[151, 188], [328, 188], [328, 220], [151, 220]],
    ]


def test_batch_misread_is_fixed_by_line_reread(monkeypatch, tmp_path):
    """همان سناریوی عکس کاربر: نتیجهٔ دسته‌ای غلط، بازخوانی خط‌به‌خط درست."""
    page = sample_image(tmp_path / "page.png")
    engine = FakeEngine(boxes_for_three_lines()[:1])
    monkeypatch.setattr(ocr, "_engine", lambda: engine)

    # مسیر قدیمی (دسته‌ای) همین متن غلط را می‌داد.
    batch, _ = engine(np.array(Image.open(page).convert("RGB")))
    assert batch[0][1] == "KW SI SIHI"

    lines = ocr.recognize(page)
    assert [line["text"] for line in lines] == ["THIS IS MY"]
    # کادرِ برگشتی همان کادر تشخیص است (پیش‌نمایش و پاک‌سازی به آن وابسته‌اند).
    assert lines[0]["quad"] == [[float(x), float(y)] for x, y in boxes_for_three_lines()[0]]
    assert lines[0]["confidence"] == pytest.approx(0.97, abs=1e-6)


def test_each_line_gets_its_own_crop_and_they_differ(monkeypatch, tmp_path):
    page = sample_image(tmp_path / "page.png")
    engine = FakeEngine(boxes_for_three_lines())
    monkeypatch.setattr(ocr, "_engine", lambda: engine)

    lines = ocr.recognize(page)
    assert len(lines) == 3
    # یک گذر دسته‌ای (تشخیص + خواندن اولیه) و بعد سه بازشناسی جدا برای سه خط.
    assert engine.batch_calls == 1
    assert len(engine.rec_inputs) == 3
    shapes = {crop.shape for crop in engine.rec_inputs}
    # هر خط تکّهٔ خودش را دارد؛ پهنای خط وسط از بقیه بیشتر است.
    widths = sorted(crop.shape[1] for crop in engine.rec_inputs)
    assert widths[0] < widths[-1]
    assert len(shapes) >= 2
    # ارتفاعِ تکه به ارتفاع استانداردِ مدل نزدیک است (بزرگ‌شدن انجام شده).
    for crop in engine.rec_inputs:
        assert crop.shape[0] >= ocr.MIN_LINE_HEIGHT


def test_low_confidence_falls_back_to_previous_text(monkeypatch, tmp_path):
    """اگر بازخوانی ضعیف باشد، نتیجهٔ قبلی حفظ می‌شود و چیزی از دست نمی‌رود."""
    page = sample_image(tmp_path / "page.png")
    engine = FakeEngine(boxes_for_three_lines()[:1], line_text="¿?", line_confidence=0.10)
    monkeypatch.setattr(ocr, "_engine", lambda: engine)
    lines = ocr.recognize(page)
    # هیچ متنی با اطمینان خیلی کم جای متن قبلی را نمی‌گیرد.
    assert lines[0]["text"] == "KW SI SIHI"
    assert lines[0]["confidence"] == pytest.approx(0.94)


def test_failing_line_recognition_keeps_batch_result(monkeypatch, tmp_path):
    page = sample_image(tmp_path / "page.png")

    class Broken(FakeEngine):
        def text_rec(self, crops):
            raise RuntimeError("مدل بازشناسی خطا داد")

    engine = Broken(boxes_for_three_lines())
    monkeypatch.setattr(ocr, "_engine", lambda: engine)
    lines = ocr.recognize(page)
    assert [line["text"] for line in lines] == ["KW SI SIHI"] * 3
    assert all(line["confidence"] == pytest.approx(0.94) for line in lines)


def test_upside_down_line_is_read_after_flip(monkeypatch, tmp_path):
    """خط وارونه: تلاش اول ضعیف است، نسخهٔ چرخیده خوانده می‌شود."""
    page = sample_image(tmp_path / "page.png")

    class Flipping(FakeEngine):
        def text_rec(self, crops):
            crop = crops[0]
            self.rec_inputs.append(crop)
            # فقط نسخهٔ ۱۸۰-درجه‌چرخیده خوب خوانده می‌شود.
            if np.array_equal(crop, np.ascontiguousarray(crop[::-1, ::-1])):
                return [(self.line_text, 0.96)], [0.02]
            return [("", 0.0)], [0.02]

    engine = Flipping(boxes_for_three_lines()[:1], line_text="READ ME")
    monkeypatch.setattr(ocr, "_engine", lambda: engine)
    lines = ocr.recognize(page)
    assert lines[0]["text"] == "READ ME"
    assert lines[0]["confidence"] > 0.9


def test_line_crop_is_straightened_and_scaled():
    """کجیِ کادر در تکهٔ خروجی برداشته می‌شود و ارتفاع به حد مدل می‌رسد."""
    image = np.full((200, 300, 3), 255, np.uint8)
    tilted = [[50, 40], [200, 60], [196, 84], [46, 64]]     # کج و کم‌ارتفاع
    crop = ocr._line_crop(image, tilted)
    assert crop is not None
    assert crop.shape[0] >= ocr.MIN_LINE_HEIGHT
    assert crop.shape[1] >= 100

    # کادر نامعتبر → None (نتیجهٔ دسته‌ای می‌ماند).
    assert ocr._line_crop(image, [[0, 0], [1, 1]]) is None
    assert ocr._line_crop(image, [[5, 5]] * 4) is None
    assert ocr._line_crop(image, None) is None


def test_wide_line_is_not_upscaled_past_the_width_cap():
    """خط پهن بزرگ‌تر از سقف نمی‌شود؛ خط خیلی پهن هم دست‌نخورده (بدون بادکردن) می‌ماند."""
    image = np.full((80, 2000, 3), 255, np.uint8)
    box = [[0, 10], [1600, 10], [1600, 48], [0, 48]]
    crop = ocr._line_crop(image, box)
    assert crop is not None
    assert crop.shape[1] <= ocr.MAX_LINE_WIDTH
    assert crop.shape[0] >= ocr.MIN_LINE_HEIGHT

    # حالت افراطی: عرض طبیعی از سقف بیشتر است → بزرگ‌نمایی انجام نمی‌شود.
    huge = np.full((80, 4000, 3), 255, np.uint8)
    thin = [[0, 10], [3999, 10], [3999, 20], [0, 20]]
    flat = ocr._line_crop(huge, thin)
    assert flat is not None
    assert flat.shape[1] == 3999 and flat.shape[0] == 10


def test_load_bgr_returns_three_channels(tmp_path):
    """تصویرِ شفاف/خاکستری هم سه‌کانالهٔ BGR می‌شود تا تصمیم مدل یکسان بماند."""
    rgba = tmp_path / "rgba.png"
    Image.new("RGBA", (40, 30), (200, 10, 10, 255)).save(rgba)
    array = ocr._load_bgr(rgba)
    assert array.ndim == 3 and array.shape[2] == 3
    assert array.shape[:2] == (30, 40)
    # قرمز RGB باید در کانال سوم (BGR) بیفتد.
    assert int(array[0, 0, 2]) > 150 and int(array[0, 0, 0]) < 60

    gray = tmp_path / "gray.png"
    Image.new("L", (20, 10), 128).save(gray)
    assert ocr._load_bgr(gray).shape == (10, 20, 3)


def test_real_engine_reads_user_sample_when_available(tmp_path):
    """اگر بستهٔ OCR نصب است، متنِ نمونهٔ کاربر درست خوانده می‌شود (تست تدریجی)."""
    pytest.importorskip("rapidocr_onnxruntime")
    font = None
    for candidate in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(candidate, 30)
            break
        except OSError:
            continue
    if font is None:
        pytest.skip("فونت آزمایشی پیدا نشد")

    page = tmp_path / "sample.png"
    canvas = Image.new("RGB", (420, 180), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((30, 40), "THIS IS MY", font=font, fill="black")
    draw.text((30, 100), "VICTORY.", font=font, fill="black")
    canvas.save(page)

    lines = ocr.recognize(page)
    text = " ".join(line["text"] for line in lines).replace(" ", "").upper()
    assert "THISISMY" in text and "VICTORY" in text


def test_equal_confidence_still_prefers_line_reread(monkeypatch, tmp_path):
    """روی نمونهٔ واقعی، خواندنِ غلط و درست هر دو ۰٫۹۷ بودند؛ اطمینان معیار نیست."""
    page = sample_image(tmp_path / "page.png")
    engine = FakeEngine(boxes_for_three_lines()[:1], line_confidence=0.97,
                        batch_confidence=0.97)
    monkeypatch.setattr(ocr, "_engine", lambda: engine)
    lines = ocr.recognize(page)
    assert lines[0]["text"] == "THIS IS MY"


def test_short_reread_does_not_replace_confident_batch_text(monkeypatch, tmp_path):
    """اگر تکه بریده شده باشد (متن کوتاه‌تر) و دسته‌ای مطمئن باشد، دسته‌ای می‌ماند."""
    page = sample_image(tmp_path / "page.png")
    engine = FakeEngine(boxes_for_three_lines()[:1], batch_text="THIS IS MY VICTORY.",
                        line_text="THIS", line_confidence=0.99, batch_confidence=0.95)
    monkeypatch.setattr(ocr, "_engine", lambda: engine)
    assert ocr.recognize(page)[0]["text"] == "THIS IS MY VICTORY."


def test_low_confidence_reread_is_ignored(monkeypatch, tmp_path):
    """متنِ بازخوانی با اطمینان خیلی کم جای متن قبلی را نمی‌گیرد."""
    page = sample_image(tmp_path / "page.png")
    engine = FakeEngine(boxes_for_three_lines()[:1], line_text="|||", line_confidence=0.2,
                        batch_confidence=0.6)
    monkeypatch.setattr(ocr, "_engine", lambda: engine)
    assert ocr.recognize(page)[0]["text"] == "KW SI SIHI"


def test_punctuation_quad_extends_for_ellipsis_and_quotes_without_catching_dust():
    """علائم نگارشی هم‌رنگ و هم‌تراز در لبه‌های کادر جذب می‌شوند، اما ذرات نویز کنار متن نادیده گرفته می‌شوند."""
    cv2 = pytest.importorskip("cv2")
    canvas = np.full((120, 420, 3), (35, 25, 15), np.uint8)
    ink = (255, 210, 80)  # آبی روشن در BGR
    # بدنهٔ متن داخل کادر [70..200, 30..78]
    cv2.rectangle(canvas, (76, 32), (190, 74), ink, -1)
    # گیومهٔ باز چپِ کادر
    cv2.rectangle(canvas, (44, 32), (58, 50), ink, -1)
    # سه نقطهٔ راستِ کادر (نقطهٔ اول لبه‌به‌لبه و دو نقطهٔ بعدی بیرون)
    cv2.rectangle(canvas, (195, 62), (207, 74), ink, -1)
    cv2.rectangle(canvas, (215, 62), (227, 74), ink, -1)
    cv2.rectangle(canvas, (235, 62), (247, 74), ink, -1)
    # ذرات نویز کم‌رنگ یا خارج از تراز عمودی که نباید جذب شوند
    cv2.rectangle(canvas, (254, 84), (266, 96), (160, 160, 160), -1)
    cv2.rectangle(canvas, (256, 42), (260, 46), (220, 220, 220), -1)

    quad = [[70.0, 30.0], [200.0, 30.0], [200.0, 78.0], [70.0, 78.0]]
    extended = ocr._extend_punctuation_quads([(quad, "USED TO SAY", 0.9)], canvas)
    out_quad = extended[0][0]
    xs = [pt[0] for pt in out_quad]
    ys = [pt[1] for pt in out_quad]
    assert min(xs) <= 44.0
    assert max(xs) >= 247.0
    assert max(xs) < 254.0
    assert min(ys) == pytest.approx(30.0)
    assert max(ys) == pytest.approx(78.0)


def test_punctuation_quad_does_not_overlap_neighboring_quad():
    """کادر گسترش‌یافته نباید وارد محدودهٔ کادر همسایه شود."""
    cv2 = pytest.importorskip("cv2")
    canvas = np.full((120, 320, 3), 255, np.uint8)
    cv2.rectangle(canvas, (24, 32), (116, 76), (10, 10, 10), -1)
    cv2.rectangle(canvas, (144, 62), (156, 74), (10, 10, 10), -1)
    cv2.rectangle(canvas, (162, 32), (240, 76), (10, 10, 10), -1)

    quad_a = [[20.0, 30.0], [120.0, 30.0], [120.0, 78.0], [20.0, 78.0]]
    quad_b = [[140.0, 30.0], [244.0, 30.0], [244.0, 78.0], [140.0, 78.0]]
    extended = ocr._extend_punctuation_quads([(quad_a, "A", 0.9), (quad_b, "B", 0.9)], canvas)
    assert max(pt[0] for pt in extended[0][0]) <= 140.0


def test_punctuation_quad_leaves_blank_box_unchanged():
    """کادر روی تصویر سفید یک‌دست بدون هیچ تغییری برمی‌گردد."""
    pytest.importorskip("cv2")
    canvas = np.full((120, 300, 3), 255, np.uint8)
    quad = [[20.0, 30.0], [150.0, 30.0], [150.0, 78.0], [20.0, 78.0]]
    extended = ocr._extend_punctuation_quads([(quad, "EMPTY", 0.9)], canvas)
    assert extended[0][0] == quad


def test_engine_disables_batch_orientation_classifier(monkeypatch):
    """طبقه‌بند ۱۸۰درجه در گذر دسته‌ای خاموش است تا فونت‌های کمیک وارونه و حذف نشوند."""
    import sys
    import types

    calls = []

    class FakeRapid:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    module = types.ModuleType("rapidocr_onnxruntime")
    module.RapidOCR = FakeRapid
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", module)
    monkeypatch.setattr(ocr, "_model_options", lambda: {})
    getattr(ocr._engine, "cache_clear", lambda: None)()
    try:
        ocr._engine()
        assert calls and calls[-1]["use_cls"] is False
    finally:
        getattr(ocr._engine, "cache_clear", lambda: None)()


def test_prefer_reread_preserves_spaces_and_avoids_lower_confidence():
    """اگر بازخوانی فاصلهٔ کلمات را حذف کند یا افت اطمینان داشته باشد، متن دسته‌ای حفظ می‌شود."""
    # افت اطمینان روی متن مطمئن
    assert ocr._prefer_reread(("MAGTC EMPEROR WHO", 0.90), ("MAGTC EMPErOr WHO", 0.78)) is False
    # حذف فاصلهٔ بین کلمات (چسبیدن کلمات به هم) روی متن مطمئن
    assert ocr._prefer_reread(("WZITTEN BY THEANCIENT", 0.88), ("WZITTEN BITHEANCENT", 0.93)) is False
    # بازخوانی موفق با حفظ یا بهبود اطمینان و ساختار کلمات
    assert ocr._prefer_reread(("TRANSMITTEDA LEGEND", 0.93), ("TRANSMITTED A LEGEND", 0.95)) is True


def test_collision_aware_horizontal_pad_limits_expansion_near_neighbors():
    """قاعدهٔ شفاف: اگر کادر همسایه نزدیک بود، اصلاً گسترش انجام نمی‌شود؛ اگر آزاد بود گسترش کامل انجام می‌شود."""
    box1 = np.array([[10.0, 10.0], [50.0, 10.0], [50.0, 30.0], [10.0, 30.0]], dtype=np.float32)
    # جعبهٔ دوم در فاصلهٔ ۴ پیکسلی سمت راست (کمتر از ۱۶ پیکسل حاشیهٔ امن)
    box2 = np.array([[54.0, 10.0], [100.0, 10.0], [100.0, 30.0], [54.0, 30.0]], dtype=np.float32)

    pad_l, pad_r = ocr._collision_free_horizontal_pad(box1, [box1, box2], target_pad_w=0.10, safe_clearance=16.0)
    # سمت چپ همسایه‌ای ندارد و کاملاً آزاد است: گسترش کامل (۱۰٪ از ۴۰ = ۴.۰)
    assert pad_l == pytest.approx(4.0, abs=1e-3)
    # سمت راست همسایه نزدیک است (۴ پیکسل): اصلاً گسترش داده نمی‌شود (۰٫۰)
    assert pad_r == 0.0


def test_resolve_line_collisions_separates_overlapping_stacked_boxes():
    """اگر دو کادر متوالی در یک ستون هم‌پوشانی عمودی داشته باشند، مرز بین آنها دقیقاً نصف و جدا می‌شود."""
    # خط اول: y از ۱۰ تا ۳۰
    line1 = ([[10.0, 10.0], [100.0, 10.0], [100.0, 30.0], [10.0, 30.0]], "LINE 1", 0.95)
    # خط دوم: y از ۲۶ تا ۴۶ (۴ پیکسل هم‌پوشانی عمودی با خط اول)
    line2 = ([[10.0, 26.0], [100.0, 26.0], [100.0, 46.0], [10.0, 46.0]], "LINE 2", 0.92)

    resolved = ocr._resolve_line_collisions([line1, line2])
    q1 = np.array(resolved[0][0])
    q2 = np.array(resolved[1][0])

    y1_bot = max(q1[2, 1], q1[3, 1])
    y2_top = min(q2[0, 1], q2[1, 1])
    # هم‌پوشانی صفر یا منفی است (فاصله دارند):
    assert y1_bot < y2_top
    assert y2_top - y1_bot >= 1.0


