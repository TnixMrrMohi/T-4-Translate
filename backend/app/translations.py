"""Numbered manual translations. Missing items are never treated as translations."""
import re
from dataclasses import dataclass

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩０１２３４５６７８９", "012345678901234567890123456789")
_MARKER = re.compile(r"^\s*\[([0-9]{1,4})\]\s*(.*)$")
# مدل ممکن است «(لحن: فریاد)» را از منبع تکرار کند؛ آن را از ترجمه حذف می‌کنیم.
_TONE_PREFIX = re.compile(r"^\s*[\(\[]\s*لحن[^\)\]]*[\)\]]\s*")


@dataclass
class ParseResult:
    translations: dict[int, str]
    missing: list[int]
    duplicates: list[int]
    unknown: list[int]


def parse_translation(text: str, expected: set[int]) -> ParseResult:
    translations: dict[int, str] = {}
    duplicates: set[int] = set()
    unknown: set[int] = set()
    current: int | None = None
    for line in text.splitlines():
        match = _MARKER.match(line.translate(_DIGITS))
        if match:
            number = int(match.group(1))
            current = number if number in expected else None
            if current is None:
                unknown.add(number)
                continue
            if current in translations:
                duplicates.add(current)
            # Preserve original Unicode text, including Persian digits in the translation.
            end_of_marker = line.index(']') + 1
            translations[current] = _TONE_PREFIX.sub("", line[end_of_marker:].strip())
        elif current is not None and line.strip():
            translations[current] = (translations[current] + '\n' + line.strip()).strip()
    translations = {number: value for number, value in translations.items() if value.strip()}
    return ParseResult(translations, sorted(expected - translations.keys()), sorted(duplicates), sorted(unknown))
