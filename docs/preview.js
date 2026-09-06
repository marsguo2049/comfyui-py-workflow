// Presentation only. Never import the real app scripts or contact a backend.
const $ = selector => document.querySelector(selector);
const views = {
  story: ['STORY TO VIDEO', '把故事，变成画面。', '从一个想法开始，在本机完成分镜与视频。'],
  batch: ['BATCH TOOLS', '一次设定，批量完成。', '重复的图片处理，交给本地工作流。'],
  settings: ['LOCAL SERVICES', '连接你的创作引擎。', '统一管理本机服务，供各个工作区使用。'],
};
function switchView(name) {
  if (!views[name]) name = 'batch';
  for (const key of Object.keys(views)) $(`#view-${key}`).classList.toggle('hidden', key !== name);
  document.querySelectorAll('[data-view]').forEach(button => {
    const selected = button.dataset.view === name;
    button.classList.toggle('active', selected);
    if (selected) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  ['eyebrow', 'title', 'subtitle'].forEach((key, index) => $(`#view-${key}`).textContent = views[name][index]);
  history.replaceState(null, '', `#${name}`);
}
document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => switchView(button.dataset.view));
$('#go-settings').onclick = () => switchView('settings');
window.addEventListener('hashchange', () => switchView(location.hash.slice(1)));
for (const eventName of ['dragover', 'drop']) window.addEventListener(eventName, event => event.preventDefault());

$('#story-text').value = '一名信使在暴雨前把一封信送到港口，一位钟表匠已在那里等候多年。\n\n（公开虚构示例）';
$('#batch-prompt').value = '把背景换成浅灰色摄影棚，保留主体和自然阴影。';
$('#batch-selection-count').textContent = '已添加 3 张图片 · 示例';
for (const name of ['product-front.png', 'product-side.png', 'product-detail.png']) {
  const row = document.createElement('div'); row.className = 'selection-row';
  const filename = document.createElement('span'); filename.textContent = name;
  const badge = document.createElement('small'); badge.textContent = '示例文件';
  row.append(filename, badge); $('#batch-selection').append(row);
}
$('#batch-completed').textContent = '0/3';
$('#batch-message').textContent = '示例任务待开始。实际处理请在本机运行 Offline Studio。';
$('#batch-history').replaceChildren();
const historyRow = document.createElement('div'); historyRow.className = 'preview-example';
historyRow.textContent = '图片编辑 · 示例任务\n统一商品图背景 · 3 张图片';
$('#batch-history').append(historyRow);
for (const id of ['lm-status', 'comfy-status', 'ocr-status']) $(`#${id} p`).textContent = '预览模式，不检测本机服务。';
$('#lm-model').options[0].textContent = '本地模型（示例）';
document.querySelectorAll('button:disabled, input:disabled, textarea:disabled, select:disabled').forEach(node => node.title = '仅展示。实际处理请在本机运行 Offline Studio。');
switchView(location.hash.slice(1));
