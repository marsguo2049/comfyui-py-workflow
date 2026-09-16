// Presentation only. Never import application scripts or contact a backend.
const $ = selector => document.querySelector(selector);
const views = {
  batch: ['BATCH TOOLS', '一次设定，批量完成。', '批量修改图片，或用首尾帧生成视频。'],
  settings: ['COMFYUI SETTINGS', '连接你的生成引擎。', '预览本机 ComfyUI 设置界面。'],
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

function switchTool() {
  const video = $('#batch-tool').value === 'first-last-video';
  $('#batch-video-inputs').classList.toggle('hidden', !video);
  $('#batch-drop').classList.toggle('hidden', video);
  $('#batch-selection-summary').classList.toggle('hidden', video);
  $('#batch-negative-field').classList.toggle('hidden', video);
  $('#batch-model').textContent = video ? 'MiniMax H3' : 'Qwen Image Edit 2509';
  $('#batch-tool-description').textContent = video ? '选择首尾帧，按配对批量生成视频。' : '用同一段提示词，逐张修改图片。';
  $('#batch-compose-title').textContent = video ? '首尾帧与视频参数' : '图片与修改要求';
  $('#batch-prompt-label').textContent = video ? '视频提示词（每段共用）' : '想如何修改？';
}

document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => switchView(button.dataset.view));
$('#go-settings').onclick = () => switchView('settings');
$('#batch-tool').onchange = switchTool;
window.addEventListener('hashchange', () => switchView(location.hash.slice(1)));
document.querySelectorAll('button:disabled, input:disabled, textarea:disabled, select:disabled').forEach(node => {
  node.title = '仅展示。实际处理请在本机运行 ComfyUI Workbench。';
});
switchTool();
switchView(location.hash.slice(1));
