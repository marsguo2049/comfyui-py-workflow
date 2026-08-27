# comfyui-py-workflow

**English** | [简体中文](README.zh-CN.md)

Run, parameterize, and chain local ComfyUI API workflows from Python.

This repository focuses on execution infrastructure rather than model-routing research: load an exported API graph, replace explicit node inputs, submit it to ComfyUI, wait for completion, download artifacts, and feed one workflow's output into the next.

> This is an independent community project and is not affiliated with or endorsed by Comfy Org.

## What it includes

- A small standard-library HTTP client for local ComfyUI.
- Image upload, prompt submission, history polling, output discovery, and artifact download.
- A two-frame chain: Z-Image Turbo → Qwen Image Edit 2509.
- A three-frame video chain: Qwen frame 3 → two MiniMax H3 first/last-frame clips → one ten-second MP4.
- API-format graphs for automation and UI-format graphs for visual editing.
- A real bicycle example with metadata-clean preview frames and final video.

## Pipeline

```text
Z-Image frame 1
  -> Qwen Image Edit frame 2
  -> Qwen Image Edit frame 3
  -> MiniMax H3 clip 1 (frame 1 to frame 2)
  -> MiniMax H3 clip 2 (frame 2 to frame 3)
  -> trim and concatenate into one ten-second MP4
```

## Quick start

Install the project and the optional media dependency:

```powershell
python -m pip install -e ".[media]"
```

Start ComfyUI at `http://127.0.0.1:8188`, install the documented models and custom nodes, then run the complete public example:

```powershell
python examples/bicycle-sequence/run.py
```

Outputs are written below `outputs/` and are ignored by Git. Use `--server` if ComfyUI is listening at a different address.

The lower-level commands are also available:

```powershell
cpw-image-sequence --help
cpw-video-sequence --help
```

## Workflows and models

See [workflows/README.md](workflows/README.md) for exact model filenames, directories, custom-node dependencies, and the difference between API and UI formats.

All generation prompt fields in the six committed workflow files are empty. Example prompts are stored explicitly in [`prompts.example.json`](examples/bicycle-sequence/prompts.example.json) and are injected at runtime. Model weights are never included.

## Example result

The [bicycle sequence](examples/bicycle-sequence/README.md) contains three keyframes and the final MP4. The public PNGs have no embedded ComfyUI prompt or workflow metadata.

## Relationship to workflow research

[`multi-model-workflow-optimization`](https://github.com/marsguo2049/multi-model-workflow-optimization) studies model selection, routing, evaluation, cost, latency, and resource-aware workflow optimization. This repository is a concrete ComfyUI execution backend that research systems can call; it does not contain the optimization research itself.

## Repository layout

- `src/comfyui_py_workflow`: client and reusable Python orchestration.
- `workflows/api`: prompt/API graphs consumed by Python.
- `workflows/ui`: editable ComfyUI canvas exports.
- `examples/bicycle-sequence`: runnable example and sanitized media.
- `tests`: offline client, workflow, and privacy checks.

## Tests

```powershell
python -m pip install -e ".[dev,media]"
python -m pytest
```

## License

Unless a file states otherwise, original repository content is provided under the **PolyForm Noncommercial License 1.0.0**. See [LICENSE](LICENSE).

Noncommercial use covered by that license is permitted. **Commercial use requires separate written permission from the author.**

The adapted Comfy Org workflow templates retain their MIT notice. Models, custom nodes, ComfyUI itself, and other third-party components retain their own licenses. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
