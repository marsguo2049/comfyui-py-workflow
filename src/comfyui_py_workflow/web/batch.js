// Workspace navigation and batch jobs share the existing local API helpers.
const views = {
  story: ['STORY TO VIDEO', '把故事，变成画面。', '从一个想法开始，在本机完成分镜与视频。'],
  batch: ['BATCH TOOLS', '一次设定，批量完成。', '重复的图片处理，交给本地工作流。'],
  settings: ['LOCAL SERVICES', '连接你的创作引擎。', '统一管理本机服务，供各个工作区使用。'],
};
function switchView(name) {
  if (!views[name]) name = 'story';
  for (const key of Object.keys(views)) $(`#view-${key}`).classList.toggle('hidden', key !== name);
  document.querySelectorAll('[data-view]').forEach(button => {
    button.classList.toggle('active', button.dataset.view === name);
    if (button.dataset.view === name) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  ['eyebrow', 'title', 'subtitle'].forEach((key, index) => $(`#view-${key}`).textContent = views[name][index]);
  if (location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
}
document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => switchView(button.dataset.view));
$('#go-settings').onclick = () => switchView('settings');
window.addEventListener('hashchange', () => switchView(location.hash.slice(1)));
switchView(location.hash.slice(1));

const batchState = {files: [], job: null, uploading: false, polling: false, loading: false};
const statusLabels = {draft: '待开始', running: '处理中', stopping: '停止中', cancelled: '已停止', interrupted: '已中断', failed: '运行失败', completed_with_errors: '部分失败', succeeded: '已完成'};
const batchMedia = (id, path) => `/batch-media/${encodeURIComponent(id)}/${path.split('/').map(encodeURIComponent).join('/')}`;
function batchError(error) {
  $('#batch-error').textContent = error ? error.message : '';
  $('#batch-error').classList.toggle('hidden', !error);
}
function updateBatchControls() {
  const locked = batchState.uploading || batchState.loading || Boolean(batchState.job && batchState.job.status !== 'draft');
  $('#batch-inputs').querySelectorAll('input, textarea, button').forEach(node => node.disabled = locked);
  $('#batch-start').disabled = locked || !(batchState.files.length || batchState.job?.files.length);
  $('#batch-new').disabled = batchState.uploading || batchState.loading;
  $('#batch-start').textContent = batchState.uploading ? '正在上传到本机…' : '开始批量处理 →';
}
function addBatchFiles(files) {
  if (batchState.uploading || batchState.loading || batchState.job) return;
  batchError(null);
  const known = new Set(batchState.files.map(f => `${f.webkitRelativePath || f.name}:${f.size}:${f.lastModified}`));
  let bytes = batchState.files.reduce((sum, file) => sum + file.size, 0);
  let skipped = 0;
  for (const file of files) {
    if (!/\.(png|jpe?g|webp|bmp|gif|tiff?)$/i.test(file.name)) { skipped++; continue; }
    const key = `${file.webkitRelativePath || file.name}:${file.size}:${file.lastModified}`;
    if (known.has(key)) continue;
    if (!file.size || file.size > 25 * 1024 * 1024 || bytes + file.size > 500 * 1024 * 1024 || batchState.files.length >= 200) {
      batchError(new Error('部分图片未添加：最多 200 张，单张 25 MB，合计 500 MB，且不能是空文件。'));
      continue;
    }
    known.add(key); bytes += file.size; batchState.files.push(file);
  }
  if (skipped) toast(`已跳过 ${skipped} 个不支持的文件`);
  renderSelection();
}
function renderSelection() {
  const files = batchState.job ? batchState.job.files : batchState.files;
  $('#batch-selection-count').textContent = files.length ? `已添加 ${files.length} 张图片` : '尚未添加图片';
  $('#batch-selection').replaceChildren();
  files.forEach((file, index) => {
    const row = document.createElement('div'); row.className = 'selection-row';
    const name = document.createElement('span'); name.textContent = file.name;
    const size = document.createElement('small'); size.textContent = `${((file.size ?? file.bytes) / 1024 / 1024).toFixed(1)} MB`;
    row.append(name, size);
    if (!batchState.job) {
      const remove = document.createElement('button'); remove.className = 'text-button'; remove.textContent = '×'; remove.setAttribute('aria-label', `移除 ${file.name}`);
      remove.onclick = () => { batchState.files.splice(index, 1); renderSelection(); };
      row.append(remove);
    }
    $('#batch-selection').append(row);
  });
  $('#batch-drop').classList.toggle('hidden', Boolean(batchState.job));
  $('#batch-clear').classList.toggle('hidden', Boolean(batchState.job) || !files.length);
  updateBatchControls();
}
for (const id of ['batch-files', 'batch-folder']) $(`#${id}`).onchange = event => { addBatchFiles(event.target.files); event.target.value = ''; };
$('#batch-clear').onclick = () => { batchState.files = []; renderSelection(); };
for (const eventName of ['dragenter', 'dragover']) $('#batch-drop').addEventListener(eventName, event => { event.preventDefault(); $('#batch-drop').classList.add('dragging'); });
for (const eventName of ['dragleave', 'drop']) $('#batch-drop').addEventListener(eventName, event => { event.preventDefault(); $('#batch-drop').classList.remove('dragging'); });
$('#batch-drop').addEventListener('drop', event => addBatchFiles(event.dataTransfer.files));

function renderBatchJob(job) {
  batchState.job = job;
  $('#batch-status').textContent = statusLabels[job.status] || job.status;
  $('#batch-status').dataset.status = job.status;
  $('#batch-message').textContent = job.message;
  $('#batch-progress').value = job.files.length ? job.completed / job.files.length * 100 : 0;
  $('#batch-completed').textContent = `${job.completed}/${job.files.length}`;
  $('#batch-succeeded').textContent = job.succeeded;
  $('#batch-failed').textContent = job.failed;
  $('#batch-cancel').classList.toggle('hidden', !['running', 'stopping'].includes(job.status));
  $('#batch-cancel').disabled = job.status === 'stopping';
  $('#batch-open').classList.remove('hidden');
  const results = $('#batch-results');
  // Avoid replacing image elements on each poll: preserve loading and keyboard focus.
  const version = `${job.id}:${job.results.length}`;
  if (results.dataset.version !== version) {
    results.dataset.version = version;
    results.replaceChildren();
    if (!job.results.length) {
      const empty = document.createElement('div'); empty.className = 'empty-results';
      empty.textContent = '处理后的图片会出现在这里，每完成一张自动更新。'; results.append(empty);
    }
    for (const item of job.results) {
      const card = document.createElement('article'); card.className = 'result-card';
      if (item.output) {
        const link = document.createElement('a'); link.href = batchMedia(job.id, item.output); link.target = '_blank'; link.rel = 'noopener';
        const img = document.createElement('img'); img.src = link.href; img.alt = item.name; img.loading = 'lazy'; link.append(img); card.append(link);
      }
      const title = document.createElement('strong'); title.textContent = item.name; card.append(title);
      if (item.error) { const error = document.createElement('p'); error.className = 'result-error'; error.textContent = item.error; card.append(error); }
      else {
        const links = document.createElement('div'); links.className = 'result-links';
        const original = document.createElement('a'); original.textContent = '查看原图'; original.href = batchMedia(job.id, item.source); original.target = '_blank'; original.rel = 'noopener';
        const download = document.createElement('a'); download.textContent = '下载结果 ↓'; download.href = batchMedia(job.id, item.output); download.download = item.output.split('/').pop();
        links.append(original, download); card.append(links);
      }
      results.append(card);
    }
  }
  updateBatchControls();
}
async function refreshBatchHistory() {
  const {jobs} = await api('/api/batch/jobs');
  const container = $('#batch-history'); container.replaceChildren();
  if (!jobs.length) { const empty = document.createElement('p'); empty.className = 'hint'; empty.textContent = '还没有批量任务'; container.append(empty); }
  for (const job of jobs.slice(0, 20)) {
    const button = document.createElement('button'); button.className = 'history-item';
    const title = document.createElement('strong'); title.textContent = `图片编辑 · ${statusLabels[job.status] || job.status}`;
    const detail = document.createElement('small'); detail.textContent = `${new Date(job.updated_at).toLocaleString('zh-CN')} · ${job.succeeded} 张成功`;
    button.append(title, detail); button.disabled = batchState.uploading || batchState.loading;
    button.onclick = () => loadBatchJob(job.id).catch(batchError); container.append(button);
  }
}
async function loadBatchJob(id) {
  if (batchState.uploading || batchState.loading) return;
  batchState.loading = true; updateBatchControls();
  try {
    const job = await api(`/api/batch/job?id=${encodeURIComponent(id)}`);
    batchState.files = [];
    const settings = job.settings || {};
    $('#batch-prompt').value = settings.prompt || '';
    $('#batch-negative').value = settings.negative_prompt || '';
    $('#batch-seed').value = settings.base_seed ?? 43;
    $('#batch-timeout').value = settings.timeout_seconds ?? 900;
    $('#batch-increment').checked = settings.increment_seed ?? true;
    $('#batch-workflow').value = settings.workflow_path || '';
    renderBatchJob(job); renderSelection(); batchError(null);
  } finally { batchState.loading = false; updateBatchControls(); }
}
$('#batch-new').onclick = () => {
  batchState.job = null; batchState.files = []; batchError(null); renderSelection();
  $('#batch-status').textContent = '待开始'; $('#batch-status').dataset.status = 'draft';
  $('#batch-message').textContent = '添加图片和修改要求，开始新一批处理。';
  $('#batch-progress').value = 0; $('#batch-completed').textContent = '0/0'; $('#batch-succeeded').textContent = '0'; $('#batch-failed').textContent = '0';
  $('#batch-cancel').classList.add('hidden'); $('#batch-open').classList.add('hidden');
  $('#batch-results').replaceChildren(); delete $('#batch-results').dataset.version;
  const empty = document.createElement('div'); empty.className = 'empty-results'; empty.textContent = '处理后的图片会出现在这里'; $('#batch-results').append(empty);
};
$('#batch-start').onclick = async () => {
  batchError(null);
  try {
    if (!$('#batch-prompt').value.trim()) throw new Error('请填写修改要求');
    if (!$('#batch-seed').checkValidity() || !$('#batch-timeout').checkValidity()) throw new Error('请检查种子和超时参数');
    const settings = {prompt: $('#batch-prompt').value, negative_prompt: $('#batch-negative').value,
      base_seed: Number($('#batch-seed').value), timeout_seconds: Number($('#batch-timeout').value),
      increment_seed: $('#batch-increment').checked, workflow_path: $('#batch-workflow').value.trim(), comfyui_url: $('#comfy-url').value.trim()};
    batchState.uploading = true; updateBatchControls();
    $('#batch-history').querySelectorAll('button').forEach(button => button.disabled = true);
    if (!batchState.job) batchState.job = await jsonPost('/api/batch/create', {kind: $('#batch-tool').value});
    // Remove a local file only after a confirmed upload, so retries keep the remaining files.
    while (batchState.files.length) {
      const file = batchState.files[0];
      $('#batch-message').textContent = `正在上传到本机：${file.name}`;
      batchState.job = await api(`/api/batch/upload?id=${batchState.job.id}&filename=${encodeURIComponent(file.name)}`, {method: 'POST', body: file});
      batchState.files.shift();
    }
    renderSelection();
    renderBatchJob(await jsonPost('/api/batch/start', {id: batchState.job.id, ...settings}));
  } catch (error) { batchError(error); }
  finally { batchState.uploading = false; updateBatchControls(); refreshBatchHistory().catch(batchError); }
};
$('#batch-cancel').onclick = async () => {
  const id = batchState.job?.id;
  if (!id) return;
  try { const job = await jsonPost('/api/batch/cancel', {id}); if (batchState.job?.id === id) renderBatchJob(job); }
  catch (error) { batchError(error); }
};
$('#batch-open').onclick = () => jsonPost('/api/batch/open-folder', {id: batchState.job.id}).catch(batchError);
$('#batch-refresh').onclick = () => refreshBatchHistory().catch(batchError);
setInterval(async () => {
  if (batchState.polling || batchState.loading || batchState.uploading || !batchState.job || !['running', 'stopping'].includes(batchState.job.status)) return;
  batchState.polling = true; const id = batchState.job.id;
  try {
    const job = await api(`/api/batch/job?id=${id}`);
    if (batchState.job?.id === id && !batchState.loading) {
      renderBatchJob(job);
      if (!['running', 'stopping'].includes(job.status)) await refreshBatchHistory();
    }
  } catch (error) { batchError(error); }
  finally { batchState.polling = false; }
}, 2000);
async function initBatch() {
  const {tools} = await api('/api/batch/tools');
  $('#batch-tool').replaceChildren(...tools.map(tool => { const option = document.createElement('option'); option.value = tool.id; option.textContent = tool.name; return option; }));
  await refreshBatchHistory(); updateBatchControls();
}
initBatch().catch(batchError);
