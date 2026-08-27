# Portable ComfyUI workflows

This directory contains the public workflow templates used by the bicycle
sequence demo. Model weights are not included.

## Formats

- `api/*.api.json` contains prompt/API graphs for Python or direct `/prompt`
  submission.
- `ui/*.workflow.json` contains the editable ComfyUI canvas, including layout,
  public model links, and example parameters.

The API files are consumed by `comfyui_py_workflow.image_sequence` and
`comfyui_py_workflow.video_sequence`. Open the UI files from ComfyUI's
**Workflows → Open** menu. For workflows with `LoadImage` nodes, upload the
matching bicycle assets first or choose your own input images.

All positive, negative, edit, and video prompt fields are intentionally empty
in both formats. The orchestrator injects prompts at runtime. Public bicycle
prompts live separately in `examples/bicycle-sequence/prompts.example.json`.

## Models

Place each file in the matching directory under `ComfyUI/models/`. The UI
workflows also contain public model download links.

### Z-Image Turbo

| Directory | File |
| --- | --- |
| `diffusion_models` | `z_image_turbo_bf16.safetensors` |
| `text_encoders` | `qwen_3_4b.safetensors` |
| `vae` | `ae.safetensors` |

### Qwen Image Edit 2509

| Directory | File |
| --- | --- |
| `diffusion_models` | `qwen_image_edit_2509_fp8_e4m3fn.safetensors` |
| `text_encoders` | `qwen_2.5_vl_7b_fp8_scaled.safetensors` |
| `vae` | `qwen_image_vae.safetensors` |
| `loras` | `Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors` |

### MiniMax H3 first/last-frame video

| Directory | File |
| --- | --- |
| `diffusion_models` | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` |
| `text_encoders` | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| `vae` | `minimax_h3_audio_vae_fp32.safetensors` |
| `vae` | `minimax_h3_video_vae_fp16.safetensors` |
| `loras` | `minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors` |

## Custom nodes and compatibility

The Z-Image and Qwen workflows use nodes shipped with a recent ComfyUI release.
The H3 workflow additionally uses:

- [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes) for
  `ImageResizeKJv2`.
- [rgthree-comfy](https://github.com/rgthree/rgthree-comfy) for the seed and
  label nodes.

The files were validated against ComfyUI 0.33.3. Newer or older releases may
rename nodes or expose different model variants.

## Privacy and portability

Public templates keep exact public model filenames because they are required
for reproduction. They contain no credentials, usernames, machine-specific
absolute paths, private source filenames, or generation prompts.

The adapted upstream template material retains its MIT notice; see
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).
