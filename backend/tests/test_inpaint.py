"""Deterministic regression tests; fake inference, no downloaded model or GPU."""
import logging
from types import SimpleNamespace

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
from app import cleaning, inpaint, models, textdet


@pytest.fixture(autouse=True)
def isolated_sessions(monkeypatch):
    monkeypatch.setattr(inpaint, "_session_cache", {
        "session": None, "failed": False, "inputs": [], "output": None,
    })
    monkeypatch.setattr(textdet, "_cache", {
        "session": None, "failed": False, "input": None, "shape": [], "outputs": [],
    })


def test_feather_has_fractional_inside_edges_and_preserves_outside():
    mask = np.zeros((40, 50), bool)
    mask[5:35, 5:45] = True
    alpha = inpaint.feather_alpha(np, cv2, mask)[..., 0]
    assert (alpha[~mask] == 0).all()
    assert 0 < alpha[20, 5] < alpha[20, 6] < alpha[20, 9] <= alpha[20, 25] <= 1
    # Even a mask clipped by the page edge has a soft inside edge.
    edge = inpaint.feather_alpha(np, cv2, np.ones((20, 20), bool))[..., 0]
    assert 0 < edge[10, 0] < edge[10, 10]


def test_refine_blends_into_classical_not_original_text(monkeypatch):
    original = np.full((80, 100, 3), 10, np.uint8)  # original ink must not leak back
    classical = np.full_like(original, 100)
    mask = np.zeros(original.shape[:2], bool)
    mask[20:60, 20:80] = True
    monkeypatch.setattr(inpaint, "_session", lambda: object())
    monkeypatch.setattr(inpaint, "_run", lambda np, cv2, image, mask: np.full_like(image, 200))
    out = inpaint.refine(original, classical, [mask], minimum_std=0)
    # Guard requires unmasked model output reasonably close to the original.
    # Test blending itself separately from that guard.
    assert np.array_equal(out, classical)
    monkeypatch.setattr(inpaint, "_looks_reasonable", lambda *args: True)
    out = inpaint.refine(original, classical, [mask])
    assert np.array_equal(out[~mask], classical[~mask])
    assert 100 < out[40, 20, 0] < out[40, 21, 0] < out[40, 40, 0] == 200
    assert np.array_equal(classical, np.full_like(classical, 100))


@pytest.mark.parametrize("shape", [(37, 9), (512, 512), (513, 515), (1033, 1101), (1400, 80)])
def test_tiles_bound_input_and_preserve_geometry_without_resize(monkeypatch, shape):
    rng = np.random.default_rng(42)
    image = rng.integers(0, 256, (*shape, 3), dtype=np.uint8)
    mask = np.ones(shape, np.uint8) * 255
    calls = []

    def identity(np, cv2, patch, local):
        calls.append(patch.shape)
        assert patch.shape == (512, 512, 3)
        assert local.shape == (512, 512)
        assert set(np.unique(local)) <= {0, 255}
        return patch.copy()

    monkeypatch.setattr(inpaint, "_run", identity)
    filled = inpaint._tiled_fill(np, cv2, image, mask)
    assert np.array_equal(filled, image)  # catches shrink/stretch on short padded crops
    assert len(calls) == len(inpaint._tile_starts(shape[0])) * len(inpaint._tile_starts(shape[1]))


def test_tile_overlap_has_smooth_normalized_transition(monkeypatch):
    image = np.zeros((100, 960, 3), np.uint8)
    calls = []

    def distinct(np, cv2, patch, mask):
        value = 50 if not calls else 150
        calls.append(value)
        return np.full_like(patch, value)

    monkeypatch.setattr(inpaint, "_run", distinct)
    filled = inpaint._tiled_fill(np, cv2, image, np.ones(image.shape[:2], np.uint8))
    row = filled[50, :, 0].astype(int)
    assert calls == [50, 150]
    assert (row[:448] == 50).all() and (row[512:] == 150).all()
    assert np.all(np.diff(row) >= 0)
    assert np.diff(row).max() <= 2  # no step at either tile boundary


def test_tiles_with_no_mask_are_not_inferred(monkeypatch):
    image = np.zeros((80, 1400, 3), np.uint8)
    mask = np.zeros(image.shape[:2], np.uint8)
    mask[10:20, 10:20] = 255
    calls = []
    monkeypatch.setattr(inpaint, "_run", lambda np, cv2, patch, local: calls.append(1) or patch)
    assert inpaint._tiled_fill(np, cv2, image, mask) is not None
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [None, MemoryError("simulated provider OOM")])
def test_late_tile_failure_discards_partial_crop_and_logs(monkeypatch, caplog, failure):
    image = np.full((100, 1000, 3), 90, np.uint8)
    classical = image + 10
    mask = np.ones(image.shape[:2], bool)
    calls = []
    monkeypatch.setattr(inpaint, "_session", lambda: object())

    def fail_later(np, cv2, patch, local):
        calls.append(1)
        if len(calls) > 1:
            if failure is not None:
                raise failure
            return None
        return patch + 20

    monkeypatch.setattr(inpaint, "_run", fail_later)
    with caplog.at_level(logging.WARNING):
        out = inpaint.refine(image, classical, [mask])
    assert len(calls) == 2
    assert np.array_equal(out, classical)
    assert np.array_equal(classical, image + 10)
    assert "classical" in caplog.text
    if failure is not None:
        assert "simulated provider OOM" in caplog.text


def test_provider_exception_is_logged_and_run_returns_none(monkeypatch, caplog):
    class BrokenSession:
        def run(self, *args):
            raise RuntimeError("CUDA allocation failed")

    inpaint._session_cache.update(session=BrokenSession(), inputs=["image", "mask"], output="out")
    with caplog.at_level(logging.WARNING):
        assert inpaint._run(np, cv2, np.zeros((64, 64, 3), np.uint8),
                            np.ones((64, 64), np.uint8)) is None
    assert "CUDA allocation failed" in caplog.text
    assert "LaMa inference failed" in caplog.text


def test_nonfinite_model_output_is_rejected(caplog):
    class InvalidSession:
        def run(self, *args):
            return [np.full((1, 3, 64, 64), np.nan, np.float32)]

    inpaint._session_cache.update(session=InvalidSession(), inputs=["image", "mask"], output="out")
    with caplog.at_level(logging.WARNING):
        assert inpaint._run(np, cv2, np.zeros((64, 64, 3), np.uint8),
                            np.ones((64, 64), np.uint8)) is None
    assert "Invalid LaMa output" in caplog.text


def test_context_fallback_feathers_inside_not_just_in_comment(monkeypatch):
    before = np.full((60, 80, 3), 100, np.uint8)
    result = before.copy()
    mask = np.zeros((60, 80), bool)
    mask[10:50, 10:70] = True
    monkeypatch.setattr(cleaning, "_push_pull_fill", lambda cv2, np, window, local: np.full_like(window, 200))
    assert cleaning._context_fill(cv2, np, result, mask, 8, grain=np.zeros(3))
    assert np.array_equal(result[~mask], before[~mask])
    assert 100 < result[30, 10, 0] < result[30, 11, 0] < result[30, 40, 0] == 200


def test_catalog_filename_loads_real_store_path_and_detector_supplies_mask(monkeypatch, tmp_path):
    import json
    import sys

    monkeypatch.setenv("T4_MODELS_DIR", str(tmp_path))
    spec = models.entry(textdet.MODEL_ID)
    filename = spec["files"][0]["name"]
    assert filename == textdet.FILE == models.COMIC_TEXT_DETECTOR_FILE
    root = tmp_path / spec["id"]
    model = root / str(spec["revision"]) / filename
    model.parent.mkdir(parents=True)
    model.write_bytes(b"test ONNX placeholder")
    (root / models.STATE_FILE).write_text(json.dumps({
        "revision": spec["revision"], "files": {filename: {"size": model.stat().st_size}},
    }))
    loaded = []

    class DetectorSession:
        def __init__(self, path, providers):
            loaded.append(path)

        def get_inputs(self):
            return [SimpleNamespace(name="image", shape=[1, 3, 64, 64])]

        def get_outputs(self):
            return [SimpleNamespace(name="text")]

        def run(self, *args):
            glyphs = np.zeros((1, 1, 64, 64), np.float32)
            glyphs[0, 0, 15:20, 20:30] = 1
            return [glyphs]

    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(
        InferenceSession=DetectorSession, get_available_providers=lambda: ["CPUExecutionProvider"],
    ))
    image = np.zeros((64, 64, 3), np.uint8)
    fallback = [np.ones((64, 64), bool)]
    masks = cleaning._smart_masks(np, cv2, image, [(5, 5, 50, 50)], fallback)
    assert loaded == [str(model)]
    assert masks is not fallback
    assert masks[0][17, 25] and not masks[0][40, 40]
    assert masks[0].sum() < fallback[0].sum()


def test_mixed_detector_results_keep_only_missed_box_fallback(monkeypatch):
    image = np.zeros((60, 100, 3), np.uint8)
    glyphs = np.zeros(image.shape[:2], bool)
    glyphs[10:15, 10:20] = True
    monkeypatch.setattr(textdet, "available", lambda: True)
    monkeypatch.setattr(textdet, "masks", lambda image: {"text": glyphs})
    masks = cleaning._smart_masks(np, cv2, image, [(0, 0, 40, 40), (60, 0, 100, 40)],
                                   [np.ones(image.shape[:2], bool)])
    union = np.logical_or.reduce(masks)
    assert union[12, 15] and union[20, 80]
    assert not union[30, 30]  # broad fallback must not overwrite a detected box
    assert not union[50, 80]


def test_missing_detector_can_be_installed_without_restarting_failed_cache(monkeypatch, tmp_path):
    import sys

    loaded = []
    model = tmp_path / models.COMIC_TEXT_DETECTOR_FILE
    path = [None]
    monkeypatch.setattr(models, "model_path", lambda *args: path[0])
    session = SimpleNamespace(
        get_inputs=lambda: [SimpleNamespace(name="image", shape=[1, 3, 64, 64])],
        get_outputs=lambda: [SimpleNamespace(name="text")],
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(
        get_available_providers=lambda: ["CPUExecutionProvider"],
        InferenceSession=lambda p, providers: loaded.append(p) or session,
    ))
    assert textdet._session() is None
    path[0] = model
    assert textdet._session() is session
    assert loaded == [str(model)]


def test_session_initialization_error_is_logged_and_falls_back(monkeypatch, tmp_path, caplog):
    import sys
    from app import diagnostics

    events = []
    monkeypatch.setattr(models, "model_path", lambda *args: tmp_path / "lama_fp32.onnx")
    monkeypatch.setattr(diagnostics, "log_exception", lambda event, **kw: events.append(event))

    def broken(*args, **kwargs):
        raise RuntimeError("provider initialization failed")

    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(
        get_available_providers=lambda: ["CPUExecutionProvider"], InferenceSession=broken,
    ))
    image = np.full((40, 40, 3), 90, np.uint8)
    with caplog.at_level(logging.WARNING):
        out = inpaint.refine(image, image.copy(), [np.ones((40, 40), bool)])
    assert np.array_equal(out, image)
    assert "provider initialization failed" in caplog.text
    assert events == ["inpaint.session.failed"]


def test_clean_image_retains_classical_on_unexpected_refine_error(monkeypatch, tmp_path, caplog):
    from PIL import Image
    from app import diagnostics

    source = tmp_path / "page.png"
    Image.new("RGB", (100, 80), "white").save(source)
    lines = [{"quad": [[10, 10], [70, 10], [70, 60], [10, 60]]}]
    mask = np.zeros((80, 100), bool)
    mask[20:40, 20:50] = True

    def fake_classical(cv2, np, image, result, box, background, mask_total, **kwargs):
        result[mask] = (190, 200, 210)
        mask_total[mask] = 255
        kwargs["collector"].append(mask.copy())
        return True

    monkeypatch.setattr(cleaning, "_fill_ink", fake_classical)
    monkeypatch.setattr(inpaint, "available", lambda: True)
    monkeypatch.setattr(textdet, "available", lambda: False)
    events = []
    monkeypatch.setattr(diagnostics, "log_exception", lambda event, **kw: events.append(event))
    reference, reference_mask = cleaning.clean_image(source, lines, {"1": "translation"}, high_quality=False)

    def oom(*args):
        raise MemoryError("simulated refinement OOM")

    monkeypatch.setattr(inpaint, "refine", oom)
    with caplog.at_level(logging.WARNING):
        actual, actual_mask = cleaning.clean_image(source, lines, {"1": "translation"})
    assert np.array_equal(np.array(actual), np.array(reference))
    assert np.array_equal(np.array(actual_mask), np.array(reference_mask))
    assert "simulated refinement OOM" in caplog.text
    assert events == ["cleaning.inpaint.failed"]
