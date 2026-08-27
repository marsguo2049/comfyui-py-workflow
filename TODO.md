# TODO

## Headless local text-generation backend

Goal: let Offline Story Studio analyze stories and generate structured storyboards without requiring the user to open the LM Studio window.

- Add a selectable text backend: `LM Studio API`, `LM Studio headless`, and later `llama.cpp`.
- Detect the installed local `lms` CLI without assuming a user-specific absolute path.
- For headless LM Studio, automate the lifecycle: start local-only server, load the selected GGUF model, wait for health, generate analysis and storyboard, unload all text-model instances, then stop the service when this application started it.
- Bind only to `127.0.0.1`; never enable LAN access or CORS by default.
- Show explicit UI stages for service startup, model loading, text generation, unloading, and handoff to ComfyUI.
- Preserve the current manual-server mode for users who already run LM Studio themselves.
- Add a standalone `llama.cpp` adapter only after validating the Qwen chat template, JSON Schema output, CUDA build, context length, cancellation, and clean process shutdown.
- Verify on a resource-constrained local target that the text model is fully released before ComfyUI loads Qwen Image Edit or MiniMax H3.
- Add offline tests for executable discovery, loopback enforcement, failed startup, timeout, unload/stop ownership, and backend fallback.

## Multiple visual references

- Prefer a trusted ComfyUI workflow with native multi-image conditioning.
- If only two-image input is available, evaluate iterative composition as a compatibility mode and measure identity drift, detail loss, and aspect-ratio behavior before enabling it.
- Keep the current single-reference workflow as the stable default.
