const comicState = {job: null, busy: false, polling: false, dirty: false, planVersion: null, resultVersion: null};
const comicStatus = {draft: '待规划', planning: '规划中', ready: '待生成', running: '生成中', stopping: '停止中',
  cancelled: '已停止', interrupted: '已中断', failed: '失败', succeeded: '已完成'};
let comicReferenceUrl;
const comicActive = () => Boolean(comicState.job && ['planning', 'running', 'stopping'].includes(comicState.job.status));
const comicMedia = path => `/comic-media/${encodeURIComponent(comicState.job.id)}/${path.split('/').map(encodeURIComponent).join('/')}?v=${encodeURIComponent(comicState.job.updated_at)}`;
function comicError(error) {
  $('#comic-error').textContent = error?.message || '';
  $('#comic-error').classList.toggle('hidden', !error);
}
function comicControls() {
  const locked = comicState.busy || comicActive();
  $('#comic-source-fields').querySelectorAll('input, textarea').forEach(node => node.disabled = locked || Boolean(comicState.job));
  $('#comic-planning-fields').querySelectorAll('input, select').forEach(node => node.disabled = locked || Boolean(comicState.job?.results.length));
  $('#comic-plan-fields').querySelectorAll('input, textarea, select').forEach(node => node.disabled = locked);
  $('#comic-plan').disabled = locked || Boolean(comicState.job?.results.length);
  $('#comic-plan').textContent = comicState.job?.plan ? '重新规划漫画分镜' : '生成漫画分镜 →';
  $('#comic-new').disabled = comicState.busy;
  $('#comic-save').disabled = locked || !comicState.dirty;
  $('#comic-generate').disabled = locked || !comicState.job?.plan || (comicState.job.status === 'succeeded' && !comicState.dirty);
  $('#comic-generate').textContent = comicState.job?.completed ? '继续生成未完成分格 →' : '确认分镜，生成漫画 →';
  $('#comic-seed').disabled = locked;
  $('#comic-timeout').disabled = locked;
  $('#comic-cancel').classList.toggle('hidden', !comicActive());
  $('#comic-cancel').disabled = comicState.busy || comicState.job?.status === 'stopping';
  $('#comic-open').classList.toggle('hidden', !comicState.job);
  $('#comic-results').querySelectorAll('button').forEach(node => node.disabled = locked);
  $('#comic-history').querySelectorAll('button').forEach(node => node.disabled = comicState.busy);
  $('#comic-dirty').textContent = comicState.dirty ? '有未保存修改' : '已保存';
}
function markComicDirty() { comicState.dirty = true; comicControls(); }
$('#comic-plan-fields').oninput = markComicDirty;
$('#comic-plan-fields').onchange = markComicDirty;

function renderComicPlan(job) {
  const plan = job.plan;
  const version = `${job.id}:${job.revision}`;
  if (!plan || comicState.planVersion === version) return;
  comicState.planVersion = version; comicState.dirty = false;
  $('#comic-title').value = plan.title;
  $('#comic-bible').value = plan.character_bible;
  $('#comic-plan-style').value = plan.style;
  $('#comic-negative').value = plan.negative_prompt;
  $('#comic-panels').replaceChildren();
  for (const panel of plan.panels) {
    const card = document.createElement('article'); card.className = 'comic-panel-editor';
    const heading = document.createElement('h3'); heading.textContent = `第 ${panel.index} 格`; card.append(heading);
    for (const [field, name, rows, limit] of [['description', '这一格发生什么', 2, 1000], ['prompt', '画面提示词', 4, 5000],
      ['caption', '旁白（可留空）', 2, 300], ['dialogue', '对白（人物：台词，可留空）', 2, 300]]) {
      const label = document.createElement('label'); label.textContent = name;
      const input = document.createElement('textarea'); input.dataset.field = field; input.rows = rows;
      input.maxLength = limit; input.value = panel[field]; label.append(input); card.append(label);
    }
    const label = document.createElement('label'); label.textContent = '画面参考';
    const select = document.createElement('select'); select.dataset.field = 'reference';
    for (const [value, text] of [['anchor', '人物参考图 / 首格（切换场景）'], ['previous', '上一格（连续动作）']]) {
      if (panel.index === 1 && value === 'previous') continue;
      const option = document.createElement('option'); option.value = value; option.textContent = text; select.append(option);
    }
    select.value = panel.reference; label.append(select); card.append(label); $('#comic-panels').append(card);
  }
}
function readComicPlan() {
  const plan = structuredClone(comicState.job.plan);
  plan.title = $('#comic-title').value;
  plan.character_bible = $('#comic-bible').value;
  plan.style = $('#comic-plan-style').value;
  plan.negative_prompt = $('#comic-negative').value;
  $('#comic-panels').querySelectorAll('.comic-panel-editor').forEach((card, index) => {
    card.querySelectorAll('[data-field]').forEach(input => plan.panels[index][input.dataset.field] = input.value);
  });
  return plan;
}
function renderComic(job) {
  comicState.job = job;
  $('#comic-status').textContent = comicStatus[job.status] || job.status;
  $('#comic-status').dataset.status = job.status;
  $('#comic-message').textContent = job.message;
  const total = job.plan?.panels.length || 0;
  $('#comic-progress').value = total ? job.completed / total * 100 : 0;
  $('#comic-metrics').textContent = `${job.completed}/${total} 格已完成`;
  $('#comic-warnings').textContent = (job.warnings || []).join('\n');
  $('#comic-warnings').classList.toggle('hidden', !job.warnings?.length);
  $('#comic-plan-panel').classList.toggle('hidden', !job.plan);
  $('#comic-source-note').textContent = '故事已保存在当前漫画项目中；修改故事或参考图请新建漫画。';
  renderComicPlan(job);
  const version = `${job.id}:${job.revision}:${job.results.length}:${job.status}`;
  if (comicState.resultVersion !== version) {
    comicState.resultVersion = version;
    $('#comic-results').replaceChildren();
    if (!job.results.length) {
      const empty = document.createElement('div'); empty.className = 'empty-results'; empty.textContent = '每完成一格，就会出现在这里。'; $('#comic-results').append(empty);
    }
    for (const result of job.results) {
      const panel = job.plan.panels[result.index - 1];
      const figure = document.createElement('figure'); figure.className = 'comic-frame';
      const link = document.createElement('a'); link.href = comicMedia(result.path); link.target = '_blank'; link.rel = 'noopener';
      const img = document.createElement('img'); img.src = link.href; img.alt = `第 ${result.index} 格：${panel.description}`; img.loading = 'lazy'; link.append(img); figure.append(link);
      const caption = document.createElement('figcaption');
      const title = document.createElement('strong'); title.textContent = `第 ${result.index} 格`; caption.append(title);
      for (const field of ['caption', 'dialogue']) { const text = document.createElement('p'); text.textContent = panel[field]; text.className = `comic-${field}`; caption.append(text); }
      const row = document.createElement('div'); row.className = 'button-row';
      const download = document.createElement('a'); download.href = link.href; download.download = result.path; download.textContent = '下载此格 ↓';
      const retry = document.createElement('button'); retry.className = 'secondary'; retry.textContent = '从此格重做'; retry.onclick = () => runComic(result.index);
      row.append(download, retry); caption.append(row); figure.append(caption); $('#comic-results').append(figure);
    }
    $('#comic-exports').replaceChildren();
    for (const [path, name, download] of [['comic.html', '打开阅读页 ↗', false], ['comic.html', '下载阅读页 ↓', true], ['comic.zip', '下载图片包 ↓', true]]) {
      if (!job.exports.includes(path)) continue;
      const link = document.createElement('a'); link.href = comicMedia(path); link.textContent = name;
      if (download) link.download = path; else { link.target = '_blank'; link.rel = 'noopener'; }
      $('#comic-exports').append(link);
    }
  }
  comicControls();
}
async function comicAction(action) {
  if (comicState.busy) return;
  comicState.busy = true; comicError(null); comicControls();
  try { await action(); }
  catch (error) { comicError(error); }
  finally { comicState.busy = false; comicControls(); refreshComics().catch(comicError); }
}
async function saveComic() {
  const job = await jsonPost('/api/comic/save-plan', {id: comicState.job.id, revision: comicState.job.revision, plan: readComicPlan()});
  renderComic(job);
}
async function runComic(retryFrom) {
  return comicAction(async () => {
    if (!$('#comic-seed').checkValidity() || !$('#comic-timeout').checkValidity()) throw new Error('请检查种子与超时');
    if (comicState.dirty) await saveComic();
    const settings = {id: comicState.job.id, revision: comicState.job.revision,
      comfyui_url: $('#comfy-url').value.trim(), base_seed: Number($('#comic-seed').value), timeout_seconds: Number($('#comic-timeout').value)};
    if (retryFrom) settings.retry_from = Math.min(retryFrom, comicState.job.results.length + 1);
    renderComic(await jsonPost('/api/comic/start', settings));
  });
}
$('#comic-generate').onclick = () => runComic();
$('#comic-save').onclick = () => comicAction(saveComic);
$('#comic-plan').onclick = () => comicAction(async () => {
  if (!$('#comic-count').checkValidity()) throw new Error('漫画格数必须是 2–16 的整数');
  if (!comicState.job) {
    const file = $('#comic-file').files[0];
    if (!file && !$('#comic-story').value.trim()) throw new Error('请先输入故事或选择文档');
    if (file && file.size > 100 * 1024 * 1024) throw new Error('故事文档不能超过 100 MB');
    comicState.job = file ? await api(`/api/comic/file?filename=${encodeURIComponent(file.name)}`, {method: 'POST', body: file})
      : await jsonPost('/api/comic/create', {text: $('#comic-story').value});
  }
  const reference = $('#comic-reference').files[0];
  if (reference && !comicState.job.reference && !comicState.job.plan) {
    if (reference.size > 25 * 1024 * 1024) throw new Error('参考图不能超过 25 MB');
    comicState.job = await api(`/api/comic/reference?id=${comicState.job.id}`, {method: 'POST', body: reference});
  }
  renderComic(await jsonPost('/api/comic/plan', {id: comicState.job.id, panel_count: Number($('#comic-count').value),
    aspect_ratio: $('#comic-aspect').value, style: $('#comic-style').value, lm_studio_url: $('#lm-url').value.trim(),
    model: $('#lm-model').value, unload_model: $('#comic-unload').checked}));
});
$('#comic-reference').onchange = event => {
  if (comicReferenceUrl) URL.revokeObjectURL(comicReferenceUrl);
  const file = event.target.files[0]; comicReferenceUrl = file ? URL.createObjectURL(file) : null;
  $('#comic-reference-preview').src = comicReferenceUrl || '';
  $('#comic-reference-preview').classList.toggle('hidden', !file);
};
$('#comic-new').onclick = () => {
  comicState.job = null; comicState.dirty = false; comicState.planVersion = null; comicState.resultVersion = null;
  $('#comic-plan-panel').classList.add('hidden'); $('#comic-status').textContent = '待开始';
  delete $('#comic-status').dataset.status;
  $('#comic-message').textContent = '输入故事，先生成可审阅的分镜。'; $('#comic-metrics').textContent = '尚未生成分格';
  $('#comic-source-note').textContent = '选择文档时以文档为准；内容只保存在本机。';
  $('#comic-progress').value = 0; $('#comic-warnings').classList.add('hidden'); $('#comic-results').replaceChildren(); $('#comic-exports').replaceChildren();
  $('#comic-story').value = ''; $('#comic-file').value = ''; $('#comic-reference').value = '';
  if (comicReferenceUrl) URL.revokeObjectURL(comicReferenceUrl);
  comicReferenceUrl = null; $('#comic-reference-preview').classList.add('hidden'); comicError(null); comicControls();
};
$('#comic-cancel').onclick = () => comicAction(async () => renderComic(await jsonPost('/api/comic/cancel', {id: comicState.job.id})));
$('#comic-open').onclick = () => jsonPost('/api/comic/open-folder', {id: comicState.job.id}).catch(comicError);
async function refreshComics() {
  const {jobs} = await api('/api/comic/jobs');
  $('#comic-history').replaceChildren();
  if (!jobs.length) { const empty = document.createElement('p'); empty.className = 'hint'; empty.textContent = '还没有漫画项目'; $('#comic-history').append(empty); }
  for (const job of jobs.slice(0, 20)) {
    const button = document.createElement('button'); button.className = 'history-item';
    const title = document.createElement('strong'); title.textContent = `${job.title || '漫画'} · ${comicStatus[job.status] || job.status}`;
    const date = document.createElement('small'); date.textContent = `${new Date(job.updated_at).toLocaleString('zh-CN')} · ${job.succeeded} 格完成`;
    button.append(title, date); button.disabled = comicState.busy;
    button.onclick = () => comicAction(async () => {
      const payload = await api(`/api/comic/job?id=${job.id}`);
      comicState.dirty = false; comicState.planVersion = null; comicState.resultVersion = null;
      $('#comic-story').value = ''; $('#comic-file').value = ''; $('#comic-reference').value = '';
      $('#comic-seed').value = payload.base_seed ?? 1000;
      if (payload.plan) { $('#comic-count').value = payload.plan.panels.length; $('#comic-aspect').value = payload.plan.aspect_ratio; $('#comic-style').value = payload.plan.style; }
      renderComic(payload);
      $('#comic-reference-preview').src = payload.reference ? comicMedia(payload.reference) : '';
      $('#comic-reference-preview').classList.toggle('hidden', !payload.reference);
    });
    $('#comic-history').append(button);
  }
}
$('#comic-refresh').onclick = () => refreshComics().catch(comicError);
setInterval(async () => {
  if (comicState.busy || comicState.polling || !comicActive()) return;
  const id = comicState.job.id; comicState.polling = true;
  try {
    const job = await api(`/api/comic/job?id=${id}`);
    if (!comicState.busy && comicState.job?.id === id && job.revision >= comicState.job.revision) {
      renderComic(job); if (!comicActive()) await refreshComics();
    }
  } catch (error) { comicError(error); }
  finally { comicState.polling = false; }
}, 2000);
comicControls(); refreshComics().catch(comicError);
