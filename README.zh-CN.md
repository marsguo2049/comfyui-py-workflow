# comfyui-py-workflow

[English](README.md) | **简体中文**

用 Python 直接运行、修改参数并串联本地 ComfyUI API 工作流。

本仓库关注的是执行基础设施，而不是模型路由研究：读取导出的 API 图，替换指定节点输入，提交到 ComfyUI，等待完成，下载结果，再把一个工作流的输出交给下一个工作流。

> 这是一个独立的社区项目，与 Comfy Org 没有隶属或官方认可关系。

## 包含内容

- 基于 Python 标准库的小型本地 ComfyUI HTTP 客户端。
- 图片上传、任务提交、运行历史轮询、输出识别和文件下载。
- 两帧图片链：Z-Image Turbo → Qwen Image Edit 2509。
- 三帧视频链：Qwen 生成第 3 帧 → MiniMax H3 生成两段首尾帧视频 → 拼接为 10 秒 MP4。
- 用于脚本自动化的 API 工作流和用于可视化编辑的 UI 工作流。
- 真实单车示例、清除隐藏元数据的预览帧和最终视频。
- 使用本地 LM Studio 从文本、Markdown、DOCX 和文本型 PDF 生成分镜。
- 动态镜头数量、模型专用提示词，以及先审阅再执行的安全模式。

## 处理流程

```text
Z-Image 生成第 1 帧
  -> Qwen Image Edit 生成第 2 帧
  -> Qwen Image Edit 生成第 3 帧
  -> MiniMax H3 生成片段 1（第 1 帧到第 2 帧）
  -> MiniMax H3 生成片段 2（第 2 帧到第 3 帧）
  -> 裁切并拼接为一段 10 秒 MP4
```

## 快速开始

安装项目、文档和媒体处理依赖：

```powershell
python -m pip install -e ".[all]"
```

在 `http://127.0.0.1:8188` 启动 ComfyUI，安装文档列出的模型和自定义节点，然后运行完整示例：

```powershell
python examples/bicycle-sequence/run.py
```

结果写入 `outputs/`，Git 不会跟踪它们。如果 ComfyUI 地址不同，可以通过 `--server` 指定。

也可以分别调用底层命令：

```powershell
cpw-image-sequence --help
cpw-video-sequence --help
```

## 自动从故事生成视频计划

启动 LM Studio 本地服务后，先只生成计划，不运行耗时的图片和视频模型：

```powershell
cpw-story-video `
  --input examples/auto-story-video/story.example.md `
  --duration 20 `
  --model "你的-LM-STUDIO-模型-ID"
```

LM Studio 会返回受 JSON Schema 约束的计划。Python 根据目标时间严格确定镜头数量和每段时长；本地模型负责选择情节节点、连续转场或切镜、统一视觉设定，并分别编写 Z-Image、Qwen Image Edit 和 MiniMax H3 提示词。计划默认保存在 `outputs/story-video/plans/`，方便生成媒体前人工检查。

检查或修改计划后，启动 ComfyUI 并执行：

```powershell
cpw-story-video --plan outputs/story-video/plans/计划编号/story-plan.json --execute
```

对于显存有限的电脑，推荐使用这两条命令：生成计划后关闭 LM Studio 或卸载其中的模型，再启动 ComfyUI。如果同一条命令同时使用故事输入和 `--execute`，CLI 会先通过本地 API 卸载 LM Studio 模型，再连接 ComfyUI。只有显式指定 `--keep-lm-loaded` 才会保留模型；12GB 显存不推荐这样做。

短故事可以用 `--story` 直接输入；TXT、Markdown、DOCX 和文本型 PDF 使用 `--input`。长文档会先在本地分块摘要，再进行分镜。扫描版 PDF 必须先 OCR，因为当前流程传给 LM Studio 的是提取文本，而不是页面图片。LM Studio 地址默认限制为本机回环地址，避免误把文档发送到远程服务器。完整说明见[自动故事视频示例](examples/auto-story-video/README.md)。

纯 ComfyUI 可以执行已经存在的 `story-plan.json`，包括人工编写或修改的计划；但扩散模型使用的文本编码器不是通用对话大模型，不能可靠代替 LM Studio 完成长文理解和结构化分镜。通过 ComfyUI custom node 再加载一个完整 LLM，通常仍会消耗相近的模型内存，并增加依赖复杂度。

如果想完全跳过 LM Studio，可以直接用明确标注为公开内容的 [`story-plan.example.json`](examples/auto-story-video/story-plan.example.json) 配合 `--execute` 演示，也可以按照相同结构人工编写计划。

## 工作流与模型

[workflows/README.md](workflows/README.md) 列出了准确的模型文件名、存放目录、自定义节点依赖，以及 API/UI 两种格式的区别。

提交到仓库的六份工作流中，所有生成提示词字段都为空。公开示例提示词明确保存在 [`prompts.example.json`](examples/bicycle-sequence/prompts.example.json)，由脚本在运行时注入。仓库不会包含模型权重。

## 示例结果

[单车序列](examples/bicycle-sequence/README.md)提供三个关键帧和最终 MP4。公开 PNG 不包含 ComfyUI 提示词或工作流隐藏元数据。

## 与工作流优化研究的关系

[`multi-model-workflow-optimization`](https://github.com/marsguo2049/multi-model-workflow-optimization) 研究模型选择、路由、评估、成本、时延和资源约束下的工作流优化。本仓库是研究系统可以调用的具体 ComfyUI 执行后端，不包含优化研究本身。

## 仓库结构

- `src/comfyui_py_workflow`：客户端和可复用 Python 编排。
- `workflows/api`：Python 使用的 API 图。
- `workflows/ui`：可编辑的 ComfyUI 画布工作流。
- `examples/bicycle-sequence`：可运行示例和脱敏媒体。
- `examples/auto-story-video`：本地 LM Studio 自动分镜示例。
- `tests`：离线客户端、工作流与隐私检查。

## 测试

```powershell
python -m pip install -e ".[dev,all]"
python -m pytest
```

## 许可证

除非文件另有说明，本仓库原创内容采用 **PolyForm Noncommercial License 1.0.0**。详见 [LICENSE](LICENSE)。

该许可证覆盖的非商业用途可以使用。**商业使用需要事先取得作者的单独书面许可。**

改编自 Comfy Org 的工作流模板保留其 MIT 声明。模型、自定义节点、ComfyUI 本身和其他第三方组件继续使用各自许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
