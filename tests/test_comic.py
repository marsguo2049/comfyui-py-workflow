from __future__ import annotations

import json
import threading
import zipfile
from copy import deepcopy
from http.client import HTTPConnection
from pathlib import Path

import pytest

from comfyui_py_workflow import comic_studio
from comfyui_py_workflow.client import ComfyUIClient
from comfyui_py_workflow.comic import create_comic_plan, validate_comic_plan
from comfyui_py_workflow.comic_studio import ComicStudio
from comfyui_py_workflow.local_ui import SingleInstanceHTTPServer, StudioRequestHandler

ROOT = Path(__file__).resolve().parents[1]
PNG = b'\x89PNG\r\n\x1a\n' + b'fake-image'


def sample_plan(count=3):
    return dict(schema_version=1, title='A short comic', style='ink drawing', character_bible='A courier in a blue coat',
                negative_prompt='text, duplicates', aspect_ratio='3:4', panels=[dict(index=i, reference='anchor' if i in {1, 3} else 'previous',
                description=f'Scene {i}', prompt=f'The courier at scene {i}', caption=f'Caption {i}', dialogue='Courier: Hello') for i in range(1, count + 1)])


class FakeClient:
    input_reference = staticmethod(ComfyUIClient.input_reference)
    def __init__(self): self.workflows, self.sources = [], []
    def check_health(self): return {}
    def upload_image(self, path, **kwargs):
        self.sources.append(Path(path).name)
        return dict(name=kwargs['filename'], subfolder=kwargs['subfolder'])
    def run(self, workflow, timeout_seconds):
        self.workflows.append(workflow)
        node = '469' if '469' in workflow else '9'
        return 'fake-prompt', {'outputs': {node: {'images': [dict(filename='fake.png', subfolder='', type='output')]}}}
    def download_asset(self, asset, destination):
        Path(destination).write_bytes(PNG)
        return destination


def finish(studio, job_id):
    studio._threads[job_id].join(timeout=5)
    assert not studio._threads[job_id].is_alive()
    return studio.get(job_id)


def prepared(studio):
    job = studio.create('A courier delivers a letter.')
    return studio.save_plan(job['id'], sample_plan(), revision=0)


@pytest.mark.parametrize('change', [
    lambda p: p.update(panels=[]), lambda p: p['panels'][1].update(index=8),
    lambda p: p['panels'][0].update(reference='previous'), lambda p: p.update(aspect_ratio='bad'),
    lambda p: p['panels'][1].update(prompt=''), lambda p: p['panels'][1].update(dialogue='x' * 301),
    lambda p: p.update(character_bible=[]),
])
def test_invalid_comic_plans(change):
    plan = sample_plan(); change(plan)
    with pytest.raises(ValueError): validate_comic_plan(plan)


def test_planner_retries_semantic_errors_and_uses_comic_instructions():
    calls = []
    class LM:
        def structured_chat(self, **kwargs):
            calls.append(kwargs)
            result = sample_plan()
            if len(calls) == 1: result['panels'][1]['index'] = 9
            return result
    result = create_comic_plan(LM(), model='fake', source='A short story', count=3, aspect='3:4', style='ink', has_reference=True)
    assert len(calls) == 2 and len(result['panels']) == 3
    assert calls[0]['schema_name'] == 'comic_plan'
    assert 'not a video director' in calls[0]['messages'][0]['content']
    assert calls[0]['schema']['properties']['panels']['minItems'] == 3


def test_async_planning_and_model_unload(tmp_path, monkeypatch):
    unloaded = []
    class LM:
        def __init__(self, *args, **kwargs): pass
        def resolve_model(self, model): return 'fake-local-model'
        def structured_chat(self, **kwargs): return sample_plan()
        def unload_model(self, model): unloaded.append(model)
    monkeypatch.setattr(comic_studio, 'LMStudioClient', LM)
    studio = ComicStudio(tmp_path)
    job = studio.create('A courier delivers a letter.')
    studio.plan(job['id'], dict(panel_count=3, aspect_ratio='3:4'))
    done = finish(studio, job['id'])
    assert done['status'] == 'ready' and done['revision'] == 1
    assert unloaded == ['fake-local-model']


def test_image_chain_anchor_resume_and_text_only_export(tmp_path, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(comic_studio, 'ComfyUIClient', lambda url: client)
    studio = ComicStudio(tmp_path)
    job = prepared(studio)
    studio.start(job['id'], dict(revision=job['revision']))
    done = finish(studio, job['id'])
    assert done['status'] == 'succeeded', done['message']
    assert done['completed'] == 3
    assert len(client.workflows) == 3 and '9' in client.workflows[0]
    assert client.sources == ['panel-0001.png', 'panel-0001.png']
    assert all('24' not in workflow for workflow in client.workflows)  # No H3/video requests.
    assert client.workflows[1]['cpw_comic_canvas']['class_type'] == 'ImageScale'
    assert client.workflows[1]['cpw_comic_canvas']['inputs']['height'] > client.workflows[1]['cpw_comic_canvas']['inputs']['width']
    restored = ComicStudio(tmp_path)
    changed = deepcopy(done['plan']); changed['panels'][0]['dialogue'] = '<script>bad()</script>'
    edited = restored.save_plan(job['id'], changed, done['revision'])
    assert len(edited['results']) == 3 and len(client.workflows) == 3
    html = restored.media_path(job['id'], 'comic.html').read_text(encoding='utf-8')
    assert '&lt;script&gt;' in html and '<script>' not in html
    with zipfile.ZipFile(restored.media_path(job['id'], 'comic.zip')) as bundle:
        assert set(bundle.namelist()) == {'comic.html', 'comic-plan.json', 'panel-0001.png', 'panel-0002.png', 'panel-0003.png'}
    changed['panels'][1]['prompt'] = 'The courier smiles in scene 2'
    updated = restored.save_plan(job['id'], changed, edited['revision'])
    assert len(updated['results']) == 1 and updated['exports'] == []
    with pytest.raises(FileNotFoundError): restored.media_path(job['id'], 'comic.html')
    restored.start(job['id'], dict(revision=updated['revision']))
    final = finish(restored, job['id'])
    assert final['status'] == 'succeeded' and len(client.workflows) == 5


def test_reference_image_uses_qwen_from_first_panel(tmp_path, monkeypatch):
    client = FakeClient(); monkeypatch.setattr(comic_studio, 'ComfyUIClient', lambda url: client)
    studio = ComicStudio(tmp_path); job = studio.create('A story')
    studio.attach_reference(job['id'], PNG)
    job = studio.save_plan(job['id'], sample_plan(), 0)
    studio.start(job['id'], dict(revision=job['revision']))
    done = finish(studio, job['id'])
    assert done['status'] == 'succeeded'
    assert all('469' in workflow for workflow in client.workflows)
    assert client.sources == ['reference.png', 'panel-0001.png', 'reference.png']


def test_failure_keeps_completed_panels_and_retry_rebuilds_suffix(tmp_path, monkeypatch):
    client = FakeClient(); monkeypatch.setattr(comic_studio, 'ComfyUIClient', lambda url: client)
    original = client.run
    def fail_second(workflow, timeout_seconds):
        if len(client.workflows) == 1: raise RuntimeError('fake GPU failure')
        return original(workflow, timeout_seconds)
    monkeypatch.setattr(client, 'run', fail_second)
    studio = ComicStudio(tmp_path); job = prepared(studio)
    studio.start(job['id'], dict(revision=job['revision']))
    failed = finish(studio, job['id'])
    assert failed['status'] == 'failed' and len(failed['results']) == 1
    monkeypatch.setattr(client, 'run', original)
    studio.start(job['id'], dict(revision=job['revision']))
    assert finish(studio, job['id'])['status'] == 'succeeded'
    assert len(client.workflows) == 3
    studio.start(job['id'], dict(revision=job['revision'], retry_from=2))
    assert finish(studio, job['id'])['status'] == 'succeeded'
    assert len(client.workflows) == 5


def test_cancel_is_between_panels_and_concurrent_start_is_rejected(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    client = FakeClient(); monkeypatch.setattr(comic_studio, 'ComfyUIClient', lambda url: client)
    original = client.run
    def wait_once(workflow, timeout_seconds):
        entered.set(); assert release.wait(4)
        return original(workflow, timeout_seconds)
    monkeypatch.setattr(client, 'run', wait_once)
    studio = ComicStudio(tmp_path); job = prepared(studio); other = prepared(studio)
    studio.start(job['id'], dict(revision=job['revision']))
    try:
        assert entered.wait(3)
        with pytest.raises(ValueError): studio.start(other['id'], dict(revision=other['revision']))
        with pytest.raises(ValueError): studio.save_plan(job['id'], sample_plan(), job['revision'])
        studio.cancel(job['id'])
    finally:
        release.set()
    done = finish(studio, job['id'])
    assert done['status'] == 'cancelled' and done['completed'] == 1


def test_validation_and_private_paths(tmp_path):
    studio = ComicStudio(tmp_path); job = prepared(studio)
    with pytest.raises(ValueError): studio.start(job['id'], dict(revision=job['revision'], comfyui_url='https://example.com'))
    with pytest.raises(ValueError): studio.plan(job['id'], dict(lm_studio_url='https://example.com'))
    with pytest.raises(ValueError): studio.start(job['id'], dict(revision=job['revision'], timeout_seconds=float('nan')))
    with pytest.raises(ValueError): studio.start(job['id'], dict(revision=0))
    with pytest.raises(ValueError): studio.save_plan(job['id'], sample_plan(), 0)
    with pytest.raises(ValueError): studio.attach_reference(job['id'], b'not-an-image')
    with pytest.raises(ValueError): studio.create(filename='../../bad.exe', data=b'content')
    for path in ['job.json', 'source.txt', '../other/job.json']:
        with pytest.raises(FileNotFoundError): studio.media_path(job['id'], path)
    job['status'] = 'running'; studio._save(job)
    assert ComicStudio(tmp_path).get(job['id'])['status'] == 'interrupted'


def test_comic_http_routes_and_exports(tmp_path, monkeypatch):
    client = FakeClient(); monkeypatch.setattr(comic_studio, 'ComfyUIClient', lambda url: client)
    class Handler(StudioRequestHandler):
        comic = ComicStudio(tmp_path)
        def log_message(self, *args): pass
    server = SingleInstanceHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    connection = HTTPConnection(*server.server_address, timeout=5)
    def request(method, path, body=None, headers=None):
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    try:
        status, body = request('POST', '/api/comic/create', json.dumps({'text': 'A letter arrives'}))
        assert status == 201
        job = json.loads(body)
        assert request('POST', f'/api/comic/reference?id={job["id"]}', PNG)[0] == 201
        status, body = request('POST', '/api/comic/save-plan', json.dumps({'id': job['id'], 'revision': 0, 'plan': sample_plan()}))
        assert status == 200; job = json.loads(body)
        assert request('POST', '/api/comic/start', json.dumps({'id': job['id'], 'revision': job['revision']}))[0] == 202
        assert finish(Handler.comic, job['id'])['status'] == 'succeeded'
        assert request('GET', f'/comic-media/{job["id"]}/comic.zip')[0] == 200
        assert request('HEAD', f'/comic-media/{job["id"]}/panel-0001.png') == (200, b'')
        assert request('GET', f'/comic-media/{job["id"]}/panel-0001.png', headers={'Range': 'bytes=0-7'}) == (206, PNG[:8])
        assert request('GET', f'/comic-media/{job["id"]}/job.json')[0] == 404
        assert request('POST', '/api/comic/create', b'{"text":"no"}', {'Origin': 'https://example.com'})[0] == 400
        assert len(json.loads(request('GET', '/api/comic/jobs')[1])['jobs']) == 1
    finally:
        connection.close(); server.shutdown(); server.server_close(); worker.join(timeout=3)
