// Batch jobs only. Host shells provide navigation plus api/jsonPost/toast helpers.
const batchState = {files: [], job: null, uploading: false, polling: false, loading: false};
const isBatchVideo = () => $('#batch-tool').value === 'first-last-video';
let batchPreviewVersion = 0;
function batchVideoSettings() {
  return {pairing_mode: $('#batch-pairing').value, duration_seconds: Number($('#batch-duration').value),
    aspect_ratio: $('#batch-aspect').value, megapixels: Number($('#batch-megapixels').value), steps: Number($('#batch-steps').value)};
}
function batchSelectedFiles() {
  return [...(batchState.job?.files || []), ...batchState.files];
}
const batchDisplayPath = file => file.relative_path || file.webkitRelativePath || file.name;
function renderPairs(pairs) {
  const container = $('#batch-pair-preview'); container.replaceChildren();
  pairs.forEach((pair, index) => {
    const row = document.createElement('div'); row.className = 'selection-row';
    row.textContent = `${index + 1}. ${pair.first.name} → ${pair.last.name}`;
    container.append(row);
  });
}
async function previewBatchPairs() {
  const version = ++batchPreviewVersion;
  if (!isBatchVideo()) return;
  if (batchState.job?.pairs) {
    renderPairs(batchState.job.pairs);
    const settings = batchState.job.settings;
    $('#batch-duration-hint').textContent = `预计每段 ${settings.actual_duration_seconds.toFixed(2)} 秒 · ${settings.frame_count} 帧 / 24 fps · 共 ${batchState.job.pairs.length} 段`;
    return;
  }
  try {
    const result = await jsonPost('/api/batch/video-preview', {...batchVideoSettings(),
      files: batchSelectedFiles().map(file => ({name: file.name, role: file.role}))});
    if (version !== batchPreviewVersion) return;
    renderPairs(result.pairs);
    $('#batch-duration-hint').textContent = `预计每段 ${result.actual_duration_seconds.toFixed(2)} 秒 · ${result.frame_count} 帧 / 24 fps · 共 ${result.pairs.length} 段。H3 帧数对齐后可能略长于设定值。`;
  } catch (error) {
    if (version !== batchPreviewVersion) return;
    $('#batch-duration-hint').textContent = '';
    $('#batch-pair-preview').textContent = error.message;
  }
}
function updateBatchTool() {
  const video = isBatchVideo();
  $('#batch-video-inputs').classList.toggle('hidden', !video);
  $('#batch-drop').classList.toggle('hidden', video || Boolean(batchState.job));
  $('#batch-negative-field').classList.toggle('hidden', video);
  $('#batch-model').textContent = video ? 'MiniMax H3' : 'Qwen Image Edit 2509';
  $('#batch-tool-description').textContent = video ? '选择首尾帧，按配对批量生成视频。' : '用同一段提示词，逐张修改图片。';
  $('#batch-compose-title').textContent = video ? '首尾帧与视频参数' : '图片与修改要求';
  $('#batch-prompt-label').textContent = video ? '视频提示词（每段共用）' : '想如何修改？';
  $('#batch-prompt').placeholder = video ? '例如：镜头缓缓推进，人物自然转身，平滑过渡至尾帧画面。描述动作、镜头与场景变化。' : '例如：把背景换成浅灰色摄影棚，保留主体和自然阴影。';
  $('#batch-workflow').placeholder = video ? '留空使用内置 MiniMax H3 首尾帧工作流' : '留空使用内置 Qwen Image Edit 2509';
  $('#batch-workflow-hint').textContent = video ? '自定义工作流须兼容内置 H3 节点与连接。输出按任务单独保存。' : '自定义工作流需兼容现有 Qwen 节点。输出按任务单独保存，不会覆盖原图。';
  $('#batch-cancel').textContent = video ? '当前视频后停止' : '当前图片后停止';
  previewBatchPairs();
}
for (const id of ['batch-pairing', 'batch-duration', 'batch-aspect', 'batch-megapixels', 'batch-steps']) {
  $(`#${id}`).onchange = previewBatchPairs;
}
const statusLabels = {draft: '待开始', running: '处理中', stopping: '停止中', cancelled: '已停止', interrupted: '已中断', failed: '运行失败', completed_with_errors: '部分失败', succeeded: '已完成'};
const batchMedia = (id, path) => `/batch-media/${encodeURIComponent(id)}/${path.split('/').map(encodeURIComponent).join('/')}`;
function batchError(error) {
  $('#batch-error').textContent = error ? error.message : '';
  $('#batch-error').classList.toggle('hidden', !error);
}
function updateBatchControls() {
  const locked = batchState.uploading || batchState.loading || Boolean(batchState.job && batchState.job.status !== 'draft');
  $('#batch-inputs').querySelectorAll('input, textarea, button, select').forEach(node => node.disabled = locked);
  $('#batch-tool').disabled = batchState.uploading || batchState.loading;
  $('#batch-start').disabled = locked || !(batchState.files.length || batchState.job?.files.length);
  $('#batch-new').disabled = batchState.uploading || batchState.loading;
  $('#batch-start').textContent = batchState.uploading ? '正在上传到本机…' : '开始批量处理 →';
}
function addBatchFiles(files, role = '') {
  if (batchState.uploading || batchState.loading || batchState.job) return;
  batchError(null);
  const known = new Set(batchState.files.map(f => `${f.role || ''}:${f.webkitRelativePath || f.name}:${f.size}:${f.lastModified}`));
  let bytes = batchState.files.reduce((sum, file) => sum + file.size, 0);
  let skipped = 0;
  for (const file of files) {
    if (!/\.(png|jpe?g|webp|bmp|gif|tiff?)$/i.test(file.name)) { skipped++; continue; }
    if (file.name.length > 180) { batchError(new Error('文件名不能超过 180 字符，请先重命名。')); continue; }
    const key = `${role}:${file.webkitRelativePath || file.name}:${file.size}:${file.lastModified}`;
    if (known.has(key)) continue;
    if (!file.size || file.size > 25 * 1024 * 1024 || bytes + file.size > 500 * 1024 * 1024 || batchState.files.length >= 200) {
      batchError(new Error('部分图片未添加：最多 200 张，单张 25 MB，合计 500 MB，且不能是空文件。'));
      continue;
    }
    known.add(key); bytes += file.size;
    // Keep the browser File immutable: the same File may be selected on both sides.
    batchState.files.push({file, role, name: file.name, size: file.size,
      lastModified: file.lastModified, webkitRelativePath: file.webkitRelativePath});
  }
  if (skipped) toast(`已跳过 ${skipped} 个不支持的文件`);
  renderSelection();
}
function renderSelection() {
  const files = batchSelectedFiles();
  $('#batch-selection-count').textContent = files.length ? `已添加 ${files.length} 张图片` : '尚未添加图片';
  const containers = {all: $('#batch-selection'), first: $('#batch-first-selection'), last: $('#batch-last-selection')};
  Object.values(containers).forEach(container => container.replaceChildren());
  function appendRow(container, file, index, showRole) {
    const row = document.createElement('div'); row.className = 'selection-row';
    const name = document.createElement('span');
    name.textContent = `${showRole && file.role ? (file.role === 'first' ? '首帧 · ' : '尾帧 · ') : ''}${batchDisplayPath(file)}`;
    const size = document.createElement('small'); size.textContent = `${((file.size ?? file.bytes) / 1024 / 1024).toFixed(1)} MB`;
    row.append(name, size);
    if (!batchState.job) {
      const remove = document.createElement('button'); remove.className = 'text-button'; remove.textContent = '×'; remove.setAttribute('aria-label', `移除 ${file.name}`);
      remove.onclick = () => { batchState.files.splice(index, 1); renderSelection(); };
      row.append(remove);
    }
    container.append(row);
  }
  files.forEach((file, index) => {
    appendRow(containers.all, file, index, true);
    if (file.role === 'first' || file.role === 'last') appendRow(containers[file.role], file, index, false);
  });
  for (const role of ['first', 'last']) {
    const count = files.filter(file => file.role === role).length;
    $(`#batch-${role}-count`).textContent = count ? `已选择 ${count} 张` : '尚未选择';
  }
  $('#batch-selection-summary').classList.toggle('hidden', isBatchVideo());
  $('#batch-drop').classList.toggle('hidden', isBatchVideo() || Boolean(batchState.job));
  $('#batch-clear').classList.toggle('hidden', Boolean(batchState.job) || !files.length);
  updateBatchControls();
  previewBatchPairs();
}
for (const role of ['first', 'last']) for (const kind of ['files', 'folder']) {
  $(`#batch-${role}-${kind}`).onchange = event => { addBatchFiles(event.target.files, role); event.target.value = ''; };
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
  const total = job.pairs?.length ?? job.files.length;
  $('#batch-progress').value = total ? job.completed / total * 100 : 0;
  $('#batch-completed').textContent = `${job.completed}/${total}`;
  $('#batch-succeeded').textContent = job.succeeded;
  $('#batch-failed').textContent = job.failed;
  $('#batch-cancel').classList.toggle('hidden', !['running', 'stopping'].includes(job.status));
  $('#batch-cancel').disabled = job.status === 'stopping';
  $('#batch-open').classList.remove('hidden');
  const results = $('#batch-results');
  // Append results for the same job so playing videos retain position and volume.
  const version = `${job.id}:${job.results.length}`;
  if (results.dataset.version !== version) {
    const previousId = results.dataset.version?.split(':')[0];
    const previousCount = Number(results.dataset.version?.split(':')[1] || 0);
    const append = previousId === job.id && previousCount > 0 && previousCount <= job.results.length;
    results.dataset.version = version;
    if (!append) results.replaceChildren();
    if (!job.results.length) {
      const empty = document.createElement('div'); empty.className = 'empty-results';
      empty.textContent = '生成结果会出现在这里，每完成一项自动更新。'; results.append(empty);
    }
    for (const item of job.results.slice(append ? previousCount : 0)) {
      const card = document.createElement('article'); card.className = 'result-card';
      if (item.output) {
        const link = document.createElement('a'); link.href = batchMedia(job.id, item.output); link.target = '_blank'; link.rel = 'noopener';
        if (job.kind === 'first-last-video') {
          const video = document.createElement('video'); video.src = link.href; video.controls = true;
          video.preload = 'metadata'; video.style.width = '100%'; video.setAttribute('aria-label', item.name); card.append(video);
        } else {
          const img = document.createElement('img'); img.src = link.href; img.alt = item.name; img.loading = 'lazy'; link.append(img); card.append(link);
        }
      }
      const title = document.createElement('strong'); title.textContent = item.name; card.append(title);
      if (item.duration_seconds) { const duration = document.createElement('small'); duration.textContent = `生成时长（帧数 / 帧率）：${item.duration_seconds.toFixed(2)} 秒`; card.append(duration); }
      if (item.error) { const error = document.createElement('p'); error.className = 'result-error'; error.textContent = item.error; card.append(error); }
      else {
        const links = document.createElement('div'); links.className = 'result-links';
        const original = document.createElement('a'); original.textContent = '查看原图'; original.href = batchMedia(job.id, item.source); original.target = '_blank'; original.rel = 'noopener';
        const download = document.createElement('a'); download.textContent = '下载结果 ↓'; download.href = batchMedia(job.id, item.output); download.download = item.output.split('/').pop();
        if (item.last_source) {
          original.textContent = '查看首帧';
          const last = document.createElement('a'); last.textContent = '查看尾帧'; last.href = batchMedia(job.id, item.last_source); last.target = '_blank'; last.rel = 'noopener';
          links.append(original, last, download);
        } else links.append(original, download);
        card.append(links);
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
    const title = document.createElement('strong'); title.textContent = `${job.kind === 'first-last-video' ? '首尾帧视频' : '图片编辑'} · ${statusLabels[job.status] || job.status}`;
    const detail = document.createElement('small'); detail.textContent = `${new Date(job.updated_at).toLocaleString('zh-CN')} · ${job.succeeded} 项成功`;
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
    batchState.job = job;
    $('#batch-tool').value = job.kind;
    const settings = job.settings || {};
    $('#batch-prompt').value = settings.prompt || '';
    $('#batch-negative').value = settings.negative_prompt || '';
    $('#batch-seed').value = settings.base_seed ?? 43;
    $('#batch-timeout').value = settings.timeout_seconds ?? 900;
    $('#batch-increment').checked = settings.increment_seed ?? true;
    $('#batch-workflow').value = settings.workflow_path || '';
    for (const [id, key, fallback] of [['duration', 'duration_seconds', 5], ['aspect', 'aspect_ratio', '1:1 (Square)'],
      ['megapixels', 'megapixels', 0.6], ['steps', 'steps', 4], ['pairing', 'pairing_mode', 'order']]) {
      $(`#batch-${id}`).value = settings[key] ?? fallback;
    }
    updateBatchTool();
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
  const empty = document.createElement('div'); empty.className = 'empty-results'; empty.textContent = '生成结果会出现在这里'; $('#batch-results').append(empty);
  updateBatchTool();
};
$('#batch-tool').onchange = () => {
  $('#batch-workflow').value = '';
  $('#batch-timeout').value = isBatchVideo() ? 1800 : 900;
  $('#batch-new').onclick();
};
$('#batch-start').onclick = async () => {
  batchError(null);
  try {
    if (!$('#batch-prompt').value.trim()) throw new Error('请填写提示词');
    if (!$('#batch-seed').checkValidity() || !$('#batch-timeout').checkValidity()) throw new Error('请检查种子和超时参数');
    const settings = {prompt: $('#batch-prompt').value, negative_prompt: $('#batch-negative').value,
      base_seed: Number($('#batch-seed').value), timeout_seconds: Number($('#batch-timeout').value),
      increment_seed: $('#batch-increment').checked, workflow_path: $('#batch-workflow').value.trim(), comfyui_url: $('#comfy-url').value.trim()};
    batchState.uploading = true; updateBatchControls();
    if (isBatchVideo()) {
      Object.assign(settings, batchVideoSettings());
      // Use the same server pairing rules for preview and execution, before uploading or creating a job.
      await jsonPost('/api/batch/video-preview', {...settings,
        files: batchSelectedFiles().map(file => ({name: file.name, role: file.role}))});
    }
    $('#batch-history').querySelectorAll('button').forEach(button => button.disabled = true);
    if (!batchState.job) batchState.job = await jsonPost('/api/batch/create', {kind: $('#batch-tool').value});
    // Remove a local file only after a confirmed upload, so retries keep the remaining files.
    while (batchState.files.length) {
      const file = batchState.files[0];
      const relativePath = batchDisplayPath(file);
      $('#batch-message').textContent = `正在上传到本机：${relativePath}`;
      batchState.job = await api(`/api/batch/upload?id=${batchState.job.id}&filename=${encodeURIComponent(file.name)}&role=${encodeURIComponent(file.role || '')}&relative_path=${encodeURIComponent(relativePath)}`, {method: 'POST', body: file.file});
      batchState.files.shift();
    }
    renderSelection();
    renderBatchJob(await jsonPost('/api/batch/start', {id: batchState.job.id, ...settings}));
    previewBatchPairs();
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
  await refreshBatchHistory(); updateBatchControls(); updateBatchTool();
}
initBatch().catch(batchError);
