"""Background chat-illustration enrichment command (auto-illustrate-chat, W1).

Submitted fire-and-forget by ``chat_completion_command`` after a notebook chat
turn (frozen contract #6 v2). Runs the two-stage gate and, for the diagram path,
generates a Mermaid block and writes the ``chat_message_media`` sidecar row the
session read hydrates (B5).

This is a **silent progressive-enhancement** job: it must never fail loudly. The
handler always returns ``success=True`` (mode reports the outcome), so the job is
never marked ``failed`` and the frontend shows no error toast (F3). All heavy
lifting — and all defensive error handling — lives in
``open_notebook.graphs.illustrate``.
"""

import time
from typing import Optional

from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command

from open_notebook.graphs.illustrate import illustrate


class IllustrateInput(CommandInput):
    session_id: str
    message_id: str
    notebook_id: str
    model_id: Optional[str] = None
    label: str = ""  # short display label for the background-jobs tray


class IllustrateOutput(CommandOutput):
    success: bool
    mode: str
    message_id: str
    error_message: Optional[str] = None
    processing_time: float


@command("illustrate_message", app="open_notebook", retry={"max_attempts": 1})
async def illustrate_message_command(input_data: IllustrateInput) -> IllustrateOutput:
    """Enrich one AI chat message with a diagram (W1) — never raises."""
    start_time = time.time()
    mode = "none"
    error_message: Optional[str] = None
    try:
        mode = await illustrate(
            session_id=input_data.session_id,
            message_id=input_data.message_id,
            notebook_id=input_data.notebook_id,
            model_id=input_data.model_id,
        )
    except Exception as e:
        # ``illustrate`` already swallows its own failures, but keep this net so a
        # background enhancement can never mark itself failed / crash the worker.
        error_message = str(e)
        logger.warning(
            f"illustrate_message degraded to none for {input_data.message_id}: {e}"
        )
        mode = "none"

    processing_time = time.time() - start_time
    logger.info(
        f"illustrate_message done for {input_data.message_id}: "
        f"mode={mode} in {processing_time:.2f}s"
    )
    return IllustrateOutput(
        success=True,
        mode=mode,
        message_id=input_data.message_id,
        error_message=error_message,
        processing_time=processing_time,
    )
