"""آزمون‌های نمایش آزمایشی ترجمهٔ فارسی روی تصویر."""
import pytest
from pathlib import Path
from PIL import Image, ImageDraw

pytest.importorskip("arabic_reshaper", reason="افزونهٔ رندر نصب نشده است")
pytest.importorskip("bidi", reason="افزونهٔ رندر نصب نشده است")

from app import rendering  # noqa: E402

PERSIAN = "سلام دنیا"


def _page(width=400, height=300, color="white"):
    return Image.new("RGB", (width, height), color)


def _line(quad, text="hello"):
    return {"text": text, "confidence": 0.9, "quad": quad}


def _box(left, top, right, bottom):
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def test_shaping_uses_presentation_forms():
    displayed = rendering.shape_text(PERSIAN)
    # حروف پایه (۰۶۰۰ تا ۰۶FF) جای خود را به شکل‌های Presentation Forms داده‌اند؛
    # یعنی متن reshaping شده و آمادهٔ رسم مستقیم است.
    assert not any("\u0600" <= char <= "\u06ff" for char in displayed)
    # «لا» به یک لیگاتور (U+FEFB/U+FEFC) تبدیل می‌شود، پس رشته کوتاه‌تر است.
    assert "\ufefb" in displayed or "\ufefc" in displayed
    assert len(displayed) < len(PERSIAN)


def test_shaping_reverses_for_display():
    displayed = rendering.shape_text(PERSIAN)
    reshaped = rendering._reshaper().reshape(PERSIAN)
    assert displayed == reshaped[::-1]


def test_wrap_text_keeps_words_and_respects_width():
    font = rendering._font(20)
    lines = rendering.wrap_text("یک دو سه چهار پنج شش هفت هشت", font, 60)
    assert len(lines) > 1
    assert " ".join(lines) == "یک دو سه چهار پنج شش هفت هشت"
    assert all(font.getlength(rendering.shape_text(line)) <= 60 for line in lines[:-1])


def test_render_draws_inside_quad_only():
    page = _page()
    rendered, drawn = rendering.render_translations(page, [_line(_box(40, 40, 200, 120))], {"1": PERSIAN})
    assert drawn == 1
    assert rendered.size == page.size
    # بیرون کادر دست‌نخورده می‌ماند.
    assert rendered.crop((0, 0, 38, 300)).tobytes() == page.crop((0, 0, 38, 300)).tobytes()
    assert rendered.crop((40, 40, 200, 120)).tobytes() != page.crop((40, 40, 200, 120)).tobytes()


def test_dark_background_uses_light_text():
    page = _page(color=(20, 20, 20))
    assert rendering._contrast_color(page, (0, 0, 50, 50)) == (245, 245, 245)
    assert rendering._contrast_color(_page(), (0, 0, 50, 50)) == (17, 17, 17)


def test_shrinks_font_to_fit_small_box():
    page = _page()
    long_text = "این یک جملهٔ بسیار طولانی برای یک کادر کوچک است "
    rendered, drawn = rendering.render_translations(page, [_line(_box(20, 20, 120, 70))], {"1": long_text})
    assert drawn == 1


def test_missing_translation_raises():
    with pytest.raises(rendering.RenderError):
        rendering.render_translations(_page(), [_line(_box(10, 10, 100, 60))], {"1": "   "})


def test_invalid_quad_raises():
    page = _page()
    with pytest.raises(rendering.RenderError):
        rendering.render_translations(page, [{"text": "x", "quad": [[0, 0]]}], {"1": PERSIAN})
    with pytest.raises(rendering.RenderError):
        rendering.render_translations(page, [{"text": "x", "quad": "bogus"}], {"1": PERSIAN})
    with pytest.raises(rendering.RenderError):
        rendering.render_translations(
            page, [{"text": "x", "quad": [[0, 0], [10, 0], [10, float("nan")], [0, 10]]}], {"1": PERSIAN})


def test_tiny_quad_raises():
    with pytest.raises(rendering.RenderError):
        rendering.render_translations(_page(), [_line(_box(10, 10, 12, 12))], {"1": PERSIAN})


def test_font_lookup_prefers_env_override(tmp_path, monkeypatch):
    custom = tmp_path / "custom.ttf"
    custom.write_bytes(rendering.font_path().read_bytes())
    monkeypatch.setenv("T4_FONT_PATH", str(custom))
    assert rendering.font_path() == custom


def test_font_lookup_supports_packaged_web_dir(tmp_path, monkeypatch):
    fonts = tmp_path / "web" / "fonts"
    fonts.mkdir(parents=True)
    (fonts / "Vazirmatn-Regular.ttf").write_bytes(rendering.font_path().read_bytes())
    monkeypatch.delenv("T4_FONT_PATH", raising=False)
    monkeypatch.setenv("T4_WEB_DIR", str(tmp_path / "web"))
    assert rendering.font_path() == fonts / "Vazirmatn-Regular.ttf"


def test_missing_font_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_FONT_PATH", str(tmp_path / "nope.ttf"))
    monkeypatch.setattr(rendering, "font_candidates", lambda: [tmp_path / "nope.ttf"])
    with pytest.raises(rendering.RenderError):
        rendering.font_path()


def test_render_blocks_fills_the_bubble_with_one_text():
    """هر بالن یک متن می‌گیرد و متن در کادر همان بالن (نه کادر یک خط) کشیده می‌شود."""
    image = Image.new("RGB", (400, 500), "white")
    blocks = [
        {"number": 1, "lines": [1, 2], "bbox": [80, 120, 320, 360], "kind": "speech", "tone": "گفت‌وگوی معمولی"},
        {"number": 2, "lines": [3], "bbox": [40, 400, 200, 470], "kind": "speech", "tone": "گفت‌وگوی معمولی"},
    ]
    canvas, drawn = rendering.render_blocks(image, blocks, {"1": "سلام دنیا", "2": "خداحافظ"})
    assert drawn == 2
    assert canvas.size == image.size
    assert canvas.crop((80, 120, 320, 360)).getbbox() is not None
    # بلوکی که ترجمه ندارد رسم نمی‌شود.
    _, drawn = rendering.render_blocks(image, blocks, {"1": "سلام دنیا"})
    assert drawn == 1
    with pytest.raises(rendering.RenderError):
        rendering.render_blocks(image, blocks, {})


def test_spiky_bubble_keeps_text_inside_a_smaller_area():
    """برای شکل دندانه‌دار، کادر متن بر اساس نسبت پر بودن کوچک‌تر می‌شود."""
    image = Image.new("RGB", (400, 300), "white")
    blocks = [
        {"number": 1, "lines": [1], "bbox": [20, 20, 380, 280], "kind": "shout", "fill": 0.62},
        {"number": 2, "lines": [2], "bbox": [20, 20, 380, 280], "kind": "speech", "fill": 0.98},
    ]
    translations = {"1": "از جلوی چشمم دور شو!", "2": "از جلوی چشمم دور شو!"}
    spiky, _ = rendering.render_blocks(image, [blocks[0]], translations)
    round_, _ = rendering.render_blocks(image, [blocks[1]], translations)
    spiky_ink = spiky.convert("L").point(lambda value: 255 if value < 200 else 0).getbbox()
    round_ink = round_.convert("L").point(lambda value: 255 if value < 200 else 0).getbbox()
    # متن شکل دندانه‌دار جمع‌تر و کوچک‌تر از همان متن در بالن گرد است.
    assert (spiky_ink[2] - spiky_ink[0]) < (round_ink[2] - round_ink[0])


def test_font_without_latin_falls_back_instead_of_tofu():
    """فونت مانهوا که حروف لاتین ندارد نباید جای متن لاتین مربع خالی بسازد."""
    pytest.importorskip("fontTools")  # بدون fontTools تشخیص پوشش گلیف ممکن نیست
    affsaneh = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "AFSANEH.ttf"
    if not affsaneh.is_file():
        pytest.skip("فونت افسانه در مخزن نیست")
    assert rendering.font_supports(str(affsaneh), "خوب جنگیدی")
    assert not rendering.font_supports(str(affsaneh), "kelgt")
    image = Image.new("RGB", (300, 200), "white")
    blocks = [{"number": 1, "lines": [1], "bbox": [30, 30, 270, 170], "kind": "shout", "fill": 0.8}]
    canvas, drawn = rendering.render_blocks(image, blocks, {"1": "kelgt"}, {"shout": str(affsaneh)})
    assert drawn == 1
    assert canvas.crop((30, 30, 270, 170)).getbbox() is not None


def _ink_box(image):
    """کادر جوهرِ رسم‌شده (متن تیره روی زمینهٔ روشن)."""
    return image.convert("L").point(lambda value: 255 if value < 200 else 0).getbbox()


def test_font_size_follows_the_bubble_area_not_the_text_box():
    """با کادر شکلِ بالن، قلم هم‌اندازهٔ بالن می‌شود نه کادر تنگِ متن اصلی."""
    image = Image.new("RGB", (420, 300), "white")
    text_box = [160, 140, 260, 165]
    plain = {"number": 1, "lines": [1], "bbox": text_box, "kind": "speech"}
    with_area = {"number": 2, "lines": [2], "bbox": text_box, "kind": "speech",
                 "area": [40, 60, 380, 240]}
    small, _ = rendering.render_blocks(image, [plain], {"1": "سلام"})
    big, _ = rendering.render_blocks(image, [with_area], {"2": "سلام"})
    small_ink, big_ink = _ink_box(small), _ink_box(big)
    assert small_ink and big_ink
    assert (big_ink[3] - big_ink[1]) > 1.6 * (small_ink[3] - small_ink[1])
    # متن از شکلِ بالن بیرون نمی‌زند.
    assert big_ink[0] >= 40 and big_ink[1] >= 60
    assert big_ink[2] <= 380 and big_ink[3] <= 240


def test_text_box_grows_over_uniform_background():
    """بدون کادر شکل، کادر متن تا لبهٔ ناحیهٔ یکدست بزرگ می‌شود تا قلم ریز نماند."""
    image = Image.new("RGB", (420, 300), "white")
    block = {"number": 1, "lines": [1], "bbox": [190, 140, 230, 160], "kind": "speech"}
    canvas, drawn = rendering.render_blocks(image, [block], {"1": "سلام"})
    assert drawn == 1
    ink = _ink_box(canvas)
    assert ink and (ink[3] - ink[1]) > 24          # بلندتر از کادر ۲۰ پیکسلی متن
    assert ink[0] > 0 and ink[2] < canvas.width      # ولی از کل صفحه بزرگ‌تر نشده


def test_growth_stops_at_a_bubble_border():
    """رشد کادر باید پشتِ خط دورِ بالن بایستد و متن از شکل بیرون نزند."""
    image = Image.new("RGB", (300, 260), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([40, 40, 260, 220], outline=(150, 150, 150), width=3)
    block = {"number": 1, "lines": [1], "bbox": [130, 120, 170, 140], "kind": "speech"}
    canvas, _ = rendering.render_blocks(image, [block], {"1": "سلام دنیا"})
    # فقط متن (تیره) سنجیده می‌شود، نه خط دورِ خاکستری.
    ink = canvas.convert("L").point(lambda value: 255 if value < 100 else 0).getbbox()
    assert ink
    assert 43 <= ink[0] and ink[2] <= 257 and 43 <= ink[1] and ink[3] <= 217
    assert (ink[3] - ink[1]) > 20      # بلندتر از کادر اولیهٔ ۲۰ پیکسلی
