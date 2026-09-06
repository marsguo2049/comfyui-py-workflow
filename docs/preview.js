// Presentation only. Never import the real app scripts or contact a backend.
const $ = selector => document.querySelector(selector);
const views = {
  comic: ['STORY TO COMIC', '让故事，一格格展开。', '从文字到连续画面，在本机完成你的漫画。'],
  story: ['STORY TO VIDEO', '把故事，变成画面。', '从一个想法开始，在本机完成分镜与视频。'],
  batch: ['BATCH TOOLS', '一次设定，批量完成。', '重复的图片处理，交给本地工作流。'],
  settings: ['LOCAL SERVICES', '连接你的创作引擎。', '统一管理本机服务，供各个工作区使用。'],
};
let storyStage = 'input';
const storyStages = ['input', 'plan', 'output'];
function switchStoryStage(stage) {
  storyStage = storyStages.includes(stage) ? stage : 'input';
  for (const key of storyStages) {
    const selected = key === storyStage;
    $(`#story-stage-${key}`).classList.toggle('hidden', !selected);
    const tab = $(`#story-tab-${key}`);
    tab.classList.toggle('active', selected);
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
  }
}
function switchView(name, stage = storyStage) {
  if (!views[name]) name = 'batch';
  for (const key of Object.keys(views)) $(`#view-${key}`).classList.toggle('hidden', key !== name);
  document.querySelectorAll('[data-view]').forEach(button => {
    const selected = button.dataset.view === name;
    button.classList.toggle('active', selected);
    if (selected) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  ['eyebrow', 'title', 'subtitle'].forEach((key, index) => $(`#view-${key}`).textContent = views[name][index]);
  if (name === 'story') switchStoryStage(stage);
  history.replaceState(null, '', name === 'story' ? `#story/${storyStage}` : `#${name}`);
}
document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => switchView(button.dataset.view));
$('#go-settings').onclick = () => switchView('settings');
function showRoute() {
  const [view, stage] = location.hash.slice(1).split('/');
  switchView(view, stage || storyStage);
}
window.addEventListener('hashchange', showRoute);
document.querySelectorAll('[data-story-stage]').forEach((button, index) => {
  button.onclick = () => switchView('story', button.dataset.storyStage);
  button.onkeydown = event => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % storyStages.length;
    else if (event.key === 'ArrowLeft') next = (index + storyStages.length - 1) % storyStages.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = storyStages.length - 1;
    else return;
    event.preventDefault();
    switchView('story', storyStages[next]);
    $(`#story-tab-${storyStages[next]}`).focus();
  };
});
for (const eventName of ['dragover', 'drop']) window.addEventListener(eventName, event => event.preventDefault());

$('#story-text').value = '一名信使在暴雨前把一封信送到港口，一位钟表匠已在那里等候多年。\n\n（公开虚构示例）';
$('#project-select').options[0].textContent = '港口的来信 · 公开虚构示例';
$('#analysis-title').textContent = '港口的来信';
$('#analysis-genre').textContent = '都市奇遇 / 氛围短片';
$('#analysis-synopsis').textContent = '信使接过一封旧信，穿过即将落雨的街道，在港口将信交给等候多年的钟表匠。';
$('#analysis-reason').textContent = '示例分析：用 30 秒呈现接信、穿城、抵达和交付，留出情绪收尾。以下内容为展示用编写，并非实时模型输出。';
for (const [label, seconds, description] of [
  ['精简版', 20, '4 段视频 · 保留核心事件'],
  ['推荐版', 30, '6 段视频 · 补充场景与情绪'],
  ['完整版', 45, '9 段视频 · 展开环境与人物反应'],
]) {
  const card = document.createElement('article');
  card.className = `duration-option ${seconds === 30 ? 'selected' : ''}`;
  const title = document.createElement('strong'); title.textContent = `${label} · ${seconds} 秒`;
  const detail = document.createElement('p'); detail.textContent = description;
  card.append(title, detail); $('#duration-options').append(card);
}
$('#duration-seconds').value = 30;
$('#visual-style').value = '雨前港城，写实电影感，统一信使外观与服装';
const sampleShots = [
  ['接信', '近景：信使接过一封泛黄的旧信。'],
  ['雨巷', '中景：信使沿狭窄街道快步前行，乌云渐近。'],
  ['穿城', '全景：信使穿过即将收摊的集市。'],
  ['抵达', '远景：港口钟表店的灯光在暮色中亮起。'],
  ['交付', '近景：钟表匠接过信件，认出熟悉的字迹。'],
  ['回响', '特写：怀表指针继续转动，两人安静相望。'],
];
$('#plan-editor').value = JSON.stringify({
  note: '公开虚构分镜摘要，用于展示流程；不是可直接导入的执行计划。',
  title: '港口的来信', duration_seconds: 30,
  shots: sampleShots.map(([title, description], index) => ({shot: index + 1, duration_seconds: 5, title, description})),
}, null, 2);
$('#progress-panel').classList.add('preview-complete');
$('#progress-percent').textContent = '100%';
$('#progress-message').textContent = '公开单车示例已完成 · 3 张关键帧 / 2 段视频 / 10 秒成片';
$('#progress-metrics').textContent = '此处展示已公开的独立样片，未启动任何本地生成任务。';
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
// Fixed public demonstration data; no local comic records or API calls.
$('#comic-story').value = '一位骑手离开小镇，沿着乡间公路骑行，在山脚停下看日落。\n\n（公开虚构故事；下方使用仓库已有单车样图演示排版。）';
$('#comic-count').value = 3;
$('#comic-aspect').value = '16:9';
$('#comic-style').value = '清晰线条，柔和色彩，乡间旅行漫画';
$('#comic-title').value = '骑向黄昏';
$('#comic-bible').value = '同一位骑手与同一辆单车；保持头盔、服装和车架颜色一致。';
$('#comic-plan-style').value = $('#comic-style').value;
$('#comic-negative').value = '文字、水印、多格拼贴、人物重复';
$('#comic-plan-panel').classList.remove('hidden');
$('#comic-status').textContent = '公开示例';
$('#comic-message').textContent = '分镜为虚构示例；图片是已有公开样图，并非本次漫画模型生成结果。';
$('#comic-metrics').textContent = '3 格排版示例';
$('#comic-results').replaceChildren();
$('#comic-history').textContent = '公开预览不读取本机漫画历史。';
$('#comic-exports').textContent = '本地生成后可下载独立 HTML 阅读页，以及包含图片和分镜的 ZIP。';
for (const [index, description, prompt, caption, dialogue] of [
  [1, '骑手从小镇出发。', 'Single comic panel, a cyclist leaving a quiet town, soft morning light.', '天刚亮，他就出发了。', '骑手：今天，去看看山的另一边。'],
  [2, '沿公路继续前进，保持人物与单车一致。', 'Keep the same cyclist and bicycle, riding along a country road, side view.', '公路渐渐安静下来。', ''],
  [3, '来到山脚，停车欣赏远景。', 'Keep the same cyclist and bicycle, stopped near the hills at sunset.', '有时候，抵达只需要停下来。', '骑手：这里就很好。'],
]) {
  const card = document.createElement('article'); card.className = 'comic-panel-editor';
  const title = document.createElement('h3'); title.textContent = `第 ${index} 格`; card.append(title);
  for (const [name, value] of [['这一格发生什么', description], ['画面提示词', prompt], ['旁白', caption], ['对白', dialogue]]) {
    const label = document.createElement('label'); label.textContent = name;
    const input = document.createElement('textarea'); input.disabled = true; input.rows = 2; input.value = value; label.append(input); card.append(label);
  }
  const reference = document.createElement('p'); reference.className = 'hint'; reference.textContent = index === 1 ? '首格：根据文字生成' : '画面参考：上一格';
  card.append(reference); $('#comic-panels').append(card);
  const figure = document.createElement('figure'); figure.className = 'comic-frame';
  const img = document.createElement('img'); img.src = `assets/bicycle-frame-000${index}.png`; img.alt = `公开单车样图 ${index}，用于排版展示`; img.loading = 'lazy';
  const text = document.createElement('figcaption');
  const heading = document.createElement('strong'); heading.textContent = `第 ${index} 格 · 排版示例`; text.append(heading);
  for (const [field, value] of [['caption', caption], ['dialogue', dialogue]]) {
    const paragraph = document.createElement('p'); paragraph.className = `comic-${field}`; paragraph.textContent = value; text.append(paragraph);
  }
  figure.append(img, text); $('#comic-results').append(figure);
}
showRoute();
