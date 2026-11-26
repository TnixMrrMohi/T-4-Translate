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
    blanks: list[int] = None

    def __post_init__(self):
        if self.blanks is None:
            self.blanks = []


def parse_translation(text: str, expected: set[int]) -> ParseResult:
    raw_translations: dict[int, str] = {}
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
            if current in raw_translations:
                duplicates.add(current)
            # Preserve original Unicode text, including Persian digits in the translation.
            end_of_marker = line.index(']') + 1
            raw_translations[current] = _TONE_PREFIX.sub("", line[end_of_marker:].strip())
        elif current is not None and line.strip():
            raw_translations[current] = (raw_translations[current] + '\n' + line.strip()).strip()

    translations: dict[int, str] = {}
    blanks: list[int] = []
    for number, val in raw_translations.items():
        trimmed = val.strip()
        if trimmed:
            translations[number] = trimmed
        else:
            blanks.append(number)

    all_found = set(raw_translations.keys())
    missing = sorted(expected - all_found)
    return ParseResult(translations, missing, sorted(duplicates), sorted(unknown), sorted(blanks))
