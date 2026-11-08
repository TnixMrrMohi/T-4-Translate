from pathlib import Path

from app import execution, ocr


def _line(text, x0, y0, x1, y1, confidence):
    return {'text': text, 'confidence': confidence,
            'quad': [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


def test_dedupe_merges_overlapping_lines_with_different_text_keeping_best():
    weak = _line('EXCEUENT STUDIES', 510, 331, 729, 364, 0.90)
    strong = _line('EXCEUENTSTUDIES', 510, 331, 730, 363, 0.95)
    other = _line('OFHIS UFE', 555, 362, 697, 399, 0.9)
    result = ocr._dedupe([weak, other, strong])
    assert [line['text'] for line in result] == ['EXCEUENTSTUDIES', 'OFHIS UFE']


def test_dedupe_drops_partial_reading_inside_a_fuller_line():
    partial = _line('OEHIKUE', 558, 364, 679, 383, 0.9)
    full = _line('OFHIS UFE', 555, 362, 697, 399, 0.9)
    assert ocr._dedupe([partial, full]) == [full]


def test_dedupe_keeps_adjacent_lines():
    first = _line('A', 0, 0, 100, 30, 0.9)
    second = _line('A', 0, 32, 100, 62, 0.9)
    assert len(ocr._dedupe([first, second])) == 2


def test_progress_write_retries_when_replace_is_denied(tmp_path, monkeypatch):
    target = tmp_path / 'progress.json'
    real = Path.replace
    calls = {'n': 0}

    def flaky(self, dest):
        calls['n'] += 1
        if calls['n'] < 3:
            raise PermissionError('in use')
        return real(self, dest)

    monkeypatch.setattr(Path, 'replace', flaky)
    execution._write(target, {'fraction': 0.5})
    assert target.read_text(encoding='utf-8') == '{"fraction": 0.5}'


def test_progress_write_never_raises_when_replace_keeps_failing(tmp_path, monkeypatch):
    def denied(self, dest):
        raise PermissionError('in use')

    monkeypatch.setattr(Path, 'replace', denied)
    execution._write(tmp_path / 'progress.json', {'fraction': 1})
    assert not list(tmp_path.glob('*.tmp'))
