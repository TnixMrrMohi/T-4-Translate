"""Raster-to-API regression tests: actual cleaning, grouping, layout and RTL drawing.

OCR is fixed for deterministic variants; a separate test uses the real bundled
RapidOCR models when installed. No external LaMa/CTD weights are downloaded.
"""
from io import BytesIO
import json
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont
from fastapi.testclient import TestClient

pytest.importorskip('cv2')
pytest.importorskip('arabic_reshaper')
from app import cleaning, inpaint, ocr, rendering, textdet
from app.main import app


def page(with_promo=False):
    image = Image.new('RGB', (900, 700), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(rendering.font_path()), 36)
    lines = []
    entries = [(60, 70, 'HELLO WORLD'), (500, 490, 'GOOD MORNING')]
    if with_promo:
        entries.insert(0, (60, 300, 'www.moonb.ir'))
    for x, y, text in entries:
        draw.rectangle((x - 25, y - 25, x + 350, y + 125), outline='black', width=3)
        draw.text((x, y), text, font=font, fill='black')
        left, top, right, bottom = draw.textbbox((x, y), text, font=font)
        lines.append({'text': text, 'confidence': .99,
                      'quad': [[left, top], [right, top], [right, bottom], [left, bottom]]})
    return image, lines


def run_pipeline(client, image, promo='replace'):
    payload = BytesIO(); image.save(payload, format='PNG')
    response = client.post('/api/jobs', files={'file': ('page.png', payload.getvalue(), 'image/png')})
    assert response.status_code == 201, response.text
    job = response.json()['jobId']; api = f'/api/jobs/{job}'
    response = client.post(api + '/ocr'); assert response.status_code == 200, response.text
    source = client.get(api + f'/translation-source?promo={promo}').json()
    response = client.post(api + '/translations', json={
        'sourceRevision': source['revision'], 'promo': promo,
        'text': '\n'.join(f"[{item['number']}] سلام دنیا" for item in source['items']),
    })
    assert response.status_code == 200, response.text
    response = client.post(api + '/clean'); assert response.status_code == 200, response.text
    cleaned = Image.open(BytesIO(client.get(api + '/clean').content)).convert('RGB')
    response = client.get(api + '/layout'); assert response.status_code == 200, response.text
    layout = response.json()
    # Render/layout must use EXACTLY the IDs, line membership and geometry that
    # were numbered for translation (including removal/renumbering of promos).
    assert [(b['number'], b['lines'], b['bbox']) for b in layout['blocks']] == [
        (b['number'], b['lines'], b['bbox']) for b in source['items']]
    areas = client.get(api + '/clean-areas').json()['areas']
    assert [b['lines'] for b in areas] == [b['lines'] for b in source['items']]
    response = client.post(api + '/render'); assert response.status_code == 200, response.text
    rendered = Image.open(BytesIO(client.get(api + '/render').content)).convert('RGB')
    return job, cleaned, rendered, layout


@pytest.mark.parametrize('promo', ['keep', 'replace', 'remove'])
def test_pipeline_keeps_numbering_geometry_and_persian_ink(tmp_path, monkeypatch, promo):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    image, lines = page(with_promo=True)
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: lines)
    with TestClient(app) as client:
        job, cleaned, rendered, layout = run_pipeline(client, image, promo)
        pixels = np.array(cleaned)
        for line in lines:
            q = np.array(line['quad']); x0, y0 = q.min(axis=0); x1, y1 = q.max(axis=0)
            assert (pixels[y0:y1, x0:x1] > 210).all(), 'source letters remain after cleaning'
        ink = np.any(np.array(cleaned) != np.array(rendered), axis=2)
        for entry in layout['blocks']:
            x, y = entry['center']
            # There must be Persian ink locally, not all at the page centre.
            assert ink[max(0,int(y)-70):int(y)+70, max(0,int(x)-160):int(x)+160].any()
        assert not ink[250:290, 410:490].any()
        api = f'/api/jobs/{job}'
        first = layout['blocks'][0]['number']
        override = {str(first): {'x': 160, 'y': 150, 'size': 24}}
        assert client.put(api+'/layout', json={'blocks': override}).status_code == 200
        saved = json.loads((tmp_path/'jobs'/job/'layout.json').read_text(encoding='utf-8'))
        assert saved['blocks'] == override
        assert client.get(api+'/layout').json()['blocks'][0]['center'] == [160, 150]
        assert client.get(api+'/render').status_code == 409
        assert client.post(api+'/render').status_code == 200


def test_real_rapidocr_pipeline_on_two_distant_text_boxes(tmp_path, monkeypatch):
    pytest.importorskip('rapidocr_onnxruntime')
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    image, _ = page()
    with TestClient(app) as client:
        job, cleaned, rendered, layout = run_pipeline(client, image)
        assert len(layout['blocks']) == 2
        assert layout['blocks'][0]['center'][0] < 350
        assert layout['blocks'][1]['center'][0] > 500
        assert layout['blocks'][1]['center'][1] > 450
        lines = client.get(f'/api/jobs/{job}/ocr').json()['lines']
        assert 'HELLO WORLD' in ' '.join(line['text'] for line in lines)
        pixels = np.array(cleaned)
        for line in lines:
            q = np.array(line['quad']); x0,y0=q.min(axis=0).astype(int);x1,y1=q.max(axis=0).astype(int)
            assert (pixels[y0:y1,x0:x1] > 210).all()
        assert np.any(np.array(rendered) != pixels)

        # Opt-in evidence export; never writes user data or generated images to Git.
        if output_dir := os.environ.get('T4_VERIFICATION_DIR'):
            import cv2
            root = Path(output_dir); root.mkdir(parents=True, exist_ok=True)
            image.save(root/'input.png')
            cleaned.save(root/'clean.png')
            rendered.save(root/'render.png')
            (root/'mask.png').write_bytes((tmp_path/'jobs'/job/'mask.png').read_bytes())
            (root/'layout-response.json').write_text(json.dumps(layout,ensure_ascii=False,indent=2),encoding='utf-8')
            (root/'ocr.json').write_text(json.dumps(lines,ensure_ascii=False,indent=2),encoding='utf-8')
            (root/'summary.json').write_text(json.dumps({
                'ocr':'real RapidOCR 1.4.4, bundled ONNX weights',
                'opencv':cv2.__version__, 'raqm':rendering.has_raqm(),
                'blocks':len(layout['blocks']), 'remainingDarkSourcePixels':0,
                'lama':'not installed; actual neural inference NOT tested',
                'comicTextDetector':'not installed; actual neural inference NOT tested',
                'layoutCenters':[b['center'] for b in layout['blocks']],
            },ensure_ascii=False,indent=2),encoding='utf-8')


def test_classical_fallback_removes_thin_ink_instead_of_feathering_it_back():
    import cv2
    pixels = np.full((60, 80, 3), 240, np.uint8)
    mask = np.zeros((60, 80), bool); mask[20:40, 25:27] = True
    pixels[mask] = 0
    cleaned = pixels.copy()
    assert cleaning._context_fill(cv2, np, cleaned, mask, 16, grain=np.zeros(3))
    assert cleaned[mask].min() > 220
    assert np.array_equal(cleaned[~mask], pixels[~mask])


@pytest.mark.parametrize('mask', [np.ones((8,8)), np.ones((40,50,3)), np.full((40,50),np.nan)])
def test_invalid_detector_mask_returns_classical_support(monkeypatch, mask):
    import cv2
    image = np.zeros((40,50,3),np.uint8)
    fallback = [np.ones((40,50),bool)]
    monkeypatch.setattr(textdet, 'available', lambda: True)
    monkeypatch.setattr(textdet, 'masks', lambda image: {'text':mask})
    assert cleaning._smart_masks(np, cv2, image, [(5,5,30,30)],fallback) is fallback


def test_basic_engine_rejects_font_missing_presentation_forms(monkeypatch):
    path = rendering.font_path().parent/'persian-pack'/'Lalezar-Regular.ttf'
    assert path.is_file()
    rendering.shape_text.cache_clear()
    monkeypatch.setattr(rendering, 'has_raqm', lambda: False)
    try:
        assert rendering.font_supports(str(path), 'سلام دنیا')
        assert not rendering.font_supports(str(path), rendering.shape_text('سلام دنیا'))
        image = Image.new('RGB',(400,200),'white')
        block = {'number':1,'lines':[1],'kind':'outside','bbox':[40,50,350,130]}
        plan = rendering.plan_blocks(image,[block],{'1':'سلام دنیا'}, {'outside':str(path)})
        assert plan[0]['path'] is None  # fallback to Vazirmatn instead of tofu
        rendered, drawn = rendering.render_blocks(image,[block],{'1':'سلام دنیا'}, {'outside':str(path)})
        assert drawn == 1 and np.any(np.array(rendered) < 200)
    finally:
        rendering.shape_text.cache_clear()


def _ready_job(client, monkeypatch):
    image, lines = page()
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: lines)
    payload = BytesIO(); image.save(payload, format='PNG')
    job = client.post('/api/jobs', files={'file': ('page.png', payload.getvalue(), 'image/png')}).json()['jobId']
    api = f'/api/jobs/{job}'
    assert client.post(api+'/ocr').status_code == 200
    source = client.get(api+'/translation-source').json()
    assert client.post(api+'/translations',json={
        'sourceRevision':source['revision'],'text':'[1] سلام\n[2] دنیا',
    }).status_code == 200
    return api


def test_clean_progress_is_pollable_while_worker_runs_and_finishes_after_save(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from app import progress
    monkeypatch.setenv('T4_DATA_DIR',str(tmp_path))
    started, release = threading.Event(), threading.Event()
    original = cleaning.clean_image

    def blocked(*args, on_progress=None, **kwargs):
        on_progress(.7, 'clean_inpaint')
        started.set()
        assert release.wait(5), 'test did not release worker'
        return original(*args, on_progress=on_progress, **kwargs)

    with TestClient(app) as client:
        api = _ready_job(client,monkeypatch)
        assert client.get(api+'/clean-progress').json()['fraction'] == 0
        monkeypatch.setattr(cleaning,'clean_image',blocked)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(client.post,api+'/clean')
            try:
                assert started.wait(5)
                state=client.get(api+'/clean-progress').json()
                assert state['fraction']==.7 and state['running']
                assert state['stage']=='clean_inpaint'
                # The independent OCR run remains completed, not overwritten.
                assert client.get(api+'/progress').json()['finished']
            finally:
                release.set()
            assert future.result(timeout=5).status_code==200
        state=client.get(api+'/clean-progress').json()
        assert state['fraction']==1 and state['stage']=='clean_done'
        assert state['finished'] and not state['running']
        assert client.get(api+'/clean').status_code==200
    progress.clear()


def test_clean_progress_records_failure_without_false_completion(tmp_path, monkeypatch):
    monkeypatch.setenv('T4_DATA_DIR',str(tmp_path))
    with TestClient(app) as client:
        api=_ready_job(client,monkeypatch)
        def broken(*args, on_progress=None, **kwargs):
            on_progress(.4,'clean_classical')
            raise cleaning.CleaningError('synthetic failure')
        monkeypatch.setattr(cleaning,'clean_image',broken)
        assert client.post(api+'/clean').status_code==400
        state=client.get(api+'/clean-progress').json()
        assert state['error'] and state['finished'] and not state['running']
        assert state['fraction']==.4 and state['stage']=='clean_error'
        assert client.get(api+'/clean').status_code==404


def test_tile_progress_reports_actual_completed_work(monkeypatch):
    monkeypatch.setattr(inpaint,'_run',lambda np,cv2,image,mask: image.copy())
    import cv2
    image=np.full((530,970,3),200,np.uint8)
    mask=np.ones(image.shape[:2],np.uint8)*255
    seen=[]
    output=inpaint._tiled_fill(np,cv2,image,mask,on_progress=seen.append)
    assert np.array_equal(output,image)
    assert len(seen)==6
    assert seen==sorted(seen) and 0<seen[0]<1 and seen[-1]==1


def test_legacy_removed_promo_recovers_policy_from_revision(tmp_path, monkeypatch):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    image, lines = page(with_promo=True)
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: lines)
    with TestClient(app) as client:
        job, _, _, layout = run_pipeline(client, image, 'remove')
        path = tmp_path/'jobs'/job/'translations.json'
        saved = json.loads(path.read_text(encoding='utf-8')); saved.pop('promo')
        path.write_text(json.dumps(saved), encoding='utf-8')
        response = client.get(f'/api/jobs/{job}/layout')
        assert response.status_code == 200, response.text
        assert response.json()['blocks'] == layout['blocks']
        assert client.post(f'/api/jobs/{job}/render').status_code == 200
