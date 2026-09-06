"""Publishing the UI must never publish live backend controls or private jobs."""
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_preview_is_inert_and_all_assets_are_local():
    class Preview(HTMLParser):
        def __init__(self):
            super().__init__()
            self.scripts = []
            self.policy = ''
            self.actions = 0

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'meta' and attrs.get('http-equiv') == 'Content-Security-Policy':
                self.policy = attrs['content']
            if tag == 'script':
                self.scripts.append(attrs.get('src'))
            if tag in {'input', 'textarea', 'select'}:
                assert 'disabled' in attrs
            if tag == 'button' and 'data-view' not in attrs and 'data-story-stage' not in attrs and attrs.get('id') != 'go-settings':
                assert 'disabled' in attrs
                self.actions += 1
            if tag in {'link', 'script', 'img', 'source'}:
                reference = attrs.get('href', attrs.get('src', ''))
                if tag == 'img' and not reference:
                    assert 'hidden' in attrs.get('class', '').split()
                    return
                assert reference and not reference.startswith(('/', 'http:', 'https:', '//'))
                assert (ROOT / 'docs' / reference).is_file()

    page = Preview()
    page.feed((ROOT / 'docs/index.html').read_text(encoding='utf-8'))
    assert page.scripts == ['preview.js']
    assert "connect-src 'none'" in page.policy
    assert "form-action 'none'" in page.policy
    assert page.actions > 10


def test_preview_uses_local_styles_and_readme_asset_is_safe_svg():
    assert (ROOT / 'docs/style.css').read_text(encoding='utf-8') == (ROOT / 'src/comfyui_py_workflow/web/style.css').read_text(encoding='utf-8')
    import xml.etree.ElementTree as ET
    svg = ROOT / 'docs/assets/offline-studio-preview.svg'
    tree = ET.fromstring(svg.read_text(encoding='utf-8'))
    assert tree.tag.endswith('svg')
    for node in tree.iter():
        assert node.tag.rsplit('}', 1)[-1] not in {'script', 'foreignObject', 'image'}
        assert all(not key.startswith('on') for key in node.attrib)


def test_story_preview_stages_are_unlocked_and_grouped():
    class Stages(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.tabs = {}
            self.containers = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if 'id' in attrs:
                self.containers[attrs['id']] = list(self.stack)
            if 'data-story-stage' in attrs:
                assert 'disabled' not in attrs
                assert attrs['role'] == 'tab'
                self.tabs[attrs['data-story-stage']] = attrs['aria-controls']
            if tag not in {'meta', 'link', 'input', 'img', 'br', 'hr', 'source'}:
                self.stack.append((tag, attrs.get('id')))

        def handle_endtag(self, tag):
            assert self.stack[-1][0] == tag
            self.stack.pop()

    page = Stages()
    page.feed((ROOT / 'docs/index.html').read_text(encoding='utf-8'))
    assert not page.stack
    assert page.tabs == {stage: f'story-stage-{stage}' for stage in ['input', 'plan', 'output']}
    for item, stage in [('story-text', 'input'), ('analysis-panel', 'plan'), ('plan-panel', 'plan'),
                        ('progress-panel', 'output'), ('results-panel', 'output')]:
        assert ('div', f'story-stage-{stage}') in page.containers[item]
    for view in ['view-comic', 'view-batch', 'view-settings']:
        assert ('div', 'view-story') not in page.containers[view]
    assert ('div', 'view-comic') in page.containers['comic-plan-panel']
    assert ('div', 'view-comic') in page.containers['comic-results']
    for name in ['bicycle-frame-0001.png', 'bicycle-frame-0002.png', 'bicycle-frame-0003.png', 'bicycle-final-10s.mp4']:
        assert (ROOT / 'docs/assets' / name).read_bytes() == (ROOT / 'examples/bicycle-sequence/assets' / name).read_bytes()
