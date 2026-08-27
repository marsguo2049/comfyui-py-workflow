const $ = (selector) => document.querySelector(selector);
const state = { projectId: null, project: null, services: null, planVersion: null };
let toastTimer;
let localReferencePreviewUrl;

function toast(message, error = false) {
  const node = $('#toast');
  node.textContent = message;
  node.className = error ? 'show error' : 'show';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.className = '', 5200);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || `${response.status} ${response.statusText}`);
  return data;
}

function jsonPost(path, body) {
  return api(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
}

async function busy(button, action) {
  const old = button.textContent;
  button.disabled = true;
  button.textContent = '处理中…';
  try { return await action(); }
  catch (error) { toast(error.message, true); throw error; }
  finally { button.disabled = false; button.textContent = old; }
}

function serviceCard(selector, result) {
  const node = $(selector);
  node.classList.toggle('ok', Boolean(result.ok));
  node.classList.toggle('bad', !result.ok);
  node.querySelector('p').textContent = result.message;
}

async function refreshServices() {
  const button = $('#refresh-services');
  await busy(button, async () => {
    const lm = encodeURIComponent($('#lm-url').value.trim());
    const comfy = encodeURIComponent($('#comfy-url').value.trim());
    const result = await api(`/api/status?lm=${lm}&comfy=${comfy}`);
    state.services = result;
    serviceCard('#lm-status', result.lm_studio);
    serviceCard('#comfy-status', result.comfyui);
    const caps = result.capabilities;
    serviceCard('#ocr-status', {
      ok: caps.text_pdf && caps.media,
      message: `文字 PDF：${caps.text_pdf ? '可用' : '缺失'}；媒体：${caps.media ? '可用' : '缺失'}；扫描件 OCR：${caps.ocr ? caps.ocr_backend : '尚未安装'}`,
    });
    const modelSelect = $('#lm-model');
    const previous = modelSelect.value;
    modelSelect.innerHTML = '<option value="">请选择本地模型</option>';
    for (const model of result.lm_studio.models || []) {
      const option = document.createElement('option');
      option.value = option.textContent = model;
      modelSelect.append(option);
    }
    if ([...modelSelect.options].some(option => option.value === previous)) modelSelect.value = previous;
    else if ((result.lm_studio.models || []).length === 1) modelSelect.value = result.lm_studio.models[0];
  });
}

async function refreshProjects(selectNewest = false) {
  const result = await api('/api/projects');
  const select = $('#project-select');
  const wanted = selectNewest && result.projects.length ? result.projects[0].project_id : state.projectId;
  select.innerHTML = '<option value="">请选择本地项目</option>';
  for (const project of result.projects) {
    const option = document.createElement('option');
    option.value = project.project_id;
    option.textContent = `${project.title || project.source_name || '未命名'} · ${project.status} · ${project.project_id}`;
    select.append(option);
  }
  if (wanted) {
    select.value = wanted;
    await loadProject(wanted);
  }
}

async function loadProject(projectId) {
  if (!projectId) return;
  const payload = await api(`/api/project?id=${encodeURIComponent(projectId)}`);
  state.projectId = projectId;
  state.project = payload;
  $('#project-select').value = projectId;
  renderProject(payload);
}

function mediaUrl(relative) {
  return `/media/${encodeURIComponent(state.projectId)}/${relative.split('/').map(encodeURIComponent).join('/')}`;
}

function showReferencePreview(url, label) {
  const image = $('#reference-preview');
  image.src = url || '';
  image.classList.toggle('hidden', !url);
  $('#reference-status').textContent = label;
}

async function uploadSelectedReference(projectId) {
  const file = $('#reference-image').files[0];
  if (!file) return null;
  return api(
    `/api/project/reference-image?project_id=${encodeURIComponent(projectId)}&filename=${encodeURIComponent(file.name)}`,
    {method: 'POST', body: file},
  );
}

function renderProject(payload) {
  const project = payload.state;
  $('#project-path').textContent = payload.project_path;
  if (payload.reference_image) {
    showReferencePreview(
      mediaUrl(payload.reference_image),
      `当前项目参考图：${project.reference_image_name || payload.reference_image}`,
    );
  } else if (!$('#reference-image').files[0]) {
    showReferencePreview('', '当前项目没有参考图，将使用纯文字生成首帧。');
  }
  $('#analysis-panel').classList.remove('hidden');
  const workflowError = $('#workflow-error');
  const showWorkflowError = Boolean(project.error) && ['analysis_failed', 'planning_failed'].includes(project.status);
  workflowError.classList.toggle('hidden', !showWorkflowError);
  workflowError.textContent = showWorkflowError ? `上次操作失败：${project.error}` : '';
  const analysis = payload.story_analysis;
  $('#analysis-empty').classList.toggle('hidden', Boolean(analysis));
  $('#analysis-result').classList.toggle('hidden', !analysis);
  if (analysis) renderAnalysis(analysis);

  const plan = payload.story_plan;
  $('#plan-panel').classList.toggle('hidden', !plan);
  if (plan) {
    const version = `${project.project_id}:${project.updated_at}:${project.status}`;
    if (document.activeElement !== $('#plan-editor') && state.planVersion !== version) {
      $('#plan-editor').value = JSON.stringify(plan, null, 2);
      state.planVersion = version;
    }
  }

  const showProgress = ['rendering', 'render_failed', 'cancelled', 'succeeded'].includes(project.status) || payload.keyframes.length;
  $('#progress-panel').classList.toggle('hidden', !showProgress);
  if (showProgress) renderProgress(payload);
  $('#results-panel').classList.toggle('hidden', !payload.keyframes.length && !payload.final_video);
  renderResults(payload);
  const activelyRunning = payload.running;
  $('#cancel-generation').classList.toggle('hidden', !activelyRunning);
  $('#start-generation').textContent = ['render_failed', 'cancelled'].includes(project.status) || (project.status === 'rendering' && !activelyRunning)
    ? '继续未完成的生成' : '第二次确认：开始生成';
}

function renderAnalysis(analysis) {
  $('#analysis-title').textContent = analysis.title;
  $('#analysis-genre').textContent = analysis.genre;
  $('#analysis-synopsis').textContent = analysis.synopsis;
  $('#analysis-reason').textContent = `推荐理由：${analysis.rationale}`;
  const container = $('#duration-options');
  container.innerHTML = '';
  for (const option of analysis.options) {
    const node = document.createElement('article');
    node.className = `duration-option ${option.key === 'recommended' ? 'selected' : ''}`;
    node.dataset.seconds = option.seconds;
    node.innerHTML = `<strong>${option.label} · ${option.seconds} 秒</strong><small>${option.shot_count} 段视频 · 约 ${option.estimated_keyframes} 张关键帧 · 预计 ${option.estimated_render_minutes} 分钟</small><p>${option.description}</p>`;
    node.onclick = () => {
      document.querySelectorAll('.duration-option').forEach(item => item.classList.remove('selected'));
      node.classList.add('selected');
      $('#duration-seconds').value = option.seconds;
    };
    container.append(node);
  }
  const recommended = analysis.options.find(item => item.key === 'recommended') || analysis.options[0];
  if (!$('#duration-seconds').value && recommended) $('#duration-seconds').value = recommended.seconds;
}

function renderProgress(payload) {
  const project = payload.state;
  const progress = project.progress || {};
  const target = Number(progress.target_seconds || project.selected_duration_seconds || 0);
  const completed = Number(progress.completed_seconds || 0);
  const percent = project.status === 'succeeded' ? 100 : target ? Math.min(99, Math.round(completed / target * 100)) : 0;
  $('#progress-bar').style.width = `${percent}%`;
  $('#progress-percent').textContent = `${percent}%`;
  $('#progress-message').textContent = progress.message || project.status;
  const metrics = [];
  if (progress.total_shots) metrics.push(`镜头 ${progress.completed_shots || 0}/${progress.total_shots}`);
  if (target) metrics.push(`成片 ${completed}/${target} 秒`);
  metrics.push(`状态 ${project.status}`);
  $('#progress-metrics').innerHTML = metrics.map(value => `<span>${value}</span>`).join('');
  const warnings = project.warnings || [];
  $('#warnings').classList.toggle('hidden', !warnings.length && !project.error);
  $('#warnings').textContent = [...warnings, project.error].filter(Boolean).join('\n');
}

function renderResults(payload) {
  $('#keyframe-gallery').innerHTML = payload.keyframes.map((path, index) =>
    `<a href="${mediaUrl(path)}" target="_blank"><img loading="lazy" src="${mediaUrl(path)}" alt="关键帧 ${index + 1}"></a>`
  ).join('');
  $('#clip-list').innerHTML = payload.clips.map((path, index) =>
    `<a href="${mediaUrl(path)}" target="_blank">片段 ${index + 1}</a>`
  ).join('');
  $('#final-video').innerHTML = payload.final_video
    ? `<video controls preload="metadata" src="${mediaUrl(payload.final_video)}"></video>`
    : '<p class="hint">最终视频尚未完成，中间结果已经保存在本机。</p>';
}

$('#refresh-services').onclick = () => refreshServices().catch(() => {});
$('#project-select').onchange = event => loadProject(event.target.value).catch(error => toast(error.message, true));

$('#reference-image').onchange = event => {
  const file = event.target.files[0];
  if (localReferencePreviewUrl) URL.revokeObjectURL(localReferencePreviewUrl);
  localReferencePreviewUrl = file ? URL.createObjectURL(file) : null;
  showReferencePreview(
    localReferencePreviewUrl,
    file ? `已选择：${file.name}；创建项目时会自动保存，或点击按钮添加到当前项目。` : '尚未选择参考图。',
  );
};

$('#attach-reference').onclick = function () {
  return busy(this, async () => {
    if (!state.projectId) throw new Error('请先创建或选择一个本地项目');
    if (!$('#reference-image').files[0]) throw new Error('请先选择一张参考图片');
    const result = await uploadSelectedReference(state.projectId);
    state.project = result;
    renderProject(result);
    toast('参考图片已保存，并会参与新场景关键帧生成');
  }).catch(() => {});
};

$('#upload-story').onclick = function () {
  return busy(this, async () => {
    const file = $('#story-file').files[0];
    if (!file) throw new Error('请先选择故事文件');
    const result = await api(`/api/project/file?filename=${encodeURIComponent(file.name)}`, {method: 'POST', body: file});
    state.projectId = result.state.project_id;
    await uploadSelectedReference(state.projectId);
    await refreshProjects(true);
    toast('本地项目创建成功');
  }).catch(() => {});
};

$('#create-text').onclick = function () {
  return busy(this, async () => {
    const result = await jsonPost('/api/project/text', {text: $('#story-text').value, filename: 'story.md'});
    state.projectId = result.state.project_id;
    await uploadSelectedReference(state.projectId);
    await refreshProjects(true);
    toast('本地项目创建成功');
  }).catch(() => {});
};

function analyzeCurrentProject(button) {
  return busy(button, async () => {
    if (!state.projectId) throw new Error('请先创建或选择项目');
    const result = await jsonPost('/api/analyze', {
      project_id: state.projectId,
      lm_studio_url: $('#lm-url').value.trim(),
      model: $('#lm-model').value,
      output_language: 'Chinese',
    });
    state.project = result;
    renderProject(result);
    toast('故事分析完成，请选择时长');
  }).catch(() => {});
}

$('#analyze-story').onclick = function () { return analyzeCurrentProject(this); };
$('#reanalyze-story').onclick = function () { return analyzeCurrentProject(this); };

$('#create-plan').onclick = function () {
  return busy(this, async () => {
    const result = await jsonPost('/api/plan', {
      project_id: state.projectId,
      duration_seconds: Number($('#duration-seconds').value),
      aspect_ratio: $('#aspect-ratio').value,
      style: $('#visual-style').value,
      dialogue_mode: $('#dialogue-mode').value,
      lm_studio_url: $('#lm-url').value.trim(),
      model: $('#lm-model').value,
      output_language: 'Chinese',
    });
    state.project = result;
    state.planVersion = null;
    renderProject(result);
    toast('详细分镜已经生成；请检查后进行第二次确认');
  }).catch(() => {});
};

$('#save-plan').onclick = function () {
  return busy(this, async () => {
    const plan = JSON.parse($('#plan-editor').value);
    const result = await jsonPost('/api/save-plan', {project_id: state.projectId, plan});
    state.project = result;
    renderProject(result);
    toast('分镜已保存并通过严格校验');
  }).catch(() => {});
};

$('#start-generation').onclick = function () {
  return busy(this, async () => {
    if (!confirm('确认开始本地生成？30 秒视频实测约需 30 分钟。')) return;
    const plan = JSON.parse($('#plan-editor').value);
    await jsonPost('/api/save-plan', {project_id: state.projectId, plan});
    const result = await jsonPost('/api/generate', {
      project_id: state.projectId,
      comfyui_url: $('#comfy-url').value.trim(),
      base_seed: 1000,
    });
    state.project = result;
    renderProject(result);
    toast('ComfyUI 任务已经启动');
  }).catch(() => {});
};

$('#cancel-generation').onclick = function () {
  return busy(this, async () => {
    const result = await jsonPost('/api/cancel', {project_id: state.projectId});
    state.project = result;
    renderProject(result);
    toast('停止请求已记录，将在当前模型步骤后生效');
  }).catch(() => {});
};

$('#open-folder').onclick = function () {
  return busy(this, async () => {
    const result = await jsonPost('/api/open-folder', {project_id: state.projectId});
    toast(`已打开：${result.path}`);
  }).catch(() => {});
};

setInterval(() => {
  if (state.projectId) loadProject(state.projectId).catch(() => {});
}, 2000);

Promise.all([refreshProjects(), refreshServices()]).catch(error => toast(error.message, true));
