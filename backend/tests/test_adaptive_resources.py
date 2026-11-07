"""Adaptive policy, bounded geometry, actual spawn and native-worker cancellation."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import os
from pathlib import Path
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app import execution, hardware, inpaint, ocr, progress
from app.main import app

REAL_SNAPSHOT = hardware.resource_snapshot


def info(**overrides):
    return dict({'availableRamMb':8192,'totalRamMb':16384,'cores':8,'cpuPercent':10,
                 'gpuUsable':False,'gpuProviders':[]}, **overrides)


@pytest.mark.parametrize('facts,name,tile,threads',[
    (info(gpuUsable=True,gpuProviders=['CUDAExecutionProvider']),'High',512,4),
    (info(gpuUsable=True,gpuProviders=['DmlExecutionProvider']),'High',512,4),
    (info(),'Medium',384,4),
    (info(availableRamMb=2000),'Low',256,1),
    (info(availableRamMb=1000,gpuUsable=True),'Low',256,1),
    (info(cpuPercent=95),'Low',256,1),
    (info(cores=2),'Low',256,1),
    (info(availableRamMb=None),'Low',256,1),
])
def test_profile_policy(facts,name,tile,threads):
    policy=hardware.choose_profile(facts)
    assert (policy['name'],policy['tile'],policy['cpuThreads'])==(name,tile,threads)
    assert 1<=policy['workers']<=2
    assert policy['memoryBudgetMb']<=2560
    if name!='High': assert policy['providers']==['CPUExecutionProvider']


def test_registered_cuda_without_a_device_is_not_high(monkeypatch):
    monkeypatch.setattr(hardware,'onnx_providers',lambda:['CUDAExecutionProvider','CPUExecutionProvider'])
    monkeypatch.setattr(hardware,'gpu',lambda:{'name':'','vendor':'none'})
    assert not REAL_SNAPSHOT()['gpuUsable']


def test_pressure_downgrades_and_never_upgrades_mid_job(monkeypatch):
    hardware.set_profile(hardware.choose_profile(info(gpuUsable=True)))
    monkeypatch.setattr(hardware,'resource_snapshot',lambda:info(availableRamMb=900))
    assert hardware.current_profile(refresh=True)['name']=='Low'
    monkeypatch.setattr(hardware,'resource_snapshot',lambda:info(gpuUsable=True))
    assert hardware.current_profile(refresh=True)['name']=='Low'


@pytest.mark.parametrize('name,size',[('High',512),('Medium',384),('Low',256)])
def test_model_tile_geometry_and_mask_values(monkeypatch,name,size):
    facts=info(gpuUsable=name=='High',availableRamMb=2000 if name=='Low' else 8192)
    monkeypatch.setattr(hardware,'resource_snapshot',lambda:facts)
    hardware.set_profile(hardware.choose_profile(facts))
    calls=[]
    def identity(np,cv2,patch,mask):
        calls.append(patch.shape)
        assert patch.shape==(size,size,3) and mask.shape==(size,size)
        assert set(np.unique(mask))<={0,255}
        return patch.copy()
    monkeypatch.setattr(inpaint,'_run',identity)
    import cv2
    image=np.full((773,563,3),120,np.uint8)
    mask=np.ones(image.shape[:2],np.uint8)*255
    result=inpaint._tiled_fill(np,cv2,image,mask)
    assert calls and np.array_equal(result,image)


def test_low_ram_avoids_loading_lama(monkeypatch):
    monkeypatch.setattr(hardware,'resource_snapshot',lambda:info(availableRamMb=900))
    monkeypatch.setattr(inpaint,'_session',lambda:pytest.fail('should not load model under pressure'))
    image=np.full((40,40,3),200,np.uint8)
    assert inpaint.refine(image,image,[np.ones((40,40),bool)]) is image


def test_fixed_512_model_is_not_upscaled_for_low(monkeypatch):
    from types import SimpleNamespace
    session=SimpleNamespace(get_inputs=lambda:[SimpleNamespace(shape=[1,3,512,512])],
                            run=lambda *args:pytest.fail('must not infer with incompatible geometry'))
    monkeypatch.setattr(inpaint,'_session',lambda:session)
    import cv2
    assert inpaint._run(np,cv2,np.zeros((256,256,3),np.uint8),np.ones((256,256),np.uint8)) is None


def test_eta_and_cancel_state(monkeypatch):
    now=[100.0];monkeypatch.setattr(progress.time,'time',lambda:now[0])
    progress.begin('eta');now[0]=110
    progress.update('eta',.5,'clean_inpaint')
    assert progress.snapshot('eta')['etaSeconds']==10
    assert progress.request_cancel('eta')
    with pytest.raises(progress.OperationCancelled):progress.check_cancelled('eta')
    progress.cancelled('eta')
    state=progress.snapshot('eta')
    assert state['stage']=='cancelled' and state['fraction']==.5 and not state['running']
    assert not progress.request_cancel('eta')
    progress.clear()


def _page():
    image=Image.new('RGB',(650,450),'white');draw=ImageDraw.Draw(image)
    from app import rendering
    font=ImageFont.truetype(str(rendering.font_path()),32)
    draw.rectangle((30,40,550,170),outline='black',width=3)
    draw.text((70,75),'HELLO WORLD',font=font,fill='black')
    data=BytesIO();image.save(data,format='PNG')
    return data.getvalue()


def test_real_spawn_ocr_clean_render_and_no_surviving_model_process(tmp_path,monkeypatch):
    pytest.importorskip('rapidocr_onnxruntime')
    monkeypatch.setenv('T4_DATA_DIR',str(tmp_path))
    monkeypatch.delenv('T4_WORKER_MODE')
    facts=info(availableRamMb=2200)
    monkeypatch.setattr(hardware,'resource_snapshot',lambda:facts)
    hardware.set_profile(hardware.choose_profile(facts))
    peaks=[];real=execution.tree_rss_mb
    def rss():
        value=real();peaks.append(value);return value
    monkeypatch.setattr(execution,'tree_rss_mb',rss)
    with TestClient(app) as client:
        job=client.post('/api/jobs',files={'file':('page.png',_page(),'image/png')}).json()['jobId']
        api=f'/api/jobs/{job}'
        r=client.post(api+'/ocr');assert r.status_code==200,r.text
        assert 'HELLO' in ' '.join(line['text'] for line in r.json()['lines'])
        source=client.get(api+'/translation-source').json()
        r=client.post(api+'/translations',json={'sourceRevision':source['revision'],'text':'[1] سلام دنیا'})
        assert r.status_code==200,r.text
        r=client.post(api+'/clean');assert r.status_code==200,r.text
        r=client.get(api+'/layout');assert r.status_code==200,r.text
        r=client.post(api+'/render');assert r.status_code==200,r.text
        assert client.get(api+'/render').status_code==200
        assert client.get(api+'/render-progress').json()['stage']=='render_done'
        assert client.get(api+'/clean-progress').json()['fraction']==1
    assert peaks and max(peaks)<2304


# Pickleable standalone target used ONLY by tests; replaces execution._worker.
def _slow_worker(kind,payload,directory,profile):
    root=Path(directory)
    (root/'pid').write_text(str(os.getpid()),encoding='utf-8')
    execution._write(root/'progress.json',{'fraction':.3,'stage':'strips','profile':profile})
    time.sleep(30)
    return []


@pytest.mark.parametrize('operation',['ocr','clean','render'])
def test_cancel_endpoint_kills_running_process_and_preserves_old_output(tmp_path,monkeypatch,operation):
    import psutil
    monkeypatch.setenv('T4_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(execution,'_worker',_slow_worker)
    with TestClient(app) as client:
        job=client.post('/api/jobs',files={'file':('page.png',_page(),'image/png')}).json()['jobId']
        workspace=tmp_path/'jobs'/job
        old=workspace/'ocr.json'
        api=f'/api/jobs/{job}'
        if operation!='ocr':
            monkeypatch.setattr(ocr,'recognize',lambda *args:[{'text':'HELLO WORLD','confidence':.99,
                'quad':[[60,65],[350,65],[350,125],[60,125]]}])
            assert client.post(api+'/ocr').status_code==200
            source=client.get(api+'/translation-source').json()
            assert client.post(api+'/translations',json={'sourceRevision':source['revision'],'text':'[1] سلام'}).status_code==200
            assert client.post(api+'/clean').status_code==200
            assert client.post(api+'/render').status_code==200
        else:
            old.write_bytes(b'{"old":true}')
        originals={p.name:p.read_bytes() for p in workspace.iterdir() if p.is_file()}
        monkeypatch.delenv('T4_WORKER_MODE')
        with ThreadPoolExecutor(max_workers=1) as threads:
            future=threads.submit(client.post,api+'/'+operation)
            deadline=time.monotonic()+15
            pid=None
            while time.monotonic()<deadline:
                files=list(workspace.glob('.t4-worker-*/pid'))
                if files:
                    pid=int(files[0].read_text(encoding='utf-8'));break
                time.sleep(.05)
            assert pid is not None
            started=time.monotonic()
            response=client.post(api+'/cancel?operation='+operation)
            assert response.status_code==200 and response.json()['accepted']
            response=future.result(timeout=10)
            assert response.status_code==409,response.text
            assert time.monotonic()-started<10
        assert not psutil.pid_exists(pid)
        assert all((workspace/name).read_bytes()==data for name,data in originals.items())
        endpoint='/progress' if operation=='ocr' else f'/{operation}-progress'
        assert client.get(api+endpoint).json()['stage']=='cancelled'
        assert not list(workspace.glob('.t4-worker-*'))
        assert client.post(api+'/cancel?operation=invalid').status_code==422


def test_rss_watchdog_terminates_pool(tmp_path,monkeypatch):
    monkeypatch.setattr(execution,'_worker',_slow_worker)
    calls=[0]
    def over_budget():
        calls[0]+=1
        return 10 if calls[0]==1 else 3000
    monkeypatch.setattr(execution,'tree_rss_mb',over_budget)
    with pytest.raises(execution.ResourceLimitError):
        asyncio.run(execution.run('ocr',{},tmp_path))
    assert not list(tmp_path.glob('.t4-worker-*'))


def test_low_profile_refreshes_free_ram_telemetry(monkeypatch):
    hardware.set_profile(hardware.choose_profile(info(availableRamMb=2000)))
    monkeypatch.setattr(hardware,'resource_snapshot',lambda:info(availableRamMb=700))
    assert hardware.current_profile(refresh=True)['availableRamMb']==700


def test_provider_runtime_fallback_downgrades_high():
    from types import SimpleNamespace
    hardware.confirm_session(SimpleNamespace(get_providers=lambda:['CPUExecutionProvider']))
    assert hardware.current_profile()['name']=='Medium'


def test_pixel_budget_rejects_before_spawning(tmp_path,monkeypatch):
    hardware.set_profile(hardware.choose_profile(info(availableRamMb=2200)))
    monkeypatch.setattr(hardware,'resource_snapshot',lambda:info(availableRamMb=2200))
    path=tmp_path/'huge.png';Image.new('RGB',(3000,2100),'white').save(path)
    with pytest.raises(execution.ResourceLimitError):
        asyncio.run(execution.run('ocr',{'path':str(path)},tmp_path))
    assert not list(tmp_path.glob('.t4-worker-*'))


def test_commit_boundary_rejects_late_cancel():
    progress.begin('commit')
    progress.start_commit('commit')
    assert not progress.request_cancel('commit')
    progress.finish('commit');progress.clear()


def test_difficult_masks_are_merged_instead_of_one_page_allocation_per_glyph():
    import cv2
    from app import cleaning
    image=np.full((60,80,3),240,np.uint8);collector=[]
    for x in range(10,70,5):
        mask=np.zeros((60,80),bool);mask[20:30,x:x+2]=True
        image[mask]=0
        assert cleaning._context_fill(cv2,np,image,mask,16,grain=np.zeros(3),collector=collector)
    assert len(collector)==1 and collector[0].sum()==12*20


def test_low_real_spawn_on_five_megapixel_webtoon(tmp_path,monkeypatch):
    pytest.importorskip('rapidocr_onnxruntime')
    monkeypatch.setenv('T4_DATA_DIR',str(tmp_path));monkeypatch.delenv('T4_WORKER_MODE')
    facts=info(availableRamMb=2200,cores=4)
    monkeypatch.setattr(hardware,'resource_snapshot',lambda:facts)
    hardware.set_profile(hardware.choose_profile(facts))
    from app import rendering
    image=Image.new('RGB',(1000,5000),'white');draw=ImageDraw.Draw(image)
    font=ImageFont.truetype(str(rendering.font_path()),36)
    for y in (80,1580,3080,4580):
        draw.rectangle((40,y-20,600,y+100),outline='black',width=3)
        draw.text((80,y),'HELLO WORLD',font=font,fill='black')
    data=BytesIO();image.save(data,format='PNG');image.close()
    with TestClient(app) as client:
        job=client.post('/api/jobs',files={'file':('long.png',data.getvalue(),'image/png')}).json()['jobId']
        api=f'/api/jobs/{job}'
        r=client.post(api+'/ocr');assert r.status_code==200,r.text
        source=client.get(api+'/translation-source').json()
        assert len(source['items'])==4
        r=client.post(api+'/translations',json={'sourceRevision':source['revision'],
            'text':'\n'.join(f"[{item['number']}] سلام دنیا" for item in source['items'])})
        assert r.status_code==200,r.text
        r=client.post(api+'/clean');assert r.status_code==200,r.text
        r=client.post(api+'/render');assert r.status_code==200,r.text
        assert client.get(api+'/render').status_code==200
