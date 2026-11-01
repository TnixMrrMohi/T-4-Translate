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
