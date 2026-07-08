import type { ContextSelections } from '@/lib/types/notebook-context'

export interface NotebookResponse {
  id: string
  name: string
  description: string
  archived: boolean
  created: string
  updated: string
  source_count: number
  note_count: number
  // Notebook-wide chat-gallery tag → color-key map (lowercased tag → palette key).
  chat_tag_colors?: Record<string, string>
  // Per-notebook auto-illustrate toggle (chat-foundation F6). Absent on old
  // notebooks → treated as ON (backend default true).
  auto_illustrate?: boolean
}

export interface NoteResponse {
  id: string
  title: string | null
  content: string | null
  note_type: string | null
  created: string
  updated: string
}

export interface SourceListResponse {
  id: string
  title: string | null
  topics?: string[]                  // Make optional to match Python API
  asset: {
    file_path?: string
    url?: string
  } | null
  embedded: boolean
  embedded_chunks: number            // ADD: From Python API
  insights_count: number
  created: string
  updated: string
  file_available?: boolean
  // ADD: Async processing fields from Python API
  command_id?: string
  status?: string
  processing_info?: Record<string, unknown>
}

export interface SourceDetailResponse extends SourceListResponse {
  full_text: string
  notebooks?: string[]  // List of notebook IDs this source is linked to
  // Document Foundation Track C (C2): chapter-tree presence/count, mirrors
  // backend SourceResponse.has_sections/sections_count exactly.
  has_sections?: boolean
  sections_count?: number
}

export type SourceResponse = SourceDetailResponse

// Document Foundation Track C (C2): chapter tree returned by
// GET /sources/{id}/sections. Mirrors the backend `SourceSectionNode` /
// `SourceSectionResponse` (api/models.py) exactly — snake_case field names.
export interface SourceSectionNode {
  id: string
  title: string
  level: number
  order: number
  page_start?: number
  page_end?: number
  summary?: string
  content?: string
  children: SourceSectionNode[]
}

export interface SourceSectionResponse {
  id: string
  title: string
  has_sections: boolean
  sections_count: number
  sections: SourceSectionNode[]
}

// Document Foundation Phase4: PDF highlight annotation. `rect` mirrors the
// backend's opaque `List[Dict]` — each entry is a `@react-pdf-viewer/highlight`
// `HighlightArea` ({ pageIndex, left, top, width, height }, percentages 0-100).
export interface AnnotationRect {
  pageIndex: number
  left: number
  top: number
  width: number
  height: number
}

export interface Annotation {
  id: string
  source_id: string
  page: number
  rect: AnnotationRect[]
  color: string
  note?: string | null
  quote?: string | null
  tags: string[]
  // Block-substrate anchor (pdf-block-ingestion Track D1/D3, Decision #13).
  // Mirrors the backend AnnotationResponse exactly: the anchor is server-resolved
  // from rect+quote at create time. `block_seq..block_end_seq` is the block RANGE
  // (equal for a single-block highlight); `anchor_start`/`anchor_end` are char
  // offsets (null for a geometric span or an atomic figure/table/equation).
  // `anchor_state` is DERIVED server-side (never stored): no block_seq → legacy;
  // anchor_gen !== source.parse_generation → stale; else anchored. Absent on
  // optimistic/mocked annotations → treated as legacy.
  block_seq?: number | null
  block_end_seq?: number | null
  anchor_start?: number | null
  anchor_end?: number | null
  anchor_gen?: number | null
  anchor_state?: AnchorState
  created: string
  updated: string
}

// Derived anchor lifecycle for a highlight (mirrors AnnotationResponse.anchor_state).
export type AnchorState = 'anchored' | 'stale' | 'legacy'

// Parse lifecycle of a source's current generation. `pending`/`parsing`/
// `embedding` are transient (poll); `ready`/`failed` are terminal. Mirrors the
// `parse_status` column written by commands/block_commands.py.
export type ParseStatus = 'pending' | 'parsing' | 'embedding' | 'ready' | 'failed'

// One typed block (pdf-block-ingestion Track C — db-design §2.1). Mirrors the
// backend `BlockResponse`: the overlay projection fills only seq/type/page/bbox/
// parent_seq/level; text/latex/section_path/table_data and the derived
// `image_url` appear only on text/full/window projections (omitted fields are
// absent, not null, because the API serializes with response_model_exclude_none).
export interface Block {
  seq: number
  type: string
  page?: number
  // Normalized page-fraction box [x0, y0, x1, y1] in 0..1 (overlay projection).
  bbox?: number[]
  parent_seq?: number
  level?: number
  section_path?: string[]
  text?: string
  latex?: string
  // Path to the crop PNG, e.g. "/api/sources/{id}/blocks/{seq}/image".
  image_url?: string
  table_data?: Record<string, unknown>
}

// One page's blocks in reading (seq) order (GET /sources/{id}/blocks).
export interface PageBlocksResponse {
  page: number
  gen: number
  blocks: Block[]
}

// A page-span of blocks with full text, for the markdown reader (pdf-block-
// ingestion Track D6, db-design §3a). Mirrors the backend `BlockSpanResponse`
// exactly. `start_page`/`end_page` reflect the CLAMPED bounds actually served
// (GET /sources/{id}/blocks/span caps a request at 10 pages).
export interface BlockSpanResponse {
  gen: number
  start_page: number
  end_page: number
  blocks: Block[]
}

// One heading entry in a parsed source's outline (mirrors the backend
// `section_index` dicts written by `open_notebook/parsers/base.py::finalize`).
// `subtree_end` is the last seq nested under this heading (its subtree range
// is `[seq, subtree_end]`) — absent/undefined on older/degenerate data.
export interface SectionIndexEntry {
  seq: number
  level: number
  title: string
  subtree_end?: number
}

// Parse status header for a source's current generation (GET /sources/{id}/parse).
// Mirrors the backend `ParseStatusResponse`. 404 when the source was never
// parsed — the frontend hook surfaces that as an error (→ legacy/unparsed UI).
export interface ParseStatusResponse {
  parse_status?: ParseStatus | string
  gen: number
  parser_name?: string
  parser_version?: string
  block_count?: number
  page_count?: number
  section_index?: SectionIndexEntry[]
  error?: string
}

export interface CreateAnnotationRequest {
  page: number
  rect: AnnotationRect[]
  color?: string
  note?: string | null
  quote?: string | null
  tags?: string[]
}

export interface UpdateAnnotationRequest {
  note?: string | null
  color?: string | null
  // Omit to leave tags unchanged; pass a list (incl. []) to replace the set.
  tags?: string[]
}

export interface SourceStatusResponse {
  status?: string
  message: string
  processing_info?: Record<string, unknown>
  command_id?: string
}

export interface SettingsResponse {
  default_content_processing_engine_doc?: string
  default_content_processing_engine_url?: string
  default_embedding_option?: string
  auto_delete_files?: string
  youtube_preferred_languages?: string[]
}

export interface CreateNotebookRequest {
  name: string
  description?: string
}

export interface UpdateNotebookRequest {
  name?: string
  description?: string
  archived?: boolean
  // Replaces the notebook's chat-gallery tag → color-key map wholesale.
  chat_tag_colors?: Record<string, string>
  // Per-notebook auto-illustrate toggle (chat-foundation F6/B6).
  auto_illustrate?: boolean
}

export interface NotebookDeletePreview {
  notebook_id: string
  notebook_name: string
  note_count: number
  exclusive_source_count: number
  shared_source_count: number
}

export interface NotebookDeleteResponse {
  message: string
  deleted_notes: number
  deleted_sources: number
  unlinked_sources: number
}

export interface CreateNoteRequest {
  title?: string
  content: string
  note_type?: string
  notebook_id?: string
}

export interface CreateSourceRequest {
  // Backward compatibility: support old single notebook_id
  notebook_id?: string
  // New multi-notebook support
  notebooks?: string[]
  // Required fields
  type: 'link' | 'upload' | 'text'
  url?: string
  file_path?: string
  content?: string
  title?: string
  transformations?: string[]
  embed?: boolean
  delete_source?: boolean
  // New async processing support
  async_processing?: boolean
}

export interface UpdateNoteRequest {
  title?: string
  content?: string
  note_type?: string
}

export interface UpdateSourceRequest {
  title?: string
  type?: 'link' | 'upload' | 'text'
  url?: string
  content?: string
}

export interface APIError {
  detail: string
}

// Structured citations (Plan D / Chunk 9). Mirrors the backend `Citation`
// (api/routers/chat.py) exactly: `id` is the full record id WITH its type prefix
// (e.g. "source:abc123"); strip the prefix before passing to openModal/
// handleReferenceClick, which expect the bare id. `page` is the pdf-viewer hook.
export interface Citation {
  id: string
  type: 'source' | 'note' | 'source_insight'
  number: number
  title?: string
  snippet?: string
  page?: number
}

// Tool-use disclosure (Plan D / Chunk 10). Mirrors the backend
// `ToolUseDisclosure` (api/routers/chat.py) exactly. Present only on AI messages
// produced by the Claude Agent path; `null`/absent on Esperanto and old sessions
// → the UI renders nothing in that case.
export interface ToolUseDisclosure {
  id: string
  tool_name: string
  tool_input: Record<string, unknown>
  tool_result?: string
  is_error?: boolean
}

// Image/video attachment (Plan D / Chunk 12). Mirrors the backend `MediaItem`
// (api/routers/chat.py) exactly. `url` is the fetchable path served by
// `GET /chat/media/{file}` (e.g. "/api/chat/media/abc.png"); prefix it with the
// resolved API base to render. Returned by `POST /chat/media`, staged in the
// composer (WorkspaceChat.pending), then carried onto a message's `media[]`.
export interface MediaItem {
  type: 'image' | 'video'
  url: string
  label: string // original filename, shown monospace
  duration?: string // video only, "m:ss"
}

// Source Chat Types
// Base session interface with common fields
export interface BaseChatSession {
  id: string
  title: string
  created: string
  updated: string
  message_count?: number
  model_override?: string | null
  // Sub-chat fields (Plan D / Chunk 11). Persisted on the backend ChatSession;
  // present on a chat spun off from a highlighted passage. Used to re-hydrate the
  // popped/anchored sub-chat panel after a reload (the workspace store is
  // ephemeral). `parent_session_id` is the chat it was spun off from; `quote` is
  // the highlighted passage.
  parent_session_id?: string | null
  quote?: string | null
  // User-assigned grouping tags (many per chat). Drives the gallery's group
  // filter + search. Absent/empty on untagged or old sessions.
  tags?: string[]
  // Per-chat context selection (chat-foundation F1/B4). `null`/absent = inherit
  // the notebook's global drawer selection; an object = this chat's own selection.
  context_config?: ContextSelections | null
}

export interface SourceChatSession extends BaseChatSession {
  source_id: string
  model_override?: string
}

// One structured annotation reference carried by a chat message (pdf-block-
// ingestion Track D2). Mirrors the backend `AnnotationRef` (api/routers/
// source_chat.py) exactly: persisted on the HUMAN message when the user
// referenced annotations, and surfaced on the session-GET payload so the UI can
// render reference pills (Track D4). `block_seq` is null for a legacy (un-
// anchored) highlight; `page` is 1-indexed.
export interface AnnotationRef {
  id: string
  quote?: string | null
  block_seq?: number | null
  page?: number | null
}

export interface SourceChatMessage {
  id: string
  type: 'human' | 'ai'
  content: string
  timestamp?: string
  // Structured citations / follow-ups resolved by the backend (AI messages;
  // absent on old sessions → inline-marker fallback). Plan D / Chunk 9.
  citations?: Citation[]
  followups?: string[]
  // Structured annotation references (pdf-block-ingestion Track D2/D4). Present
  // on the HUMAN turn that referenced highlights; the UI renders them as pills
  // (AnnotationReferences). Absent when no annotations were referenced.
  annotation_refs?: AnnotationRef[]
  // Claude Agent tool-use disclosure (AI messages; null/absent on the Esperanto
  // path and old sessions). Plan D / Chunk 10.
  tool_uses?: ToolUseDisclosure[]
  // Image/video attachments (Plan D / Chunk 12). On human turns these are what the
  // user attached; AI messages echo `[]`. Absent on old sessions.
  media?: MediaItem[]
  // Background-jobs C1: optimistic placeholders inserted by C2/C3 while the
  // worker generates. `pending` shows a spinner; `error` shows a failure bubble.
  // Never present on messages fetched from the backend.
  pending?: boolean
  error?: boolean
}

export interface SourceChatContextIndicator {
  sources: string[]
  insights: string[]
  notes: string[]
}

export interface SourceChatSessionWithMessages extends SourceChatSession {
  messages: SourceChatMessage[]
  context_indicators?: SourceChatContextIndicator
}

export interface CreateSourceChatSessionRequest {
  source_id: string
  title?: string
  model_override?: string
}

export interface UpdateSourceChatSessionRequest {
  title?: string
  model_override?: string
}

export interface SendMessageRequest {
  message: string
  model_override?: string
  // Annotation IDs the user is referencing (pdf-block-ingestion Track D2/D4).
  // Each is resolved into the AI context and recorded as a cites_annotation
  // edge; the resolved refs come back on the human message as `annotation_refs`.
  annotation_ids?: string[]
}

export interface SourceChatStreamEvent {
  type: 'user_message' | 'ai_message' | 'context_indicators' | 'complete' | 'error'
  content?: string
  data?: unknown
  message?: string
  timestamp?: string
}

// Notebook Chat Types
export interface NotebookChatSession extends BaseChatSession {
  notebook_id: string
}

// Token usage reported by the model for an AI turn (chat-foundation frozen
// contract #9, N2/N3). Only the claude-agent path populates this; local /
// Esperanto models report nothing (null/absent), so every field is optional.
export interface UsageInfo {
  input_tokens?: number
  output_tokens?: number
  cache_read_input_tokens?: number
  cache_creation_input_tokens?: number
  model?: string
  context_window?: number
}

export interface NotebookChatMessage {
  id: string
  type: 'human' | 'ai'
  content: string
  timestamp?: string
  // Structured citations / follow-ups resolved by the backend (AI messages;
  // absent on old sessions → inline-marker fallback). Plan D / Chunk 9.
  citations?: Citation[]
  followups?: string[]
  // Claude Agent tool-use disclosure (AI messages; null/absent on the Esperanto
  // path and old sessions). Plan D / Chunk 10.
  tool_uses?: ToolUseDisclosure[]
  // Ground-truth token usage for this AI turn (chat-foundation N2, frozen
  // contract #9). Null/absent on the Esperanto path and old sessions.
  usage?: UsageInfo | null
  // Image/video attachments (Plan D / Chunk 12). On human turns these are what the
  // user attached; AI messages echo `[]`. Absent on old sessions.
  media?: MediaItem[]
  // Background-jobs C1: optimistic placeholders inserted by C2 while the
  // worker generates. `pending` shows a spinner; `error` shows a failure bubble.
  // Never present on messages fetched from the backend.
  pending?: boolean
  error?: boolean
}

export interface NotebookChatSessionWithMessages extends NotebookChatSession {
  messages: NotebookChatMessage[]
}

export interface CreateNotebookChatSessionRequest {
  notebook_id: string
  title?: string
  model_override?: string
  // Sub-chat creation (Plan D / Chunk 11): set both to spawn a chat anchored to a
  // highlighted passage of its parent. Mirrors the backend CreateSessionRequest.
  parent_session_id?: string
  quote?: string
  tags?: string[]
  // Per-chat context selection (chat-foundation F1/F2). Seed `{sources:{},notes:{}}`
  // for a quote-only side chat; omit/null to inherit the notebook default.
  context_config?: ContextSelections | null
}

export interface UpdateNotebookChatSessionRequest {
  title?: string
  model_override?: string | null
  // Promote a side chat to a main chat by clearing its parent/quote (Sidebar
  // redesign / Chunk 1). Backend update_session applies these via exclude_unset
  // and they're in ChatSession.nullable_fields, so PUT-ing null clears them.
  parent_session_id?: string | null
  quote?: string | null
  // Replaces the session's grouping tags wholesale.
  tags?: string[]
  // Per-chat context selection (chat-foundation F1/B4). PUT an object to set this
  // chat's own selection; PUT `null` to reset to the notebook default (inherit).
  context_config?: ContextSelections | null
}

export interface SendNotebookChatMessageRequest {
  session_id: string
  message: string
  context: {
    sources: Array<Record<string, unknown>>
    notes: Array<Record<string, unknown>>
  }
  model_override?: string
  // Image/video attachments for this turn (Plan D / Chunk 12). Mirrors the
  // backend ExecuteChatRequest.media.
  media?: MediaItem[]
}

export interface ExecuteChatJobResponse {
  job_id: string
  session_id: string
  messages: NotebookChatMessage[]  // compat shim: Track C (C2) removes this access; backend omits it
}

export interface BuildContextRequest {
  notebook_id: string
  context_config: {
    sources: Record<string, string>
    notes: Record<string, string>
  }
}

export interface BuildContextResponse {
  context: {
    sources: Array<Record<string, unknown>>
    notes: Array<Record<string, unknown>>
  }
  token_count: number
  char_count: number
}

// Background-jobs A4: row shape returned by GET /commands/jobs and
// GET /commands/active. Used by commandsApi.listActive() and commandsApi.getJob().
export interface CommandJobSummary {
  job_id: string
  name: string
  status: string
  result?: Record<string, unknown> | null
  error_message?: string | null
  created?: string | null
  updated?: string | null
  args?: Record<string, unknown> | null
  /**
   * Live per-job phase written by long-running commands (e.g. ingest).
   * `tool_name`/`tool_input` are set by the chat tool loop (see
   * open_notebook.graphs.chat) so the chat UI can render a localized,
   * icon-matched label via ToolUseDisclosure's `describeTool`/`detailFor`
   * instead of the raw English `phase` string.
   */
  progress?: { phase?: string; tool_name?: string; tool_input?: Record<string, unknown> } | null
}

// Notebook Multi-Chat Workspace (Plan C) — client-only per-chat workspace state.
// A "chat" maps onto an existing chat session (Decision 5/8): title + messages
// come from the session/useNotebookChat; these fields live only in Zustand.
// `parentId`/`quote` mirror the persisted sub-chat fields. `pending` holds media
// already uploaded via POST /chat/media (Plan D / Chunk 12) and staged in the
// composer until the next send moves it onto the message's `media[]`.
export interface WorkspaceChat {
  id: string // session id
  // Sidebar redesign (Chunk 2): is this chat rendered at all? false → it's only
  // listed in the sidebar (main chats) or reachable via the side-chats control.
  // true → rendered in the dock (active main) or as a popped panel in the track.
  open: boolean
  docked: boolean // among open chats: true → shown in the dock; false → popped panel in the track
  width: number // popped panel width in px (Chunk 8)
  draft: string // current composer text
  pending: MediaItem[] // uploaded attachments staged in the composer (Chunk 12)
  parentId: string | null // id of the chat this was spun off from (Plan D sub-chats)
  quote: string | null // the highlighted passage that seeded this sub-chat (Plan D)
}
