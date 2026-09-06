# Offline Studio 批量图片编辑

批量图片编辑已整合到 Offline Studio 的“批量工具”工作区，与故事视频共用服务设置。多张图片使用相同的修改提示词，由本机 ComfyUI 逐张处理。

## 启动

1. 启动 ComfyUI，准备 Qwen Image Edit 2509 工作流所需模型与节点。
2. 双击 `start-local-ui.bat`，选择“批量工具”；也可以双击 `start-batch-image-edit-ui.bat` 直接打开该工作区。
3. 默认地址为 `http://127.0.0.1:7860/#batch`。若 Studio 已运行，直接在已有页面切换，无需再次启动。

终端入口：

```powershell
.venv\Scripts\python.exe -m comfyui_py_workflow.local_ui --view batch
```

本项目需已安装到本地环境：`.venv\Scripts\python.exe -m pip install -e .`。网页批量工具不依赖 Tk，也不需要启动 LM Studio。

## 使用

1. 选择多张图片、选择文件夹（包含子文件夹），或拖入图片文件。开始前可以移除单张图片或清空选择。
2. 填写统一修改要求，例如“把背景替换为浅灰色摄影棚，保留主体和自然阴影”。
3. 如有需要，展开“高级参数”设置负向提示词、种子、单张超时或自定义工作流路径。路径指运行 Studio 的电脑上的文件，需与现有 Qwen 节点兼容。
4. 点击“开始批量处理”。图片先复制到本机任务目录，再逐张提交给 ComfyUI。
5. 查看成功、失败和处理数量。每张完成后可以查看原图、查看结果或下载；也可打开任务文件夹。

支持 PNG、JPEG、WebP、BMP、GIF、TIFF。最多 200 张，单张不超过 25 MB，合计不超过 500 MB。上传会检查图片文件头，完整解码由 ComfyUI 负责；文件夹中的非图片会跳过。

点击“当前图片后停止”会保留正在处理图片的结果，然后停止后续图片；不会强行中断 ComfyUI。单张失败会继续下一张，连接或工作流初始化失败会停止任务并显示原因。

## 任务与文件

默认目录：

```text
outputs/offline-studio/batch-jobs/<任务编号>/
  input/       上传的图片副本
  output/      编辑结果
  job.json     参数、状态、每张结果及错误
```

每个任务使用独立目录，原始图片不被修改，重名图片也不会覆盖彼此。使用 `--project-root` 时，批量任务位于指定目录下的 `batch-jobs/`。

关闭浏览器不会停止后台任务。重新打开页面后，点击“最近任务”恢复查看；该列表显示最近 20 个任务。关闭或重启 Python 服务后，未完成任务会标为“已中断”，已完成结果保留。当前版本不自动重跑失败或中断的图片，请新建任务添加这些图片。

同时只允许运行一个网页批量任务。故事视频和旧桌面工具各自提交任务，如同时使用会进入同一个 ComfyUI 队列。

页面适配窄屏和触控操作，但服务仍只允许本机回环地址，不开放局域网或公网访问。上传内容、提示词和结果均保存在被 Git 忽略的 `outputs/` 中；自定义输出根目录请自行保持在忽略范围内。

## 旧桌面界面

原 Tk 界面仍保留，适用于需要直接指定源文件路径和输出目录的桌面操作：

```powershell
.venv\Scripts\python.exe -m comfyui_py_workflow.batch_edit_ui
```

`cpw-batch-image-edit-ui` 也仍指向该旧桌面界面。启动脚本的 `--diagnose` 现在检查统一网页工作台的 Python 导入。

## 添加其他批量功能

`batch_studio.py` 管理任务持久化、上传、状态与结果；`local_ui.py` 提供 HTTP 接口，`web/batch.js` 管理网页交互。现有图像编辑执行器继续复用 `QwenBatchImageEditor`。新增工具需要注册工具描述，并增加相应的参数校验、执行器与表单；不需要再单独创建窗口和启动服务。
