from typing import TYPE_CHECKING, Any

from .client import (
    ComfyUIAsset,
    ComfyUIClient,
    ComfyUIError,
    ComfyUIExecutionError,
    load_workflow_template,
)

if TYPE_CHECKING:
    from .image_sequence import GeneratedFrame, TwoFrameImageSequence

__all__ = [
    "ComfyUIAsset",
    "ComfyUIClient",
    "ComfyUIError",
    "ComfyUIExecutionError",
    "GeneratedFrame",
    "TwoFrameImageSequence",
    "load_workflow_template",
]


def __getattr__(name: str) -> Any:
    if name in {"GeneratedFrame", "TwoFrameImageSequence"}:
        from .image_sequence import GeneratedFrame, TwoFrameImageSequence

        return {
            "GeneratedFrame": GeneratedFrame,
            "TwoFrameImageSequence": TwoFrameImageSequence,
        }[name]
    raise AttributeError(name)
