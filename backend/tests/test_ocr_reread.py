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
