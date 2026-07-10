"""Study-memory substrate commands (Track A, Chunk A2).

Two async jobs that turn a learner's study traces into embedded, queryable
memory rows (coordinator decision 6/8/11):

- ``embed_annotation``: embeds a ``SourceAnnotation``'s searchable text
  (quote/note/tags). Submitted by ``SourceAnnotation.save()`` whenever the
  highlight carries text; re-runs on every edit so edits re-embed.
- ``mirror_chat_exchange``: turns one completed chat turn into a
  ``ChatExchange`` row — a short LLM-distilled gist, then an embedding over
  question+gist. Submitted fire-and-forget by ``chat_completion_command``
  after each turn (Chunk A3). A gist failure must never lose the exchange:
  on any gist error, or a gist that fails the output-sanity guard (empty or
  over the char bound), the command falls back to a truncated slice of the
  raw answer and still creates + embeds the row (to-fix/004 lesson: never
  let a model hiccup silently drop data).

Both commands copy the shapes already established in
``commands/embedding_commands.py`` (``embed_note_command``: decorator/retry,
input/output models, ``get_command_id``, the ``repo_query`` UPDATE
write-back, the ValueError-vs-raise error split) and
``commands/summary_commands.py`` (the one-shot gist pattern: provision +
reasoning-off + ``heavy_lane_for`` + progress + output extraction).
"""

import time
from typing import List, Optional, Tuple

from langchain_core.messages import HumanMessage
from loguru import logger
from pydantic import Field
from surreal_commands import CommandInput, CommandOutput, command

from commands._heavy_lane import heavy_lane_for
from commands.embedding_commands import get_command_id
from open_notebook.ai.models import model_manager
from open_notebook.ai.provision import apply_reasoning_flag, provision_langchain_model
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import ChatExchange, SourceAnnotation
from open_notebook.exceptions import ConfigurationError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.chunking import ContentType
from open_notebook.utils.embedding import generate_embedding
from open_notebook.utils.job_progress import report_job_progress
from open_notebook.utils.text_utils import extract_text_content

# Standard retry shape shared by every command in this module — copied from
# embedding_commands.embed_note_command.
_STANDARD_RETRY = {
    "max_attempts": 5,
    "wait_strategy": "exponential_jitter",
    "wait_min": 1,
    "wait_max": 60,
    "stop_on": [
        ValueError,
        ConfigurationError,
    ],  # Don't retry validation/config errors
    "retry_log_level": "debug",
}

# Gist output-sanity guard (coordinator decision 8, to-fix/004 lesson): a
# gist that is empty or implausibly long is treated as a model failure, not
# trusted content.
_GIST_MAX_CHARS = 700
_GIST_FALLBACK_CHARS = 400
_QUESTION_MAX_CHARS = 2000

_GIST_INSTRUCTION = (
    "Distill the assistant's answer into 2-3 sentences capturing its key "
    "conclusion, in the same language as the conversation. Answer:\n{answer}"
)


class EmbedAnnotationInput(CommandInput):
    """Input for embedding a single source annotation (highlight)."""

    annotation_id: str


class EmbedAnnotationOutput(CommandOutput):
    """Output from annotation embedding command."""

    success: bool
    annotation_id: str
    processing_time: float
    error_message: Optional[str] = None


class MirrorChatExchangeInput(CommandInput):
    """Input for mirroring one completed chat turn into study memory."""

    session_id: str
    scope: str
    source_id: Optional[str] = None
    notebook_id: Optional[str] = None
    question: str
    answer: str
    message_id: str
    annotation_ids: List[str] = Field(default_factory=list)


class MirrorChatExchangeOutput(CommandOutput):
    """Output from the chat-exchange mirror command."""

    success: bool
    exchange_id: Optional[str] = None
    gist_used_fallback: bool = False
    processing_time: float
    error_message: Optional[str] = None


@command(
    "embed_annotation",
    app="open_notebook",
    retry=_STANDARD_RETRY,
)
async def embed_annotation_command(
    input_data: EmbedAnnotationInput,
) -> EmbedAnnotationOutput:
    """
    Generate and store embedding for a single source annotation (highlight).

    Uses the unified embedding pipeline with automatic chunking and mean
    pooling for annotations that exceed the chunk size limit.

    Flow:
    1. Load SourceAnnotation by ID
    2. Build searchable text from quote + note + tags
    3. Generate embedding via generate_embedding() (auto-chunks + mean pools if needed)
    4. UPSERT annotation embedding in database

    Re-runs on every ``SourceAnnotation.save()`` (coordinator decision 11) so
    edits to the quote/note/tags re-embed.

    Retry Strategy:
    - Retries up to 5 times for transient failures (network, timeout, etc.)
    - Uses exponential-jitter backoff (1-60s)
    - Does NOT retry permanent failures (ValueError for validation errors)
    """
    start_time = time.time()

    try:
        logger.info(f"Starting embedding for annotation: {input_data.annotation_id}")

        # 1. Load annotation
        annotation = await SourceAnnotation.get(input_data.annotation_id)
        if not annotation:
            raise ValueError(f"Annotation '{input_data.annotation_id}' not found")

        # 2. Build searchable text: quote + note + comma-joined tags
        text = "\n\n".join(
            filter(
                None,
                [annotation.quote, annotation.note, ", ".join(annotation.tags)],
            )
        )
        if not text.strip():
            raise ValueError(
                f"Annotation '{input_data.annotation_id}' has no text to embed"
            )

        # 3. Generate embedding (auto-chunks + mean pools if needed)
        cmd_id = get_command_id(input_data)
        embedding = await generate_embedding(
            text, content_type=ContentType.MARKDOWN, command_id=cmd_id
        )

        # 4. UPSERT embedding into annotation record
        await repo_query(
            "UPDATE $annotation_id SET embedding = $embedding",
            {
                "annotation_id": ensure_record_id(input_data.annotation_id),
                "embedding": embedding,
            },
        )

        processing_time = time.time() - start_time
        logger.info(
            f"Successfully embedded annotation {input_data.annotation_id} "
            f"in {processing_time:.2f}s"
        )

        return EmbedAnnotationOutput(
            success=True,
            annotation_id=input_data.annotation_id,
            processing_time=processing_time,
        )

    except ValueError as e:
        # Permanent failure - don't retry
        processing_time = time.time() - start_time
        cmd_id = get_command_id(input_data)
        logger.error(
            f"Failed to embed annotation {input_data.annotation_id} "
            f"(command: {cmd_id}): {e}"
        )
        return EmbedAnnotationOutput(
            success=False,
            annotation_id=input_data.annotation_id,
            processing_time=processing_time,
            error_message=str(e),
        )
    except Exception as e:
        # Transient failure - will be retried (surreal-commands logs final failure)
        cmd_id = get_command_id(input_data)
        logger.debug(
            f"Transient error embedding annotation {input_data.annotation_id} "
            f"(command: {cmd_id}): {e}"
        )
        raise


async def _generate_gist(answer: str, cmd_id: str) -> Tuple[str, bool]:
    """Distill ``answer`` into a short gist; never raises.

    Returns ``(gist, used_fallback)``. On any failure to provision/invoke the
    model, or when the reply fails the output-sanity guard (empty or over
    ``_GIST_MAX_CHARS``), falls back to ``answer[:_GIST_FALLBACK_CHARS]`` — a
    gist failure must never lose the exchange (coordinator decision 8).
    """
    fallback = answer[:_GIST_FALLBACK_CHARS]

    try:
        model = apply_reasoning_flag(
            await provision_langchain_model(answer, None, "gist", max_tokens=512),
            False,
        )
        defaults = await model_manager.get_defaults()
        # Gate on the resolved gist model (small by design) rather than the heavy
        # transformation model, so the mirror doesn't queue behind the big slot.
        gist_model_id = (
            defaults.default_gist_model or defaults.default_transformation_model
        )
        lane = await heavy_lane_for(gist_model_id)
        async with lane:
            await report_job_progress(cmd_id, "Distilling gist")
            response = await model.ainvoke(
                [HumanMessage(content=_GIST_INSTRUCTION.format(answer=answer))]
            )
        gist = clean_thinking_content(extract_text_content(response.content))
    except Exception as e:
        logger.warning(
            f"mirror_chat_exchange: gist generation failed (command: {cmd_id}): "
            f"{e} — using fallback gist"
        )
        return fallback, True

    if not gist or not gist.strip() or len(gist) > _GIST_MAX_CHARS:
        logger.debug(
            f"mirror_chat_exchange: gist sanity guard triggered "
            f"(len={len(gist) if gist else 0}, command: {cmd_id}) — using fallback"
        )
        return fallback, True

    return gist.strip(), False


@command(
    "mirror_chat_exchange",
    app="open_notebook",
    retry=_STANDARD_RETRY,
)
async def mirror_chat_exchange_command(
    input_data: MirrorChatExchangeInput,
) -> MirrorChatExchangeOutput:
    """
    Mirror one completed chat turn into queryable study memory.

    Flow:
    1. Distill a short gist from the answer (never fails the job — falls
       back to a truncated answer slice on any gist error or sanity-guard
       trip; see ``_generate_gist``).
    2. Create a ``ChatExchange`` record (question truncated to a sane bound).
    3. Embed ``question + gist`` and write the embedding back.

    Submitted fire-and-forget from ``chat_completion_command`` after each
    chat turn (Chunk A3); a mirror failure must never fail the chat turn
    itself — that guarantee lives at the call site, not here.

    Retry Strategy:
    - Retries up to 5 times for transient failures (network, timeout, etc.)
    - Uses exponential-jitter backoff (1-60s)
    - Does NOT retry permanent failures (ValueError/ConfigurationError)
    """
    start_time = time.time()
    cmd_id = get_command_id(input_data)

    try:
        logger.info(
            f"Starting chat-exchange mirror for session {input_data.session_id} "
            f"(scope={input_data.scope})"
        )

        if not input_data.session_id:
            raise ValueError("mirror_chat_exchange requires a session_id")
        if not input_data.answer or not input_data.answer.strip():
            raise ValueError("mirror_chat_exchange requires a non-empty answer")

        # 1. Gist — never raises; falls back internally on failure.
        gist, used_fallback = await _generate_gist(input_data.answer, cmd_id)

        # 2. Create the exchange record.
        exchange = ChatExchange(
            session=input_data.session_id,
            scope=input_data.scope,
            source=input_data.source_id,
            notebook=input_data.notebook_id,
            question=input_data.question[:_QUESTION_MAX_CHARS],
            gist=gist,
            message_id=input_data.message_id,
            annotation_ids=list(input_data.annotation_ids or []),
        )
        await report_job_progress(cmd_id, "Saving exchange")
        await exchange.save()
        if not exchange.id:
            raise ValueError("Failed to create chat_exchange record")

        # 3. Embed question + gist, write back.
        await report_job_progress(cmd_id, "Embedding exchange")
        embed_text = (
            f"{exchange.question}\n\n{gist}" if gist else exchange.question
        )
        embedding = await generate_embedding(
            embed_text, content_type=ContentType.MARKDOWN, command_id=cmd_id
        )
        await repo_query(
            "UPDATE $exchange_id SET embedding = $embedding",
            {
                "exchange_id": ensure_record_id(str(exchange.id)),
                "embedding": embedding,
            },
        )

        processing_time = time.time() - start_time
        logger.info(
            f"Successfully mirrored chat exchange {exchange.id} "
            f"in {processing_time:.2f}s (gist_fallback={used_fallback})"
        )

        return MirrorChatExchangeOutput(
            success=True,
            exchange_id=str(exchange.id),
            gist_used_fallback=used_fallback,
            processing_time=processing_time,
        )

    except (ValueError, ConfigurationError) as e:
        # Permanent failure - don't retry
        processing_time = time.time() - start_time
        logger.error(
            f"Failed to mirror chat exchange for session {input_data.session_id} "
            f"(command: {cmd_id}): {e}"
        )
        return MirrorChatExchangeOutput(
            success=False,
            processing_time=processing_time,
            error_message=str(e),
        )
    except Exception as e:
        # Transient failure - will be retried (surreal-commands logs final failure)
        logger.debug(
            f"Transient error mirroring chat exchange for session "
            f"{input_data.session_id} (command: {cmd_id}): {e}"
        )
        raise
