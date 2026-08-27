# Automatic story-video planning

This example turns a short Markdown story into a reviewable structured plan by
calling a model served locally by LM Studio. It does not contact a hosted AI API.

Start the LM Studio server, then run:

```powershell
cpw-story-video --input examples/auto-story-video/story.example.md --duration 20 --model "YOUR-LM-STUDIO-MODEL-ID"
```

The default is plan-only mode. Inspect the generated `story-plan.json` under
`outputs/story-video/plans/`, edit prompts if needed, then close LM Studio (or
unload its model), start ComfyUI, and execute:

```powershell
cpw-story-video --plan outputs/story-video/plans/PLAN-ID/story-plan.json --execute
```

TXT, Markdown, DOCX, and text-based PDF inputs are supported. Scanned PDFs need
OCR before they can be planned by a text-only model.

To skip LM Studio entirely, use the explicitly public example plan (or write a
plan with the same schema), start ComfyUI, and run:

```powershell
cpw-story-video --plan examples/auto-story-video/story-plan.example.json --execute
```
