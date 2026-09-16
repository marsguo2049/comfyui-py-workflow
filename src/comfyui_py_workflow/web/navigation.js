// Workspace navigation and batch jobs share the existing local API helpers.
const views = {
  story: ['STORY TO VIDEO', '把故事，变成画面。', '从一个想法开始，在本机完成分镜与视频。'],
  comic: ['STORY TO COMIC', '让故事，一格格展开。', '从文字到连续画面，在本机完成你的漫画。'],
  batch: ['BATCH TOOLS', '一次设定，批量完成。', '批量修改图片，或用首尾帧生成视频。'],
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
