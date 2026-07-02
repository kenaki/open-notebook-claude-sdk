import asyncio
import operator
from typing import Any, Dict, List, Optional, Tuple

from content_core import extract_content
from content_core.common import ProcessSourceState
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from loguru import logger
from typing_extensions import Annotated, NotRequired, TypedDict

from surreal_commands import submit_command

from open_notebook.ai.models import Model, ModelManager
from open_notebook.domain.content_settings import ContentSettings
from open_notebook.domain.notebook import Asset, Source
from open_notebook.domain.transformation import Transformation
from open_notebook.graphs.transformation import graph as transform_graph


class SourceState(TypedDict):
    content_state: ProcessSourceState
    apply_transformations: List[Transformation]
    source_id: str
    notebook_ids: List[str]
    source: Source
    transformation: Annotated[list, operator.add]
    embed: bool
    # A2: per-block page provenance from Docling (None for non-PDF or on fallback)
    page_map: NotRequired[Optional[List[Dict]]]


class TransformationState(TypedDict):
    source: Source
    transformation: Transformation


# ---------------------------------------------------------------------------
# A2: Docling page-provenance extraction (sync; called via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _extract_docling_page_map(file_path: str) -> Tuple[str, List[Dict]]:
    """
    Run Docling on a PDF file and return (structured_markdown, page_map).

    page_map is a list of {"text": str, "page_no": int} dicts — one entry per
    text block — where page_no is Docling's 1-indexed physical page number.
    Raises on any failure so the caller can fall back gracefully.
    """
    from docling.document_converter import DocumentConverter  # lazy import

    converter = DocumentConverter()
    result = converter.convert(file_path)
    doc = result.document

    full_text: str = doc.export_to_markdown()

    page_map: List[Dict] = []
    for item, _level in doc.iterate_items():
        text = getattr(item, "text", None)
        prov_list = getattr(item, "prov", None)
        if text and prov_list:
            try:
                page_no: int = prov_list[0].page_no
                page_map.append({"text": text, "page_no": page_no})
            except (AttributeError, IndexError):
                # Malformed provenance on this block — skip silently
                pass

    return full_text, page_map


async def content_process(state: SourceState) -> dict:
    content_settings = ContentSettings(
        default_content_processing_engine_doc="auto",
        default_content_processing_engine_url="auto",
        default_embedding_option="ask",
        auto_delete_files="yes",
        youtube_preferred_languages=[
            "en",
            "pt",
            "es",
            "de",
            "nl",
            "en-GB",
            "fr",
            "hi",
            "ja",
        ],
    )
    content_state: Dict[str, Any] = state["content_state"]  # type: ignore[assignment]

    content_state["url_engine"] = (
        content_settings.default_content_processing_engine_url or "auto"
    )
    content_state["document_engine"] = (
        content_settings.default_content_processing_engine_doc or "auto"
    )
    content_state["output_format"] = "markdown"

    # Add speech-to-text model configuration from Default Models
    try:
        model_manager = ModelManager()
        defaults = await model_manager.get_defaults()
        if defaults.default_speech_to_text_model:
            stt_model = await Model.get(defaults.default_speech_to_text_model)
            if stt_model:
                content_state["audio_provider"] = stt_model.provider
                content_state["audio_model"] = stt_model.name
                logger.debug(
                    f"Using speech-to-text model: {stt_model.provider}/{stt_model.name}"
                )
    except Exception as e:
        logger.warning(f"Failed to retrieve speech-to-text model configuration: {e}")
        # Continue without custom audio model (content-core will use its default)

    processed_state = await extract_content(content_state)

    # content-core signals a soft extraction failure (e.g. an unreachable or
    # invalid URL) by returning title="Error" and content prefixed with
    # "Failed to extract content:" instead of raising. Detect that sentinel and
    # raise so the job is marked failed and the source becomes retryable, rather
    # than being saved as a "completed" source whose body is the error string.
    if processed_state.title == "Error" and (processed_state.content or "").startswith(
        "Failed to extract content:"
    ):
        raise ValueError(
            "Could not extract content from this source. "
            "The URL or file may be unreachable, invalid, or in an unsupported format."
        )

    if not processed_state.content or not processed_state.content.strip():
        url = processed_state.url or ""
        if url and ("youtube.com" in url or "youtu.be" in url):
            raise ValueError(
                "Could not extract content from this YouTube video. "
                "No transcript or subtitles are available. "
                "Try configuring a Speech-to-Text model in Settings "
                "to transcribe the audio instead."
            )
        raise ValueError(
            "Could not extract any text content from this source. "
            "The content may be empty, inaccessible, or in an unsupported format."
        )

    # ------------------------------------------------------------------
    # A2: For PDF sources, additionally run Docling directly to capture
    #     structured markdown (full_text) and per-block page provenance
    #     (page_map).  Non-PDF sources are unchanged.
    #     On ANY Docling failure: log + keep existing content + page_map=None.
    # ------------------------------------------------------------------
    page_map: Optional[List[Dict]] = None
    if (
        processed_state.identified_type == "application/pdf"
        and processed_state.file_path
    ):
        try:
            full_text, page_map = await asyncio.to_thread(
                _extract_docling_page_map, processed_state.file_path
            )
            # Replace content with Docling's structured markdown (richer
            # heading/table/list structure compared to the PyMuPDF plain-text path)
            processed_state.content = full_text
            logger.info(
                f"Docling extraction: {len(page_map)} blocks, {len(full_text)} chars"
            )
        except ImportError:
            logger.warning(
                "Docling not installed — PDF uses existing extraction path; "
                "page_map=None.  Install via: uv sync (content-core[docling] in pyproject.toml)"
            )
        except Exception as exc:
            logger.warning(
                f"Docling extraction failed ({exc!r}) — falling back to existing "
                "extraction content; page_map=None"
            )

    return {"content_state": processed_state, "page_map": page_map}


async def save_source(state: SourceState) -> dict:
    content_state = state["content_state"]

    # Get existing source using the provided source_id
    source = await Source.get(state["source_id"])
    if not source:
        raise ValueError(f"Source with ID {state['source_id']} not found")

    # Update the source with processed content
    source.asset = Asset(url=content_state.url, file_path=content_state.file_path)
    source.full_text = content_state.content

    # Preserve user-set title; only overwrite placeholder or empty titles
    if content_state.title and (not source.title or source.title == "Processing..."):
        source.title = content_state.title

    # Phase3: persist A2's per-block page provenance so out-of-process embedding
    # commands (embed_source / backfill_page_numbers) can stamp page_number on
    # each chunk. Only PDFs that went through Docling carry a page_map; web /
    # pasted / PyMuPDF-fallback sources leave it null and degrade gracefully.
    page_map = state.get("page_map")
    if page_map:
        source.page_map = page_map

    await source.save()

    # NOTE: Notebook associations are created by the API immediately for UI responsiveness
    # No need to create them here to avoid duplicate edges

    if state["embed"]:
        if source.full_text and source.full_text.strip():
            logger.debug("Embedding content for vector search")
            await source.vectorize()
        else:
            logger.warning(
                f"Source {source.id} has no text content to embed, skipping vectorization"
            )

    return {"source": source}


def trigger_transformations(state: SourceState, config: RunnableConfig) -> List[Send]:
    if len(state["apply_transformations"]) == 0:
        return []

    to_apply = state["apply_transformations"]
    logger.debug(f"Applying transformations {to_apply}")

    return [
        Send(
            "transform_content",
            {
                "source": state["source"],
                "transformation": t,
            },
        )
        for t in to_apply
    ]


async def transform_content(state: TransformationState) -> Optional[dict]:
    source = state["source"]
    content = source.full_text
    if not content:
        return None
    transformation: Transformation = state["transformation"]

    logger.debug(f"Applying transformation {transformation.name}")
    result = await transform_graph.ainvoke(
        dict(input_text=content, transformation=transformation)  # type: ignore[arg-type]
    )
    await source.add_insight(transformation.title, result["output"])
    return {
        "transformation": [
            {
                "output": result["output"],
                "transformation_name": transformation.name,
            }
        ]
    }


async def submit_sections(state: SourceState) -> dict:
    """
    A3: Fire-and-forget build_sections for PDF sources.

    Submits a build_sections command immediately after save_source so that the
    section tree is built asynchronously (retriable, visible in the job tray).
    Non-PDF sources and sources without full_text are skipped silently.
    """
    source = state.get("source")
    if not source:
        return {}

    # Decision #12: chaptering is for PDFs / long documents only in v1
    content_state = state.get("content_state")
    is_pdf = False
    if content_state is not None and hasattr(content_state, "identified_type"):
        is_pdf = content_state.identified_type == "application/pdf"
    elif source.asset and source.asset.file_path:
        is_pdf = source.asset.file_path.lower().endswith(".pdf")

    if not is_pdf:
        return {}

    if not source.full_text or not source.full_text.strip():
        return {}

    try:
        cmd_id = submit_command(
            "open_notebook",
            "build_sections",
            {"source_id": str(source.id)},
        )
        logger.info(f"Submitted build_sections for source {source.id}: {cmd_id}")
    except Exception as exc:
        # Non-fatal: chaptering failure must not block the ingest pipeline
        logger.warning(f"Failed to submit build_sections for {source.id}: {exc}")

    return {}


# Create and compile the workflow
workflow = StateGraph(SourceState)

# Add nodes
workflow.add_node("content_process", content_process)
workflow.add_node("save_source", save_source)
workflow.add_node("submit_sections", submit_sections)  # A3: chaptering fire-and-forget
workflow.add_node("transform_content", transform_content)
# Define the graph edges
workflow.add_edge(START, "content_process")
workflow.add_edge("content_process", "save_source")
# A3: submit chaptering job after save, then fan out transformations
workflow.add_edge("save_source", "submit_sections")
workflow.add_conditional_edges(
    "submit_sections", trigger_transformations, ["transform_content"]
)
workflow.add_edge("transform_content", END)

# Compile the graph
source_graph = workflow.compile()
