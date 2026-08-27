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

安装项目和媒体处理依赖：

```powershell
python -m pip install -e ".[media]"
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
- `tests`：离线客户端、工作流与隐私检查。

## 测试

```powershell
python -m pip install -e ".[dev,media]"
python -m pytest
```

## 许可证

除非文件另有说明，本仓库原创内容采用 **PolyForm Noncommercial License 1.0.0**。详见 [LICENSE](LICENSE)。

该许可证覆盖的非商业用途可以使用。**商业使用需要事先取得作者的单独书面许可。**

改编自 Comfy Org 的工作流模板保留其 MIT 声明。模型、自定义节点、ComfyUI 本身和其他第三方组件继续使用各自许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
