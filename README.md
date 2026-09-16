# comfyui-py-workflow

**English** | [简体中文](README.zh-CN.md)

Run, parameterize, and chain local ComfyUI API workflows from Python. The package includes a loopback-only **ComfyUI Workbench** for batch image editing and first/last-frame video generation.

The standalone Workbench is intentionally ComfyUI-only. Story video, story comic, document translation, and shared LM Studio settings live in the separate [Offline Studio](https://github.com/marsguo2049/offline-studio), which opens on port `7870`. The reusable story and comic Python engines remain available for compatible callers.

> This is an independent community project and is not affiliated with or endorsed by Comfy Org.

## ComfyUI Workbench

[![ComfyUI Workbench preview showing synthetic first/last-frame video pairs](docs/assets/comfyui-workbench-preview.svg)](https://marsguo2049.github.io/comfyui-py-workflow/#batch)

[Open the inert public preview](https://marsguo2049.github.io/comfyui-py-workflow/#batch). It uses synthetic filenames, disables uploads and task actions, and cannot contact a backend because its Content Security Policy sets `connect-src 'none'`.

The Workbench provides:

- batch Qwen Image Edit jobs with multi-file, folder, and drag-and-drop input;
- batch MiniMax H3 first/last-frame videos with natural-order or same-name pairing;
- pairing preview before uploads or inference;
- duration, aspect ratio, resolution, steps, seeds, timeout, and optional workflow overrides;
- persistent progress and job history, image downloads, and byte-range MP4 playback;
- one saved loopback ComfyUI address, with no LM Studio dependency.

## Quick start

Install the project and optional media support:

```powershell
python -m pip install -e ".[media]"
```

Start ComfyUI at `http://127.0.0.1:8188`, then double-click `start-local-ui.bat` or run:

```powershell
cpw-workbench
```

The Workbench opens at `http://127.0.0.1:7860/#batch`. Jobs are stored under:

```text
outputs/comfyui-workbench/batch-jobs/<job-id>/
```

Use `--output-root` to choose another batch-job root. Existing `outputs/offline-studio/` histories are left untouched and are not migrated automatically.

See [batch image editing](BATCH_IMAGE_EDIT_UI.zh-CN.md) and [first/last-frame video](BATCH_VIDEO.zh-CN.md) for detailed usage. Only edit media you own or are authorized to modify.

## Python workflows and CLI

The lower-level ComfyUI execution APIs and workflow examples remain part of this package:

```powershell
cpw-image-sequence --help
cpw-video-sequence --help
python examples/bicycle-sequence/run.py
```

The bicycle example builds three frames and two MiniMax H3 clips, then concatenates them into a ten-second MP4. Outputs are written below `outputs/` and ignored by Git. Use `--server` when ComfyUI listens on another loopback address.

Legacy story planning is also retained as a library/CLI workflow for existing users:

```powershell
cpw-story-video `
  --input examples/auto-story-video/story.example.md `
  --duration 20 `
  --model "YOUR-LM-STUDIO-MODEL-ID"
```

Review the generated plan before execution, then run:

```powershell
cpw-story-video --plan outputs/story-video/plans/PLAN-ID/story-plan.json --execute
```

This CLI accepts direct text plus TXT, Markdown, DOCX, and text-based PDF. Scanned PDFs require OCR. Its LM Studio URL is loopback-restricted by default. The browser UI for these creative workflows is maintained by [Offline Studio](https://github.com/marsguo2049/offline-studio).

## Workflows and models

See [workflows/README.md](workflows/README.md) for model filenames, directories, custom-node dependencies, and the distinction between API and UI workflow formats. The six committed workflow graphs contain empty generation prompts; public example prompts are injected at runtime. Model weights are never included.

## Repository layout

- `src/comfyui_py_workflow`: ComfyUI client, batch engines, reusable orchestration, and compatibility APIs.
- `src/comfyui_py_workflow/web`: ComfyUI-only Workbench shell and shared batch fragment.
- `workflows/api`: API graphs consumed by Python.
- `workflows/ui`: editable ComfyUI canvas exports.
- `examples`: runnable, sanitized examples.
- `docs`: privacy-safe static Workbench preview.
- `tests`: offline client, workflow, boundary, and privacy checks.

## Tests

```powershell
python -m pip install -e ".[dev,all]"
python -m pytest
python scripts/build_ui_preview.py --check
```

## License

Unless a file states otherwise, original repository content is provided under the **PolyForm Noncommercial License 1.0.0**. See [LICENSE](LICENSE). Commercial use requires separate written permission. Adapted Comfy Org workflow templates retain their MIT notice; models, custom nodes, ComfyUI, and other third-party components retain their own licenses. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
