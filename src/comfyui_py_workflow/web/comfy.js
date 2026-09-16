const $ = selector => document.querySelector(selector);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.message || `请求失败：${response.status}`);
  return payload;
}

async function jsonPost(path, body) {
  return api(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
}

let toastTimer;
function toast(message) {
  const node = $('#toast');
  node.textContent = message;
  node.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove('show'), 2400);
}

const workbenchViews = {
  batch: ['BATCH TOOLS', '一次设定，批量完成。', '批量修改图片，或用首尾帧生成视频。'],
  settings: ['COMFYUI SETTINGS', '连接你的生成引擎。', '检测并保存本机 ComfyUI 地址。'],
};

function switchView(name) {
  if (!workbenchViews[name]) name = 'batch';
  for (const key of Object.keys(workbenchViews)) $(`#view-${key}`).classList.toggle('hidden', key !== name);
  document.querySelectorAll('[data-view]').forEach(button => {
    const selected = button.dataset.view === name;
    button.classList.toggle('active', selected);
    if (selected) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  ['eyebrow', 'title', 'subtitle'].forEach((key, index) => $(`#view-${key}`).textContent = workbenchViews[name][index]);
  if (location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
}

async function refreshComfyUI() {
  const url = $('#comfy-url').value.trim();
  localStorage.setItem('cpw-comfy-url', url);
  const card = $('#comfy-status');
  card.querySelector('p').textContent = '检测中…';
  try {
    const status = await api(`/api/status?comfy=${encodeURIComponent(url)}`);
    card.querySelector('p').textContent = status.comfyui.ok ? '已连接，可以运行批量任务。' : status.comfyui.message;
    card.classList.toggle('connected', status.comfyui.ok);
    $('#service-summary').textContent = status.comfyui.ok ? '已连接' : '未连接';
  } catch (error) {
    card.querySelector('p').textContent = error.message;
    card.classList.remove('connected');
    $('#service-summary').textContent = '未连接';
  }
}

$('#comfy-url').value = localStorage.getItem('cpw-comfy-url') || $('#comfy-url').value;
$('#comfy-url').addEventListener('change', refreshComfyUI);
$('#refresh-services').onclick = refreshComfyUI;
document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => switchView(button.dataset.view));
$('#go-settings').onclick = () => switchView('settings');
window.addEventListener('hashchange', () => switchView(location.hash.slice(1)));
switchView(location.hash.slice(1));
refreshComfyUI();
