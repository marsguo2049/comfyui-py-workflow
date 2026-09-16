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
            if tag in {'input', 'textarea', 'select'} and attrs.get('id') != 'batch-tool':
                assert 'disabled' in attrs
            if tag == 'select' and attrs.get('id') == 'batch-tool':
                assert 'disabled' not in attrs
            if tag == 'button' and 'data-view' not in attrs and attrs.get('id') != 'go-settings':
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
    assert page.actions > 5


def test_preview_uses_local_styles_and_readme_asset_is_safe_svg():
    assert (ROOT / 'docs/style.css').read_text(encoding='utf-8') == (ROOT / 'src/comfyui_py_workflow/web/style.css').read_text(encoding='utf-8')
    import xml.etree.ElementTree as ET
    svg = ROOT / 'docs/assets/comfyui-workbench-preview.svg'
    tree = ET.fromstring(svg.read_text(encoding='utf-8'))
    assert tree.tag.endswith('svg')
    for node in tree.iter():
        assert node.tag.rsplit('}', 1)[-1] not in {'script', 'foreignObject', 'image'}
        assert all(not key.startswith('on') for key in node.attrib)


def test_preview_contains_only_comfyui_batch_workbench_and_synthetic_pairs():
    class Workbench(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids = set()
            self.views = set()
            self.options = set()

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if 'id' in attrs:
                self.ids.add(attrs['id'])
            if 'data-view' in attrs:
                assert 'disabled' not in attrs
                self.views.add(attrs['data-view'])
            if tag == 'option':
                self.options.add(attrs.get('value'))

    html = (ROOT / 'docs/index.html').read_text(encoding='utf-8')
    page = Workbench()
    page.feed(html)
    assert page.views == {'batch', 'settings'}
    assert 'first-last-video' in page.options
    assert {'view-batch', 'view-settings', 'batch-pair-preview'} <= page.ids
    assert 'view-story' not in html
    assert 'view-comic' not in html
    assert 'LM Studio' not in html
    assert 'story-text' not in html
    assert 'translation' not in html.lower()
    assert 'sample-start-01.png' in html
    assert 'sample-end-01.png' in html
