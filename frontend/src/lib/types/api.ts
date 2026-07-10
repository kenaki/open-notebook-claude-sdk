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
  // E3: full_text is no longer shipped on GET /sources/{id}; fetch it lazily via
  // sourcesApi.getFullText (GET /sources/{id}/full-text) only when needed.
  full_text?: string
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
  // `page -> [first_seq, last_seq]`, indexed by `page - 1` (empty pages hold the
  // inverted range [0, -1]). See `lib/utils/page-index.ts` for the lookups.
  page_index?: number[][]
  section_index?: SectionIndexEntry[]
  error?: string
}

export interface CreateAnnotationRequest {
  // PDF-born path: page + rect (server resolves the block anchor from them).
  // Both optional so the reader-born path can omit them — the server derives
  // page + rect from the block range's bboxes (pdf-block-ingestion D7).
  page?: number
  rect?: AnnotationRect[]
  color?: string
  note?: string | null
  quote?: string | null
  tags?: string[]
  // Reader-born path (pdf-block-ingestion D7, db-design §2.3): the selected
  // block range + char offsets + quote. When `block_seq` is set the request is
  // reader-born; the server validates the range against the current parse
  // generation, derives page + rect, and sets anchor_gen. `anchor_start`/
  // `anchor_end` are null for a multi-block span or an atomic block.
  block_seq?: number
  block_end_seq?: number
  anchor_start?: number | null
  anchor_end?: number | null
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
  /** Block-parse lifecycle for PDF sources: pending/parsing/embedding/ready/failed */
  parse_status?: string
  /** Failed downstream pipeline jobs for the current run */
  failed_jobs?: Array<{ name: string; count: number; latest_error?: string | null }>
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
  // Owning source of this annotation (cross-interface-study Track B3). Always
  // present on notebook-chat refs (a notebook spans multiple sources, so the
  // ref can't rely on a single surface-level sourceId); optional on source-chat
  // refs, which fall back to the chat surface's own sourceId.
  source_id?: string
  quote?: string | null
  block_seq?: number | null
  page?: number | null
}

// A chat session that cites a given annotation, for the reverse "linked chats"
// view (cross-interface-study Track B4). Mirrors the backend
// `CitingSessionResponse`. `scope` is a strict union — orphan sessions with no
// `refers_to` edge are omitted server-side. `notebook_id`/`source_id` are the
// navigation targets (notebook-scope deep-links to the session; source-scope
// only navigates to the source, per study-memory's session-level nav depth).
export interface CitingSession {
  session_id: string
  title: string
  scope: 'notebook' | 'source'
  notebook_id?: string | null
  source_id?: string | null
  updated?: string | null
}

// Bulk per-annotation citing counts for a source's sidebar badges
// (cross-interface-study Track B4). Keys are full annotation record ids.
export interface CitingCountsResponse {
  counts: Record<string, number>
}

// One recall breadcrumb carried by an AI chat message (study-memory Track
// C1/B3). Mirrors the backend `RecallRef` contract (coordinator.md's
// Reconciliation section) verbatim: a metadata-only pointer to a prior chat
// exchange or the user's own annotation that's related to the current
// answer. Deliberately carries NO gist, note, or answer text — the spoiler
// guard is structural (two backend tools: search vs. full-content), not a UI
// choice, so this shape must never grow a content/gist field.
export interface RecallRef {
  kind: 'exchange' | 'annotation'
  title?: string | null
  session_id?: string | null
  scope?: 'source' | 'notebook' | null
  source_id?: string | null
  notebook_id?: string | null
  message_id?: string | null
  annotation_id?: string | null
  page?: number | null
  quote?: string | null
  similarity?: number
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
  // Persisted reasoning trace for this AI turn (agent-console track A/B10).
  // Optional/absent on old messages and non-thinking-capable models — the UI
  // renders nothing when unset.
  thinking?: string
  // Recall breadcrumbs to prior study material related to this answer
  // (study-memory Track C1/B3). AI turns only; absent when nothing relevant
  // was found or on old sessions. Never carries gist/note/answer text.
  recall_refs?: RecallRef[]
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
  // Structured annotation references (cross-interface-study Track B1/B3).
  // Present on the HUMAN turn that referenced highlights; the UI renders them
  // as pills (AnnotationReferences). Each ref carries `source_id` since a
  // notebook chat can reference annotations across multiple sources.
  annotation_refs?: AnnotationRef[]
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
  // Persisted reasoning trace for this AI turn (agent-console track A/B10).
  // Optional/absent on old messages and non-thinking-capable models — the UI
  // renders nothing when unset.
  thinking?: string
  // Recall breadcrumbs to prior study material related to this answer
  // (study-memory Track C1/B3). AI turns only; absent when nothing relevant
  // was found or on old sessions. Never carries gist/note/answer text.
  recall_refs?: RecallRef[]
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
  // Annotation IDs the user is referencing (cross-interface-study Track B1/B3).
  // Mirrors source chat's SendMessageRequest.annotation_ids: each is resolved
  // into the AI context and recorded as a cites_annotation edge; the resolved
  // refs come back on the human message as `annotation_refs`.
  annotation_ids?: string[]
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
   *
   * `partial_content` is the answer-so-far (thinking stripped), overwritten each
   * flush by the streaming graph so the chat bubble can render the reply
   * progressively instead of one-shot on completion.
   */
  progress?: {
    phase?: string
    tool_name?: string
    tool_input?: Record<string, unknown>
    partial_content?: string
  } | null
}

// Per-status job totals from GET /commands/jobs/counts — real table-wide
// counts (the list endpoint is capped, so row lengths saturate at the cap).
// Keys are backend statuses ('new' | 'running' | 'completed' | 'failed' |
// 'canceled') plus an 'all' sum; open-ended so a new backend status can't
// break the client.
export type JobCounts = Record<string, number>

// Agent console (agent-console B1): one entry of `progress.events[]` — mirrors
// the backend event contract exactly (see .claude/plans/agent-console/
// coordinator.md "Event contract"). JSON primitives only; append-only, capped
// server-side at 200 (thinking additionally capped at 150 + a truncation marker).
export type JobEvent = { t: string } & (
  | { type: 'phase'; label: string }
  | { type: 'tool_call'; tool_name: string; tool_input?: Record<string, unknown> }
  | { type: 'tool_result'; tool_name: string; preview?: string; is_error?: boolean }
  | { type: 'thinking'; text: string }
  | { type: 'context'; chars?: number; preview?: string }
  // Non-fatal: work the job declined to do while still completing (a verify
  // proof rejected as truncated, a section skipped as too large). The job's
  // status stays `completed`, so this event is the only signal in the console.
  | { type: 'warning'; message: string }
)

// Detail payload from GET /commands/jobs/{job_id} (agent-console B1). The
// console reads this query directly rather than through jobs-store, which
// only ever holds today's snapshot progress (coordinator Decision #9). List
// endpoints (`/commands/active`, `/commands/jobs`) strip `progress.events`
// server-side; only this detail shape carries the full event log.
export type CommandJobDetail = CommandJobSummary & {
  args?: Record<string, unknown>
  progress?: (CommandJobSummary['progress'] & { events?: JobEvent[] }) | null
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
  // Staged annotation refs from a panel Ask-AI (cross-interface-study / Chunk
  // A3): attaches to whatever the user next sends from this chat's composer,
  // then clears on a successful send. Undefined/absent = nothing staged.
  askRefs?: string[]
}
