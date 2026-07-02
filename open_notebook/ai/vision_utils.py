"""Vision-model provisioning helpers.

Builds multimodal ``HumanMessage``s (text + inlined page-image data-URIs) for
vision-capable chat models. Reuses the exact same block-building pattern as
``open_notebook.graphs.chat._attach_media_blocks`` (imported, not duplicated)
so chat attachments and document-pipeline vision calls (Track B: verify-clean,
see .claude/plans/document-foundation/b-pipeline.md Chunk B1/B2) share one
code path for turning bytes into ``{"type": "image_url", ...}`` content
blocks.
"""

import base64
from typing import List

from langchain_core.messages import HumanMessage

from open_notebook.graphs.chat import _attach_media_blocks


async def provision_vision_message(
    page_images: List[bytes],
    text_prompt: str,
    mime_type: str = "image/png",
) -> HumanMessage:
    """Build a HumanMessage with text + page-image data-URIs.

    Args:
        page_images: Raw image bytes for each page (e.g. PyMuPDF
            ``doc.get_pixmap(page=N).tobytes("png")``), in the order they
            should appear to the model.
        text_prompt: The instruction/question to accompany the images.
        mime_type: MIME type for the inlined images (default ``image/png``).

    Returns:
        A ``HumanMessage`` whose ``content`` is already a list of
        ``{"type": "text", ...}`` / ``{"type": "image_url", ...}`` blocks,
        ready to hand to a vision-capable ``BaseChatModel`` (e.g. via
        ``model.ainvoke([...])``).
    """
    media = [
        {
            "type": "image",
            "data_uri": (
                f"data:{mime_type};base64,"
                f"{base64.b64encode(image_bytes).decode('ascii')}"
            ),
        }
        for image_bytes in page_images
    ]
    draft_message = HumanMessage(
        content=text_prompt,
        additional_kwargs={"media": media},
    )
    # Reuses graphs/chat.py's block-building logic verbatim (DRY) — this is
    # the same function the chat graph uses to inline attached images.
    attached = _attach_media_blocks([draft_message])
    return attached[0]
