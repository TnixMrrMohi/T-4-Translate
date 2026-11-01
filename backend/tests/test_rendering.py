"""آزمون‌های نمایش آزمایشی ترجمهٔ فارسی روی تصویر."""
import pytest
from PIL import Image

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
