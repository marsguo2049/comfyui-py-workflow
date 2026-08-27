# Bicycle sequence

This real local example combines three ComfyUI workflows:

1. Z-Image Turbo generates the first keyframe.
2. Qwen Image Edit 2509 transforms frame 1 into frame 2, then frame 2 into
   frame 3.
3. MiniMax H3 generates a five-second first/last-frame clip for each adjacent
   pair. Python trims and concatenates the two clips into a ten-second result
   while preserving the encoded video and audio streams.

## Result

| Frame 1 | Frame 2 | Frame 3 |
| --- | --- | --- |
| ![Red bicycle](assets/bicycle-frame-0001.png) | ![Bicycle with sunflower basket](assets/bicycle-frame-0002.png) | ![Bicycle at sunset with drifting petals](assets/bicycle-frame-0003.png) |

[Download or view the final ten-second MP4](assets/bicycle-final-10s.mp4).

The public PNG files were re-encoded without ComfyUI prompt/workflow metadata.
The editable workflows and dependencies are documented in
[`workflows/`](../../workflows/README.md).

## Run it

Start ComfyUI locally, install the listed models and custom nodes, then install
this project with its media dependency:

```powershell
python -m pip install -e ".[media]"
python examples/bicycle-sequence/run.py
```

The script checks `http://127.0.0.1:8188` by default. Use `--server` to select a
different endpoint. Outputs are written below `outputs/bicycle-sequence/` and
remain untracked.

Prompts, seeds, dimensions, and clip duration are in
[`prompts.example.json`](prompts.example.json). Generative output can vary
across ComfyUI, PyTorch, driver, model, and custom-node versions even with the
same seed.
