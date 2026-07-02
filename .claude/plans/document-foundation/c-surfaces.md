# Document Foundation — Track C: Surfaces (sections API + TOC viewer + interaction layer)

> **Self-contained plan for ONE chat.** Read `coordinator.md` (this directory) first — shared
> decisions, conventions, concurrency, file ownership — then execute this track's chunks here,
> one per session. **Track A must be fully ☑ before starting any C chunk.**
> **Location:** `.claude/plans/document-foundation/c-surfaces.md` → archived with the directory
> when all tracks ☑.

## SESSION HANDOFF — resume here

**Track deps:** **Track A must be fully ☑** (needs `Source.get_sections()`, the `source_section`
domain model, and the sections API endpoint). Check the coordinator's Global status table before
starting a single chunk.

**Concurrent with:** **Track B** and **Phase3** — safe to run at the same time. C touches only
`api/routers/sources/`, `api/models.py`, and `frontend/*`; B touches backend
domain/graphs/commands/ai. No shared files between B and C.

**Paste-able resume prompt (run in a fresh chat):**
```
Read .claude/plans/document-foundation/coordinator.md then
.claude/plans/document-foundation/c-surfaces.md in full. Confirm Track A is fully ☑ in the
coordinator before starting. Implement the next unstarted chunk (one only — derive from the Status
table + `git log --oneline -30`, respecting C1 → C2 → C3 → C4 order). Verify: uv run pytest
tests/test_models_api.py (backend chunks); npm run build (frontend chunks). Commit (one chunk =
one commit). Update BOTH this file's Status table AND the coordinator's Global status table +
Changelog. Announce "✅ Chunk C.n complete — safe to clear context. Next: C.(n+1)" and stop.
```

**State at handoff (2026-06-26):** Plan authored; no chunks started. Track A not yet started.

---

## This track's file ownership

Creates/modifies (Track C only):

| File | Chunk | What changes |
|------|-------|-------------|
| `api/routers/sources/sections.py` | C1 | New file: GET /sources/{id}/sections endpoint |
| `api/routers/sources/__init__.py` | C1 | Import + register sections router |
| `api/models.py` | C1 | Add SourceSectionNode, SourceSectionResponse; add has_sections/sections_count to SourceResponse |
| `frontend/src/lib/types/api.ts` | C2 | Add SourceSectionNode, SourceSectionResponse types; add has_sections?/sections_count? to SourceDetailResponse |
| `frontend/src/lib/api/sources.ts` | C2 | Add sourcesApi.getSections(id) |
| `frontend/src/components/source/detail/SourceContentTab.tsx` | C3 | Add TOC + per-chapter chapter rendering (replaces flat full_text render for chaptered sources) |
| `frontend/src/components/source/detail/SourceTOC.tsx` | C3 | New component: sticky TOC tree |
| `frontend/src/lib/locales/*/` | C3, C4 | Append-only locale keys |
| `frontend/src/components/notebooks/workspace/PassageSelectionMenu.tsx` | C4 | Extend: add Explain/Save-note actions |
| `frontend/src/components/source/detail/SourceTOC.tsx` | C4 | Extend: add per-chapter Summarize/Quiz buttons |

**Do NOT touch** `open_notebook/domain/notebook.py`, `graphs/`, `commands/`, `ai/` — Track A/B own those.
**`api/models.py`** is owned by C (C1 adds section models). Track B does not touch `api/models.py`.

**Post-refactor path notes (confirmed 2026-06-26):**
- `api/routers/sources/` is a **package**: `__init__.py`, `create.py`, `crud.py`, `_helpers.py`, `insights.py`.
- `SourceDetailContent.tsx` is at `frontend/src/components/source/detail/SourceDetailContent.tsx`.
- `SourceContentTab.tsx` is at `frontend/src/components/source/detail/SourceContentTab.tsx` — this is where the `ReactMarkdown` render lives (line 87–110); **C3 anchors here**.
- `useSourceDetail` hook is at `frontend/src/lib/hooks/useSourceDetail.ts`.
- `PassageSelectionMenu.tsx` is at `frontend/src/components/notebooks/workspace/PassageSelectionMenu.tsx` — **C4 extends this**.

---

## Per-chunk workflow

read coordinator + referenced files → implement → verify → mark ☑ here AND in coordinator →
note new Open Questions → commit → announce "✅ Chunk C.n complete — safe to clear context" → stop.

---

## Status table (this track)

| Chunk | Title | Status | Notes |
|------:|-------|--------|-------|
| C1 | GET /sources/{id}/sections + schemas + has_sections flag | ☐ | Needs A ☑; sources.py is a package |
| C2 | Frontend types + getSections API client | ☑ | commit 22eca7c (wave5 2026-07-02); types + getSections client. tsc clean. ⚠ `title` non-optional per spec vs nullable backend — C3 tolerate null |
| C3 | TOC sidebar + per-chapter rendering (SourceContentTab) | ☑ | commit 887bf95 (wave5b 2026-07-02); SourceTOC.tsx + two-col SourceContentTab (single ReactMarkdown reused), content via getSections(id,true), fallback preserved, null-title tolerated, 3 keys ×14. tsc clean. Anchors + getSectionPageRangeLabel ready for C4. ⚠ visual spot-check parked |
| C4 | Interaction: selection actions + per-chapter AI + citation→section jump | ☐ | |

Legend: ☐ todo · ◐ in progress · ☑ done · ⏸ blocked

---

## Changelog (this track)

- _(none yet.)_

---

## Chunks (verbatim)

---

### Chunk C1 — GET /sources/{id}/sections + schemas + has_sections flag

**Goal:** Expose the chapter tree over REST and signal its presence on the source detail, without
breaking any existing endpoints.

**Read first:**
- `api/routers/sources/__init__.py` — how the existing sub-routers are imported and assembled
- `api/routers/sources/crud.py` — the `GET /sources/{id}` handler (find it; study response build + 404/500 pattern)
- `api/models.py` — `SourceResponse` (359–376), `SourceListResponse` (378–393), `AssetModel` (302–304)
- `api/main.py` line ~303 — router registration (confirm sources router is registered as `sources.router` or similar)
- `Source.get_sections()` + `Source.get_outline()` from Track A3 (read their return shapes)

**Spec / exact values:**

New `api/models.py` types:
```python
class SourceSectionNode(BaseModel):
    id: str
    title: str
    level: int
    order: int
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    summary: Optional[str] = None
    content: Optional[str] = None   # only included when explicitly requested
    children: List["SourceSectionNode"] = []

SourceSectionNode.model_rebuild()  # needed for self-referential models

class SourceSectionResponse(BaseModel):
    id: str
    title: str
    has_sections: bool
    sections_count: int
    sections: List[SourceSectionNode] = []
```

Add to `SourceResponse`:
```python
has_sections: bool = False
sections_count: int = 0
```

New `api/routers/sources/sections.py`:
```python
from fastapi import APIRouter, HTTPException
from open_notebook.domain.notebook import Source
from api.models import SourceSectionResponse, SourceSectionNode

router = APIRouter()

@router.get("/{source_id}/sections", response_model=SourceSectionResponse)
async def get_source_sections(source_id: str, include_content: bool = False):
    source = await Source.get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    sections = await source.get_sections()   # full nested tree from A3
    # Build SourceSectionNode tree
    # summary always included; content only when include_content=True (keep payload light)
    ...
    return SourceSectionResponse(
        id=source_id,
        title=source.title,
        has_sections=len(sections) > 0,
        sections_count=len(sections),
        sections=section_nodes,
    )
```

Wire in `api/routers/sources/__init__.py`: import sections router and include it with the same prefix as the other sub-routers.

Populate `has_sections` / `sections_count` in `GET /sources/{id}` response (`crud.py`): call `Source.get_sections()` or a cheaper count query.

**Verify:**
1. `GET /sources/{id}/sections` returns a nested tree for a chaptered PDF source.
2. `GET /sources/{id}/sections` returns `{has_sections: false, sections: []}` for an unchaptered source.
3. `/docs` (FastAPI Swagger) lists the new endpoint.
4. Existing `GET /sources/{id}` and `GET /sources` are unchanged.
5. `uv run pytest tests/test_models_api.py` — green.

---

### Chunk C2 — Frontend types + getSections API client

**Goal:** Mirror the new REST contract in TypeScript and add the client function, so C3 can fetch
sections.

**Read first:**
- `frontend/src/lib/types/api.ts` lines 21–46 — `SourceListResponse`, `SourceDetailResponse`
- `frontend/src/lib/api/sources.ts` — existing `get`, `list`, `downloadFile`, API client pattern

**Spec / exact values:**

Add to `frontend/src/lib/types/api.ts`:
```typescript
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
```

Add to `SourceDetailResponse` (in the same file):
```typescript
has_sections?: boolean
sections_count?: number
```

Add to `frontend/src/lib/api/sources.ts`:
```typescript
getSections: (id: string, includeContent = false) =>
  apiClient.get<SourceSectionResponse>(
    `/sources/${id}/sections${includeContent ? '?include_content=true' : ''}`
  ).then(r => r.data),
```

**Verify:**
1. `npm run build` passes (no TypeScript errors).
2. Type names match the backend field names exactly (snake_case on backend; TypeScript mirrors them).

---

### Chunk C3 — TOC sidebar + per-chapter rendering (SourceContentTab)

**Goal:** Replace the single-blob render with a navigable chapter view: a TOC outline + one chapter
rendered at a time, reusing the existing ReactMarkdown renderer. Falls back to the flat `full_text`
render when a source has no sections.

**Read first:**
- `frontend/src/components/source/detail/SourceContentTab.tsx` (full file) — the `ReactMarkdown` + `remarkGfm` + custom-components block at lines 87–110 renders `source.full_text`. This is WHERE C3 adds TOC + chapter selection.
- `frontend/src/components/source/detail/SourceDetailContent.tsx` lines 27–50 — tab structure, `useSourceDetail` import; understand which props/data are available in SourceContentTab.
- `frontend/src/lib/hooks/useSourceDetail.ts` — what it returns (confirm `source` object is available).
- `frontend/src/lib/api/sources.ts` — `getSections` from C2.
- Coordinator Decision #9 (render cleaned content default), Convention (reuse existing ReactMarkdown block).

**Spec / exact values:**

1. **`SourceTOC.tsx`** (new at `frontend/src/components/source/detail/SourceTOC.tsx`):
   - Props: `sections: SourceSectionNode[]`, `activeSectionId: string | null`, `onSectionClick: (id: string) => void`
   - Renders a sticky, collapsible tree (by `level`): one row per section showing title + page range
   - Each row has `data-section-id={section.id}` for scroll targets
   - Clicking a row calls `onSectionClick(section.id)`
   - Collapsible nesting: level-2+ sections collapse under their parent
   - Styling: `Shadcn` `ScrollArea` or plain `overflow-y-auto`; `cn()` for active highlight

2. **`SourceContentTab.tsx`** modifications:
   - Add a TanStack Query call: `const { data: sectionsData } = useQuery({ queryKey: ['sections', source.id], queryFn: () => sourcesApi.getSections(source.id) })`
   - If `sectionsData?.has_sections`:
     - Show `SourceTOC` on the left (or above on mobile)
     - Show the active chapter's content (cleaned_content when available, else content) via the EXISTING `ReactMarkdown` block (don't add a second renderer — just change what string it receives)
     - Add `data-section-id` on the heading components to enable citation-jump scrolling (C4)
     - State: `const [activeSectionId, setActiveSectionId] = useState(sections[0]?.id ?? null)`
     - Chapter content = `activeSection.content` from `sectionsData.sections` (or a lazy fetch with `include_content=true` if content wasn't inlined)
   - If `!sectionsData?.has_sections` (or loading): render as today (`source.full_text`)
   - Add locale keys for any new labels (TOC header, "Loading chapters...", "No chapters", etc.)

3. **Layout guidance:** the Content tab card is the parent — add a two-column flex/grid inside `CardContent` when sections are present: TOC (sticky, ~250px) + chapter body (flex-1). Single column when no sections.

**Verify:**
1. A chaptered textbook source shows a TOC; clicking a chapter shows that chapter's content rendered cleanly.
2. An unchaptered/web-page source still renders as today (no TOC, `full_text` render).
3. `npm run build` passes.
4. Locale keys present in all `frontend/src/lib/locales/*/` files.

---

### Chunk C4 — Interaction layer: selection actions + per-chapter AI actions + citation→jump

**Goal:** Make the document interactive — extend the existing selection gesture into an action menu,
add per-chapter AI action buttons, and make citation clicks scroll to the right chapter anchor.
**Annotations/highlights are OUT** (deferred to Phase4 — do not build them).

**Read first:**
- `frontend/src/components/notebooks/workspace/PassageSelectionMenu.tsx` (full file) — LANDED; currently has "Chat about this" sub-chat spawn; understand its selection gesture + item list structure
- `frontend/src/components/source/chat/ChatPanel.tsx` lines ~121–135 — `handleReferenceClick` (openModal), citation click handler
- `frontend/src/lib/utils/source-references.tsx` — existing `[source:id]` ref parser (Phase3 extends it for `#p=N`; C4 adds section-scroll)
- `frontend/src/components/source/detail/SourceTOC.tsx` (from C3) — `data-section-id` anchors
- Coordinator Decision #10 (annotations OUT)

**Spec / exact values:**

1. **Extend `PassageSelectionMenu.tsx`** — add two new items alongside "Chat about this":
   - **Explain** — sends a scoped "Explain this passage: [selected text]" message to the current chat session (same pattern as "Chat about this" but with a different prompt prefix)
   - **Save note** — creates a new Note with the selected text as content; wire to the existing note-create mutation

2. **Per-chapter action buttons** in `SourceTOC.tsx` (extend C3's component):
   - Add a small `...` / `⋮` icon button on hover for each chapter row
   - Menu items: **Summarize** → sends "Summarize section: [section title]" to chat; **Quiz me** → sends "Quiz me on section: [section title]" to chat
   - Use the existing chat dispatch mechanism (same `sendMessage`/sub-chat pattern as PassageSelectionMenu)

3. **Citation → section scroll:** In `SourceContentTab.tsx` (or `source-references.tsx`), wire citation clicks that carry a section context:
   - When `ChatPanel.handleReferenceClick(type="source", id=sourceId)` fires and the source detail is open, check if the citation `id` maps to a known section id (from `sectionsData`) — if so, scroll to `document.querySelector('[data-section-id="<id>"]')`.
   - Keep the existing `openModal` fallback when no section anchor is found.

4. **Locale keys** for "Explain", "Save note", "Summarize", "Quiz me".

**Constraints:**
- Do NOT build annotations (highlight rects, comment bubbles) — that is Phase4.
- Reuse `PassageSelectionMenu`'s existing selection gesture; do not rebuild it.
- Reuse the existing sub-chat spawn logic; do not duplicate chat dispatch.

**Verify:**
1. Selecting text in the source detail shows the action menu with Explain / Chat about this / Save note.
2. "Explain" sends a scoped message to the current chat.
3. "Save note" creates a note with the selected text.
4. A chapter's Summarize/Quiz button drives the chat with a scoped message.
5. Clicking a citation scroll-jumps to the correct `data-section-id` anchor.
6. Annotations are absent (correctly deferred — no highlight rects, no comment bubbles).
7. `npm run build` passes.

---

## Open Questions (this track)

- **Q-section-content-payload** — Inline `content` in the sections endpoint or lazy per-chapter fetch? Default: `summary` always inline, `content` only on demand (`include_content=true` query param). Revisit if it adds a UX-hurting round-trip.
- **Q-quiz-scope** — "Quiz me" output format: inline chat message vs. a saved note. Default: inline chat message; promote to a note later if wanted.
- **Q-c4-chat-scope** — C4's per-chapter actions need access to the chat send function. Confirm that `SourceTOC` can receive a `onSendMessage` prop from `SourceContentTab`, which gets it from the `useSourceDetail` hook or a chat context. Verify the data flow before implementing.
