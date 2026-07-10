from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Notebook models
class NotebookCreate(BaseModel):
    name: str = Field(..., description="Name of the notebook")
    description: str = Field(default="", description="Description of the notebook")


class NotebookUpdate(BaseModel):
    name: Optional[str] = Field(None, description="Name of the notebook")
    description: Optional[str] = Field(None, description="Description of the notebook")
    archived: Optional[bool] = Field(
        None, description="Whether the notebook is archived"
    )
    chat_tag_colors: Optional[Dict[str, str]] = Field(
        None, description="Tag → color-key map for the chat gallery (replaces existing)"
    )
    auto_illustrate: Optional[bool] = Field(
        None, description="Per-notebook auto-illustrate toggle for chat messages"
    )


class NotebookResponse(BaseModel):
    id: str
    name: str
    description: str
    archived: bool
    created: str
    updated: str
    source_count: int
    note_count: int
    chat_tag_colors: Dict[str, str] = Field(
        default_factory=dict, description="Tag → color-key map for the chat gallery"
    )
    auto_illustrate: bool = Field(
        True,
        description="Per-notebook auto-illustrate toggle for chat messages (default True)",
    )


# Search models
class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query")
    type: Literal["text", "vector"] = Field("text", description="Search type")
    limit: int = Field(100, description="Maximum number of results", ge=1, le=1000)
    search_sources: bool = Field(True, description="Include sources in search")
    search_notes: bool = Field(True, description="Include notes in search")
    minimum_score: float = Field(
        0.2, description="Minimum score for vector search", ge=0, le=1
    )


class SearchResponse(BaseModel):
    results: List[Dict[str, Any]] = Field(..., description="Search results")
    total_count: int = Field(..., description="Total number of results")
    search_type: str = Field(..., description="Type of search performed")


class AskRequest(BaseModel):
    question: str = Field(..., description="Question to ask the knowledge base")
    strategy_model: str = Field(..., description="Model ID for query strategy")
    answer_model: str = Field(..., description="Model ID for individual answers")
    final_answer_model: str = Field(..., description="Model ID for final answer")


class AskResponse(BaseModel):
    answer: str = Field(..., description="Final answer from the knowledge base")
    question: str = Field(..., description="Original question")


# Models API models
class ModelCreate(BaseModel):
    name: str = Field(..., description="Model name (e.g., gpt-5-mini, claude, gemini)")
    provider: str = Field(
        ..., description="Provider name (e.g., openai, anthropic, gemini)"
    )
    type: str = Field(
        ...,
        description="Model type (language, embedding, text_to_speech, speech_to_text)",
    )
    credential: Optional[str] = Field(
        None, description="Credential ID to link this model to"
    )


class ModelResponse(BaseModel):
    id: str
    name: str
    provider: str
    type: str
    credential: Optional[str] = None
    created: str
    updated: str


class DefaultModelsResponse(BaseModel):
    default_chat_model: Optional[str] = None
    default_transformation_model: Optional[str] = None
    large_context_model: Optional[str] = None
    default_text_to_speech_model: Optional[str] = None
    default_speech_to_text_model: Optional[str] = None
    default_embedding_model: Optional[str] = None
    default_tools_model: Optional[str] = None


class ProviderAvailabilityResponse(BaseModel):
    available: List[str] = Field(..., description="List of available providers")
    unavailable: List[str] = Field(..., description="List of unavailable providers")
    supported_types: Dict[str, List[str]] = Field(
        ..., description="Provider to supported model types mapping"
    )


class ClaudeAgentModelOption(BaseModel):
    value: str = Field(..., description="Model id/alias ('' = follow Claude Code default)")
    label: str = Field(..., description="Human-readable label for the dropdown")


class ClaudeAgentModelResponse(BaseModel):
    model: Optional[str] = Field(
        None,
        description="Pinned Claude model id (null = follow the Claude Code default)",
    )
    env_override: Optional[str] = Field(
        None,
        description="CLAUDE_AGENT_MODEL env value; applies only when model follows default",
    )
    options: List[ClaudeAgentModelOption] = Field(
        ..., description="Curated selectable models for the dropdown"
    )


class ClaudeAgentModelUpdate(BaseModel):
    model: Optional[str] = Field(
        None,
        description="Claude model id/alias to pin; empty/null follows the Claude Code default",
    )


# Transformations API models
class TransformationCreate(BaseModel):
    name: str = Field(..., description="Transformation name")
    title: str = Field(..., description="Display title for the transformation")
    description: str = Field(
        ..., description="Description of what this transformation does"
    )
    prompt: str = Field(..., description="The transformation prompt")
    apply_default: bool = Field(
        False, description="Whether to apply this transformation by default"
    )


class TransformationUpdate(BaseModel):
    name: Optional[str] = Field(None, description="Transformation name")
    title: Optional[str] = Field(
        None, description="Display title for the transformation"
    )
    description: Optional[str] = Field(
        None, description="Description of what this transformation does"
    )
    prompt: Optional[str] = Field(None, description="The transformation prompt")
    apply_default: Optional[bool] = Field(
        None, description="Whether to apply this transformation by default"
    )


class TransformationResponse(BaseModel):
    id: str
    name: str
    title: str
    description: str
    prompt: str
    apply_default: bool
    created: str
    updated: str


class TransformationExecuteRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    transformation_id: str = Field(
        ..., description="ID of the transformation to execute"
    )
    input_text: str = Field(..., description="Text to transform")
    model_id: str = Field(..., description="Model ID to use for the transformation")


class TransformationExecuteResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    output: str = Field(..., description="Transformed text")
    transformation_id: str = Field(..., description="ID of the transformation used")
    model_id: str = Field(..., description="Model ID used")


# Default Prompt API models
class DefaultPromptResponse(BaseModel):
    transformation_instructions: str = Field(
        ..., description="Default transformation instructions"
    )


class DefaultPromptUpdate(BaseModel):
    transformation_instructions: str = Field(
        ..., description="Default transformation instructions"
    )


# Notes API models
class NoteCreate(BaseModel):
    title: Optional[str] = Field(None, description="Note title")
    content: str = Field(..., description="Note content")
    note_type: Optional[str] = Field("human", description="Type of note (human, ai)")
    notebook_id: Optional[str] = Field(
        None, description="Notebook ID to add the note to"
    )


class NoteUpdate(BaseModel):
    title: Optional[str] = Field(None, description="Note title")
    content: Optional[str] = Field(None, description="Note content")
    note_type: Optional[str] = Field(None, description="Type of note (human, ai)")


class NoteResponse(BaseModel):
    id: str
    title: Optional[str]
    content: Optional[str]
    note_type: Optional[str]
    created: str
    updated: str
    command_id: Optional[str] = None


# Embedding API models
class EmbedRequest(BaseModel):
    item_id: str = Field(..., description="ID of the item to embed")
    item_type: str = Field(..., description="Type of item (source, note)")
    async_processing: bool = Field(
        False, description="Process asynchronously in background"
    )


class EmbedResponse(BaseModel):
    success: bool = Field(..., description="Whether embedding was successful")
    message: str = Field(..., description="Result message")
    item_id: str = Field(..., description="ID of the item that was embedded")
    item_type: str = Field(..., description="Type of item that was embedded")
    command_id: Optional[str] = Field(
        None, description="Command ID for async processing"
    )


# Rebuild request/response models
class RebuildRequest(BaseModel):
    mode: Literal["existing", "all"] = Field(
        ...,
        description="Rebuild mode: 'existing' only re-embeds items with embeddings, 'all' embeds everything",
    )
    include_sources: bool = Field(True, description="Include sources in rebuild")
    include_notes: bool = Field(True, description="Include notes in rebuild")
    include_insights: bool = Field(True, description="Include insights in rebuild")


class RebuildResponse(BaseModel):
    command_id: str = Field(..., description="Command ID to track progress")
    total_items: int = Field(..., description="Estimated number of items to process")
    message: str = Field(..., description="Status message")


class RebuildProgress(BaseModel):
    processed: int = Field(..., description="Number of items processed")
    total: int = Field(..., description="Total items to process")
    percentage: float = Field(..., description="Progress percentage")


class RebuildStats(BaseModel):
    sources: int = Field(0, description="Sources processed")
    notes: int = Field(0, description="Notes processed")
    insights: int = Field(0, description="Insights processed")
    failed: int = Field(0, description="Failed items")


class RebuildStatusResponse(BaseModel):
    command_id: str = Field(..., description="Command ID")
    status: str = Field(..., description="Status: queued, running, completed, failed")
    progress: Optional[RebuildProgress] = None
    stats: Optional[RebuildStats] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


# Settings API models
class SettingsResponse(BaseModel):
    default_content_processing_engine_doc: Optional[str] = None
    default_content_processing_engine_url: Optional[str] = None
    default_embedding_option: Optional[str] = None
    auto_delete_files: Optional[str] = None
    youtube_preferred_languages: Optional[List[str]] = None


class SettingsUpdate(BaseModel):
    default_content_processing_engine_doc: Optional[str] = None
    default_content_processing_engine_url: Optional[str] = None
    default_embedding_option: Optional[str] = None
    auto_delete_files: Optional[str] = None
    youtube_preferred_languages: Optional[List[str]] = None


# Sources API models
class AssetModel(BaseModel):
    file_path: Optional[str] = None
    url: Optional[str] = None


class SourceCreate(BaseModel):
    # Backward compatibility: support old single notebook_id
    notebook_id: Optional[str] = Field(
        None, description="Notebook ID to add the source to (deprecated, use notebooks)"
    )
    # New multi-notebook support
    notebooks: Optional[List[str]] = Field(
        None, description="List of notebook IDs to add the source to"
    )
    # Required fields
    type: str = Field(..., description="Source type: link, upload, or text")
    url: Optional[str] = Field(None, description="URL for link type")
    file_path: Optional[str] = Field(None, description="File path for upload type")
    content: Optional[str] = Field(None, description="Text content for text type")
    title: Optional[str] = Field(None, description="Source title")
    transformations: Optional[List[str]] = Field(
        default_factory=list, description="Transformation IDs to apply"
    )
    embed: bool = Field(False, description="Whether to embed content for vector search")
    delete_source: bool = Field(
        False, description="Whether to delete uploaded file after processing"
    )
    # New async processing support
    async_processing: bool = Field(
        False, description="Whether to process source asynchronously"
    )

    @model_validator(mode="after")
    def validate_notebook_fields(self):
        # Ensure only one of notebook_id or notebooks is provided
        if self.notebook_id is not None and self.notebooks is not None:
            raise ValueError(
                "Cannot specify both 'notebook_id' and 'notebooks'. Use 'notebooks' for multi-notebook support."
            )

        # Convert single notebook_id to notebooks array for internal processing
        if self.notebook_id is not None:
            self.notebooks = [self.notebook_id]
            # Keep notebook_id for backward compatibility in response

        # Set empty array if no notebooks specified (allow sources without notebooks)
        if self.notebooks is None:
            self.notebooks = []

        return self


class SourceUpdate(BaseModel):
    title: Optional[str] = Field(None, description="Source title")
    topics: Optional[List[str]] = Field(None, description="Source topics")


class SourceSectionNode(BaseModel):
    id: str
    title: str
    level: int
    order: int
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    summary: Optional[str] = None
    content: Optional[str] = None  # only included when explicitly requested
    children: List["SourceSectionNode"] = []


SourceSectionNode.model_rebuild()  # needed for self-referential models


class SourceSectionResponse(BaseModel):
    id: str
    title: Optional[str]
    has_sections: bool
    sections_count: int
    sections: List[SourceSectionNode] = []


class SourceResponse(BaseModel):
    id: str
    title: Optional[str]
    topics: Optional[List[str]]
    asset: Optional[AssetModel]
    # E3: full_text is excluded from the serialized payload (regenerated whole-book
    # markdown fetched lazily via GET /sources/{id}/full-text instead).
    full_text: Optional[str] = Field(default=None, exclude=True)
    embedded: bool
    embedded_chunks: int
    file_available: Optional[bool] = None
    created: str
    updated: str
    # New fields for async processing
    command_id: Optional[str] = None
    status: Optional[str] = None
    processing_info: Optional[Dict] = None
    # Notebook associations
    notebooks: Optional[List[str]] = None
    # Section metadata
    has_sections: bool = False
    sections_count: int = 0


class SourceListResponse(BaseModel):
    id: str
    title: Optional[str]
    topics: Optional[List[str]]
    asset: Optional[AssetModel]
    embedded: bool  # Boolean flag indicating if source has embeddings
    embedded_chunks: int  # Number of embedded chunks
    insights_count: int
    created: str
    updated: str
    file_available: Optional[bool] = None
    # Status fields for async processing
    command_id: Optional[str] = None
    status: Optional[str] = None
    processing_info: Optional[Dict[str, Any]] = None


# PDF annotation models (document-foundation Phase4)
class AnnotationRect(BaseModel):
    """One line-rect of a highlight selection — the native `HighlightArea`
    shape emitted by `@react-pdf-viewer/highlight`. `left`/`top`/`width`/
    `height` are percentages (0-100) of the page box; `pageIndex` is 0-based.
    A single highlight is a LIST of these (length 1 for a single-line
    selection, >1 for a multi-line/paragraph selection).
    """

    pageIndex: int
    left: float
    top: float
    width: float
    height: float


class AnnotationResponse(BaseModel):
    id: str
    source_id: str
    page: int
    rect: List[Dict[str, Any]]
    color: str
    note: Optional[str] = None
    quote: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    # Block-substrate anchor (pdf-block-ingestion Track D1, Decision #13). The
    # anchor is server-resolved from rect+quote at create time; these mirror the
    # SourceAnnotation columns. block_seq..block_end_seq is the block RANGE (equal
    # for a single-block highlight); anchor_start/anchor_end are char offsets
    # (None for a geometric span or an atomic figure/table/equation). anchor_state
    # is DERIVED server-side (never stored): no block_seq -> legacy; anchor_gen !=
    # source.parse_generation -> stale; else anchored.
    block_seq: Optional[int] = None
    block_end_seq: Optional[int] = None
    anchor_start: Optional[int] = None
    anchor_end: Optional[int] = None
    anchor_gen: Optional[int] = None
    anchor_state: Literal["anchored", "stale", "legacy"] = "legacy"
    created: str
    updated: str


class CreateAnnotationRequest(BaseModel):
    """Create a highlight in one of two directions (db-design §2.3, Track D1/D7).

    * **PDF-born** (default): the client sends ``page`` + ``rect`` (line-rects of
      the pdf.js selection); the server RESOLVES the block anchor from rect+quote.
    * **reader-born** (D7): the client sends the block range
      (``block_seq``/``block_end_seq``) + char offsets + ``quote`` and the server
      DERIVES ``page`` + ``rect`` from the blocks' bboxes — so ``page``/``rect``
      are optional here (server-filled). ``block_seq`` being present is what
      selects the reader-born path.
    """

    page: int = Field(default=1, description="1-indexed physical page of the first rect (PDF-born; server-derived for reader-born)")
    rect: List[AnnotationRect] = Field(
        default_factory=list,
        description="One entry per line-rect of the selection (PDF-born; server-derived for reader-born)",
    )
    color: str = Field(default="#fde047", description="Highlight color (hex)")
    note: Optional[str] = Field(default=None, description="User comment on the highlight")
    quote: Optional[str] = Field(default=None, description="The selected text")
    tags: List[str] = Field(default_factory=list, description="Grouping tags")
    # Reader-born block anchor (D7). When block_seq is set, the request is
    # reader-born: the server validates the range against the CURRENT parse
    # generation and derives page+rect from the blocks' bboxes. Offsets are the
    # char positions within block_seq/block_end_seq's text (null for a
    # multi-block span or an atomic figure/table/equation, per §2.3).
    block_seq: Optional[int] = Field(default=None, description="Reader-born: start block seq")
    block_end_seq: Optional[int] = Field(default=None, description="Reader-born: end block seq (defaults to block_seq)")
    anchor_start: Optional[int] = Field(default=None, description="Reader-born: char offset within block_seq's text")
    anchor_end: Optional[int] = Field(default=None, description="Reader-born: char offset within block_end_seq's text")

    @model_validator(mode="after")
    def _validate_create_path(self) -> "CreateAnnotationRequest":
        if self.block_seq is None:
            # PDF-born: a rect is required (server resolves the anchor from it).
            if not self.rect:
                raise ValueError("rect must contain at least one line-rect for a PDF-born annotation")
        elif self.block_end_seq is None:
            # Single-block reader selection: end defaults to start.
            self.block_end_seq = self.block_seq
        return self


class UpdateAnnotationRequest(BaseModel):
    note: Optional[str] = None
    color: Optional[str] = None
    # None = leave tags unchanged; a list (incl. []) replaces the whole set.
    tags: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Block / parse schemas (pdf-block-ingestion Track C — db-design §2–§3)
# Payload-hygienic by construction: optional fields are OMITTED by projection
# (routes serialize with response_model_exclude_none), so a page overlay ships
# no text and a window ships no bbox. Composite block ids read back as strings
# but the API surfaces only the plain `seq`.
# ---------------------------------------------------------------------------
class BlockResponse(BaseModel):
    """One typed block (db-design §2.1). The overlay projection fills only
    seq/type/page/bbox/parent_seq/level; text/latex/section_path/table_data and
    the derived `image_url` appear only on text/full/window projections."""

    seq: int
    type: str
    page: Optional[int] = None
    bbox: Optional[List[float]] = None
    parent_seq: Optional[int] = None
    level: Optional[int] = None
    section_path: Optional[List[str]] = None
    text: Optional[str] = None
    latex: Optional[str] = None
    # /api/sources/{id}/blocks/{seq}/image — set only when the block carries a crop
    image_url: Optional[str] = None
    table_data: Optional[Dict[str, Any]] = None


class PageBlocksResponse(BaseModel):
    """One page's blocks in reading (seq) order (db-design §3a)."""

    page: int
    gen: int
    blocks: List[BlockResponse] = Field(default_factory=list)


class ParseStatusResponse(BaseModel):
    """Parse status header for the source's current generation (db-design §2.2).
    Polled by the frontend to track a re-parse."""

    parse_status: Optional[str] = None
    gen: int
    parser_name: Optional[str] = None
    parser_version: Optional[str] = None
    block_count: Optional[int] = None
    page_count: Optional[int] = None
    # `page -> [first_seq, last_seq]`, indexed by `page - 1`. An empty page holds
    # the inverted range [0, -1]. The reader uses it both ways: seq -> page (to
    # label outline entries) and page -> seq (to jump). Already stored on every
    # parse header, so it needs no re-parse.
    page_index: Optional[List[List[int]]] = None
    section_index: Optional[List[Any]] = None
    error: Optional[str] = None


class BlockSpanResponse(BaseModel):
    """A windowed span of pages' blocks with full text for the markdown reader
    view (db-design §3a, Decision #12). Blocks arrive in reading (seq) order with
    text/latex/section_path/image_url populated. `start_page`/`end_page` reflect
    the CLAMPED bounds actually served (max 10 pages per request)."""

    gen: int
    start_page: int
    end_page: int
    blocks: List[BlockResponse] = Field(default_factory=list)


# Context API models
class ContextConfig(BaseModel):
    sources: Dict[str, str] = Field(
        default_factory=dict, description="Source inclusion config {source_id: level}"
    )
    notes: Dict[str, str] = Field(
        default_factory=dict, description="Note inclusion config {note_id: level}"
    )


class ContextRequest(BaseModel):
    notebook_id: str = Field(..., description="Notebook ID to get context for")
    context_config: Optional[ContextConfig] = Field(
        None, description="Context configuration"
    )


class ContextResponse(BaseModel):
    notebook_id: str
    sources: List[Dict[str, Any]] = Field(..., description="Source context data")
    notes: List[Dict[str, Any]] = Field(..., description="Note context data")
    total_tokens: Optional[int] = Field(None, description="Estimated token count")


# Insights API models
class SourceInsightResponse(BaseModel):
    id: str
    source_id: str
    insight_type: str
    content: str
    created: str
    updated: str


class InsightCreationResponse(BaseModel):
    """Response for async insight creation."""

    status: Literal["pending"] = "pending"
    message: str = "Insight generation started"
    source_id: str
    transformation_id: str
    command_id: Optional[str] = None


class SaveAsNoteRequest(BaseModel):
    notebook_id: Optional[str] = Field(None, description="Notebook ID to add note to")


class CreateSourceInsightRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    transformation_id: str = Field(..., description="ID of transformation to apply")
    model_id: Optional[str] = Field(
        None, description="Model ID (uses default if not provided)"
    )


# Source status response
class SourceStatusResponse(BaseModel):
    status: Optional[str] = Field(None, description="Processing status")
    message: str = Field(..., description="Descriptive message about the status")
    processing_info: Optional[Dict[str, Any]] = Field(
        None, description="Detailed processing information"
    )
    command_id: Optional[str] = Field(None, description="Command ID if available")
    parse_status: Optional[str] = Field(
        None,
        description="Block-parse lifecycle for PDF sources: pending/parsing/embedding/ready/failed",
    )
    failed_jobs: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Failed downstream pipeline jobs for the current run: [{name, count, latest_error}]",
    )


# Error response
class ErrorResponse(BaseModel):
    error: str
    message: str


# API Key Configuration models
class SetApiKeyRequest(BaseModel):
    """Request to set an API key for a provider."""

    api_key: Optional[str] = Field(None, description="API key for the provider")
    base_url: Optional[str] = Field(
        None, description="Base URL for URL-based providers (Ollama, OpenAI-compatible)"
    )
    endpoint: Optional[str] = Field(
        None, description="Endpoint URL for Azure OpenAI"
    )
    api_version: Optional[str] = Field(
        None, description="API version for Azure OpenAI"
    )
    endpoint_llm: Optional[str] = Field(
        None, description="Service-specific endpoint for LLM (Azure)"
    )
    endpoint_embedding: Optional[str] = Field(
        None, description="Service-specific endpoint for embedding (Azure)"
    )
    endpoint_stt: Optional[str] = Field(
        None, description="Service-specific endpoint for STT (Azure)"
    )
    endpoint_tts: Optional[str] = Field(
        None, description="Service-specific endpoint for TTS (Azure)"
    )
    service_type: Optional[Literal["llm", "embedding", "stt", "tts"]] = Field(
        None,
        description="Service type for OpenAI-compatible providers (llm, embedding, stt, tts)",
    )
    # Vertex AI specific fields
    vertex_project: Optional[str] = Field(
        None, description="Google Cloud Project ID for Vertex AI"
    )
    vertex_location: Optional[str] = Field(
        None, description="Google Cloud Region for Vertex AI (e.g., us-central1)"
    )
    vertex_credentials_path: Optional[str] = Field(
        None, description="Path to Google Cloud service account JSON file"
    )

    @field_validator(
        "api_key",
        "base_url",
        "endpoint",
        "api_version",
        "endpoint_llm",
        "endpoint_embedding",
        "endpoint_stt",
        "endpoint_tts",
        "vertex_project",
        "vertex_location",
        "vertex_credentials_path",
        mode="before",
    )
    @classmethod
    def validate_not_empty_string(cls, v: Optional[str]) -> Optional[str]:
        """Reject empty strings - convert to None or raise error."""
        if v is not None:
            stripped = v.strip()
            if not stripped:
                return None  # Treat empty/whitespace-only as None
            return stripped
        return v


class ApiKeyStatusResponse(BaseModel):
    """Response showing which providers are configured and their source."""

    configured: Dict[str, bool] = Field(
        ..., description="Map of provider name to whether it is configured"
    )
    source: Dict[str, Literal["database", "environment", "none"]] = Field(
        ...,
        description="Map of provider name to configuration source (database, environment, or none)",
    )
    encryption_configured: bool = Field(
        ...,
        description="Whether OPEN_NOTEBOOK_ENCRYPTION_KEY is set (required to store keys in database)",
    )


class TestConnectionResponse(BaseModel):
    """Response from testing a provider connection."""

    provider: str = Field(..., description="Provider name that was tested")
    success: bool = Field(..., description="Whether connection test succeeded")
    message: str = Field(..., description="Result message with details")


class MigrateFromEnvRequest(BaseModel):
    """Request to migrate API keys from environment variables to database."""

    force: bool = Field(
        False, description="Force overwrite existing database configurations"
    )


class MigrationResult(BaseModel):
    """Response from migrating API keys from environment to database."""

    message: str = Field(..., description="Summary message")
    migrated: List[str] = Field(
        default_factory=list, description="Providers successfully migrated"
    )
    skipped: List[str] = Field(
        default_factory=list, description="Providers skipped (already in DB)"
    )
    errors: List[str] = Field(
        default_factory=list, description="Migration errors by provider"
    )


# Notebook delete cascade models
# Credential models
class CreateCredentialRequest(BaseModel):
    """Request to create a new credential."""

    name: str = Field(..., description="Credential name")
    provider: str = Field(..., description="Provider name (openai, anthropic, etc.)")
    modalities: List[str] = Field(
        default_factory=list,
        description="Supported modalities (language, embedding, text_to_speech, speech_to_text)",
    )
    api_key: Optional[str] = Field(None, description="API key (stored encrypted)")
    base_url: Optional[str] = Field(None, description="Base URL")
    endpoint: Optional[str] = Field(None, description="Endpoint URL (Azure)")
    api_version: Optional[str] = Field(None, description="API version (Azure)")
    endpoint_llm: Optional[str] = Field(None, description="LLM endpoint")
    endpoint_embedding: Optional[str] = Field(None, description="Embedding endpoint")
    endpoint_stt: Optional[str] = Field(None, description="STT endpoint")
    endpoint_tts: Optional[str] = Field(None, description="TTS endpoint")
    project: Optional[str] = Field(None, description="Project ID (Vertex)")
    location: Optional[str] = Field(None, description="Location (Vertex)")
    credentials_path: Optional[str] = Field(
        None, description="Credentials file path (Vertex)"
    )
    num_ctx: Optional[int] = Field(
        None, description="Context window size (Ollama only; defaults to 8192)"
    )


class UpdateCredentialRequest(BaseModel):
    """Request to update an existing credential."""

    name: Optional[str] = Field(None, description="Credential name")
    modalities: Optional[List[str]] = Field(None, description="Supported modalities")
    api_key: Optional[str] = Field(None, description="API key (stored encrypted)")
    base_url: Optional[str] = Field(None, description="Base URL")
    endpoint: Optional[str] = Field(None, description="Endpoint URL")
    api_version: Optional[str] = Field(None, description="API version")
    endpoint_llm: Optional[str] = Field(None, description="LLM endpoint")
    endpoint_embedding: Optional[str] = Field(None, description="Embedding endpoint")
    endpoint_stt: Optional[str] = Field(None, description="STT endpoint")
    endpoint_tts: Optional[str] = Field(None, description="TTS endpoint")
    project: Optional[str] = Field(None, description="Project ID")
    location: Optional[str] = Field(None, description="Location")
    credentials_path: Optional[str] = Field(None, description="Credentials path")
    num_ctx: Optional[int] = Field(
        None, description="Context window size (Ollama only; defaults to 8192)"
    )


class CredentialResponse(BaseModel):
    """Response for a credential (never includes api_key)."""

    id: str
    name: str
    provider: str
    modalities: List[str]
    base_url: Optional[str] = None
    endpoint: Optional[str] = None
    api_version: Optional[str] = None
    endpoint_llm: Optional[str] = None
    endpoint_embedding: Optional[str] = None
    endpoint_stt: Optional[str] = None
    endpoint_tts: Optional[str] = None
    project: Optional[str] = None
    location: Optional[str] = None
    credentials_path: Optional[str] = None
    num_ctx: Optional[int] = None
    has_api_key: bool = False
    created: str
    updated: str
    model_count: int = 0
    decryption_error: Optional[str] = None


class CredentialDeleteResponse(BaseModel):
    """Response for credential deletion."""

    message: str
    deleted_models: int = 0


class DiscoveredModelResponse(BaseModel):
    """A model discovered from a provider."""

    name: str
    provider: str
    model_type: Optional[str] = None
    description: Optional[str] = None


class DiscoverModelsResponse(BaseModel):
    """Response from model discovery."""

    credential_id: str
    provider: str
    discovered: List[DiscoveredModelResponse]


class RegisterModelData(BaseModel):
    """A model to register with user-specified type."""

    name: str
    provider: str
    model_type: str  # Required: user specifies the type


class RegisterModelsRequest(BaseModel):
    """Request to register discovered models."""

    models: List[RegisterModelData]


class RegisterModelsResponse(BaseModel):
    """Response from model registration."""

    created: int
    existing: int


class NotebookDeletePreview(BaseModel):
    notebook_id: str = Field(..., description="ID of the notebook")
    notebook_name: str = Field(..., description="Name of the notebook")
    note_count: int = Field(..., description="Number of notes that will be deleted")
    exclusive_source_count: int = Field(
        ..., description="Number of sources only in this notebook"
    )
    shared_source_count: int = Field(
        ..., description="Number of sources shared with other notebooks"
    )


class NotebookDeleteResponse(BaseModel):
    message: str = Field(..., description="Success message")
    deleted_notes: int = Field(..., description="Number of notes deleted")
    deleted_sources: int = Field(..., description="Number of exclusive sources deleted")
    unlinked_sources: int = Field(
        ..., description="Number of sources unlinked from notebook"
    )
