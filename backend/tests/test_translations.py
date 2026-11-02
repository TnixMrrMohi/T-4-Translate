from app.translations import parse_translation


def test_multilingual_digits_and_continuation_preserve_text():
    result = parse_translation('مقدمه\n[۱] سلام ۱۲\nادامه\n[٢] دوم\n[３] سوم', {1, 2, 3})
    assert result.translations == {1: 'سلام ۱۲\nادامه', 2: 'دوم', 3: 'سوم'}
    assert result.missing == []


def test_missing_duplicate_unknown_and_empty():
    result = parse_translation('[1] اول\n[1] جایگزین\n[9] ناشناخته\nنباید اضافه شود\n[2]', {1, 2, 3})
    assert result.translations == {1: 'جایگزین'}
    assert result.duplicates == [1]
    assert result.unknown == [9]
    assert result.missing == [2, 3]


def test_tone_prefix_echoed_by_the_model_is_removed():
    """اگر مدل «(لحن: …)» را از منبع تکرار کند، نباید روی تصویر چاپ شود."""
    result = parse_translation("[1] (لحن: فریاد و عصبانیت) برو عقب!\n[2] (لحن: زمزمه) آرام باش", {1, 2})
    assert result.translations == {1: "برو عقب!", 2: "آرام باش"}


def test_parentheses_that_are_not_a_tone_stay_in_the_translation():
    result = parse_translation("[1] (آه) دیگر بس است", {1})
    assert result.translations == {1: "(آه) دیگر بس است"}
