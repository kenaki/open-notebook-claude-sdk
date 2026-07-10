"""Regression tests for to-fix/004 — verify/summarize output bounds.

Live incident (2026-07-09): verify_clean_section wrote whatever the vision
model returned straight to cleaned_content, and every reader prefers that
layer, so a truncated reply silently shortened the chapter everywhere (a
22,532-char Preface came back as 506 chars — 2% kept). The same pipeline also
proofed the book 2.6× over (fan-out over every tree node instead of leaves)
and generated prose summaries that consumers truncate to 300-char routing
blurbs (~80% of generated chars discarded).
"""

from contextlib import nullcontext
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from commands import summary_commands, verify_commands
from commands.summary_commands import (
    _MIN_SUMMARY_CHARS,
    SummarizeSectionInput,
    SummarizeSourceInput,
    _flatten_sections_for_abstract,
    _remaining_unsummarized,
    _summary_target_ids,
    summarize_section,
    summarize_source,
)
from commands.verify_commands import (
    VerifyCleanSectionInput,
    _leaf_section_ids,
    _output_truncation_reason,
    _verify_clean_section_impl,
)


def _response(content: str, **metadata):
    resp = MagicMock()
    resp.content = content
    resp.response_metadata = metadata
    return resp


# --- Finding 2: the output-sanity guard (pure helper) ------------------------


def test_length_stop_is_rejected_even_when_ratio_passes():
    """Ollama reports done_reason='length' when the reply hit max_tokens — the
    tail is missing no matter how much text came back."""
    reason = _output_truncation_reason(
        "x" * 1000, "x" * 1000, _response("irrelevant", done_reason="length")
    )
    assert reason is not None and "max_tokens" in reason


def test_openai_style_finish_reason_length_is_rejected():
    reason = _output_truncation_reason(
        "x" * 1000, "x" * 1000, _response("irrelevant", finish_reason="length")
    )
    assert reason is not None


def test_short_reply_is_rejected_without_a_length_stop():
    """The Preface case: 22,532 chars in, 506 out, clean stop reason."""
    reason = _output_truncation_reason(
        "x" * 506, "x" * 22532, _response("...", done_reason="stop")
    )
    assert reason is not None and "506" in reason


def test_plausible_shrink_passes():
    """Dropping running headers/footers legitimately loses a few percent."""
    assert _output_truncation_reason("x" * 950, "x" * 1000, _response("...")) is None


def test_expansion_passes():
    """Repairing tables/hyphenation adds characters (observed up to 177%)."""
    assert _output_truncation_reason("x" * 1770, "x" * 1000, _response("...")) is None


def test_empty_input_never_divides_by_zero():
    assert _output_truncation_reason("anything", "", _response("...")) is None
    assert _output_truncation_reason("anything", None, _response("...")) is None


def test_missing_metadata_falls_back_to_ratio_only():
    resp = MagicMock(spec=[])  # no response_metadata attribute at all
    resp.content = "x"
    assert _output_truncation_reason("x" * 999, "x" * 1000, resp) is None
    assert _output_truncation_reason("x" * 10, "x" * 1000, resp) is not None


# --- Finding 2: guard wired into the command ---------------------------------


def _verify_pipeline_mocks(section, source, reply):
    """Patch everything between 'section loaded' and 'model replied'."""
    vision_model = MagicMock()
    vision_model.to_langchain.return_value.ainvoke = AsyncMock(return_value=reply)
    return (
        patch("commands.verify_commands.SourceSection.get", AsyncMock(return_value=section)),
        patch("commands.verify_commands.Source.get", AsyncMock(return_value=source)),
        patch("commands.verify_commands._resolve_pdf_path", return_value="/tmp/x.pdf"),
        patch("commands.verify_commands._run_render", AsyncMock(return_value=[b"png"])),
        patch("commands.verify_commands.provision_vision_message", AsyncMock(return_value=MagicMock())),
        patch.object(
            verify_commands.model_manager,
            "get_vision_model",
            AsyncMock(return_value=vision_model),
        ),
        patch.object(
            verify_commands.model_manager,
            "get_defaults",
            AsyncMock(return_value=MagicMock(default_vision_model="model:v")),
        ),
        patch("commands.verify_commands.heavy_lane_for", AsyncMock(return_value=nullcontext())),
    )


def _section_mock(content: str):
    section = MagicMock()
    section.id = "source_section:s1"
    section.title = "Preface"
    section.content = content
    section.source = "source:x"
    section.page_start = 0
    section.page_end = 1
    section.save = AsyncMock()
    return section


def _source_mock():
    source = MagicMock()
    source.id = "source:x"
    source.parse_generation = 1
    source.page_offset = None
    source.add_insight = AsyncMock()
    return source


async def _run_verify(section, source, reply):
    """Drive _verify_clean_section_impl with the warning sink captured.

    `report_job_warning` is patched at the verify_commands namespace, which is
    also what `_record_verify_verdict` calls — so the returned mock is the single
    place any non-clean verdict surfaces in the UI.
    """
    mocks = _verify_pipeline_mocks(section, source, reply)
    with patch(
        "commands.verify_commands.report_job_warning", AsyncMock()
    ) as warn, mocks[0], mocks[1], mocks[2], mocks[3], mocks[4], mocks[5], mocks[6], mocks[7]:
        out = await _verify_clean_section_impl(
            VerifyCleanSectionInput(source_section_id="source_section:s1")
        )
    return out, warn


@pytest.mark.asyncio
async def test_truncated_proof_is_rejected_not_persisted():
    section = _section_mock("x" * 20000)
    source = _source_mock()
    out, warn = await _run_verify(section, source, _response("y" * 500))

    assert out.cleaned_content is None
    assert section.verify_status == "rejected"
    assert "sanity floor" in section.verify_reason
    warn.assert_awaited_once()
    # The verdict never becomes an insight: insights ride into the LLM prompt
    # (Notebook.get_context) and into vector search. Diagnostics must not.
    source.add_insight.assert_not_awaited()


@pytest.mark.asyncio
async def test_length_stopped_proof_is_rejected_not_persisted():
    section = _section_mock("x" * 1000)
    source = _source_mock()
    # Full-length reply, but the provider says it stopped on the token cap.
    out, warn = await _run_verify(
        section, source, _response("y" * 1000, done_reason="length")
    )

    assert out.cleaned_content is None
    assert section.verify_status == "rejected"
    assert "max_tokens" in section.verify_reason
    warn.assert_awaited_once()
    source.add_insight.assert_not_awaited()


@pytest.mark.asyncio
async def test_sane_proof_is_persisted_and_marked_clean():
    section = _section_mock("x" * 1000)
    source = _source_mock()
    out, warn = await _run_verify(
        section, source, _response("y" * 950, done_reason="stop")
    )

    assert out.cleaned_content == "y" * 950
    assert section.cleaned_content == "y" * 950
    assert section.verify_status == "clean"
    assert section.verify_reason is None
    section.save.assert_awaited_once()  # one save for content + verdict
    warn.assert_not_awaited()  # a clean proof is not a warning
    source.add_insight.assert_not_awaited()


@pytest.mark.asyncio
async def test_oversized_page_span_is_skipped_not_flagged():
    section = _section_mock("x" * 1000)
    section.page_start = 0
    section.page_end = verify_commands._MAX_VERIFY_PAGES + 10
    source = _source_mock()
    out, warn = await _run_verify(section, source, _response("y" * 950))

    assert out.cleaned_content is None
    assert section.verify_status == "skipped"
    assert "too large" in section.verify_reason
    warn.assert_awaited_once()
    source.add_insight.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_vision_reply_is_rejected_not_silent():
    """An empty reply must leave a verdict, not vanish.

    qwen3.6 intermittently spends its whole output budget on the thinking prelude
    and returns nothing (to-fix/004 Finding 4). This path used to return silently,
    so the section looked identical to one verify never reached — 8 sections of the
    test book were lost this way.
    """
    section = _section_mock("x" * 1000)
    source = _source_mock()
    out, warn = await _run_verify(section, source, _response("", done_reason="length"))

    assert out.cleaned_content is None
    assert section.verify_status == "rejected"
    assert "empty content" in section.verify_reason
    warn.assert_awaited_once()
    source.add_insight.assert_not_awaited()


@pytest.mark.asyncio
async def test_discrepancy_narration_is_dropped_not_stored():
    """The model's freeform commentary on an ACCEPTED proof goes nowhere.

    This was ~107K chars on one textbook, injected into every chat turn. The proof
    still lands; only the monologue is discarded.
    """
    section = _section_mock("x" * 1000)
    source = _source_mock()
    reply = _response(
        "y" * 950 + "\n\nDISCREPANCIES:\nThe parsed text omits a paragraph on p. 41.",
        done_reason="stop",
    )
    out, warn = await _run_verify(section, source, reply)

    assert section.verify_status == "clean"
    assert out.discrepancies  # still reported in the job's result payload
    source.add_insight.assert_not_awaited()  # but never persisted as content
    warn.assert_not_awaited()  # and it is not a warning — the proof was accepted


# --- Finding 1: leaf-only fan-out --------------------------------------------


def test_leaf_ids_skip_parents():
    """Parents' page ranges cover their children's — proofing both re-emits
    the same pages twice."""
    tree = [
        {
            "id": "source_section:ch1",
            "children": [
                {"id": "source_section:s11", "children": []},
                {
                    "id": "source_section:s12",
                    "children": [{"id": "source_section:s121"}],
                },
            ],
        },
        {"id": "source_section:ch2", "children": None},
    ]
    assert _leaf_section_ids(tree) == [
        "source_section:s11",
        "source_section:s121",
        "source_section:ch2",
    ]


def test_leaf_ids_flat_tree_keeps_everything():
    tree = [{"id": "source_section:a"}, {"id": "source_section:b"}]
    assert _leaf_section_ids(tree) == ["source_section:a", "source_section:b"]


def test_leaf_ids_ignore_idless_leaves():
    assert _leaf_section_ids([{"children": []}, {"id": "source_section:a"}]) == [
        "source_section:a"
    ]


# --- Finding 3: summaries are bounded routing blurbs --------------------------


def test_summary_targets_require_both_level_and_size():
    big, small = "x" * (_MIN_SUMMARY_CHARS + 1), "x" * (_MIN_SUMMARY_CHARS - 1)
    tree = [
        {
            "id": "source_section:ch1",
            "level": 1,
            "content": big,
            "children": [
                {"id": "source_section:s11", "level": 2, "content": small},
                {"id": "source_section:s12", "level": 2, "cleaned_content": big},
                # Level 3 is outside the tiered policy no matter the size.
                {"id": "source_section:s13", "level": 3, "content": big},
            ],
        },
        # Heading-only structural node: no text, no summary.
        {"id": "source_section:part2", "level": 1, "content": ""},
    ]
    assert _summary_target_ids(tree) == [
        "source_section:ch1",
        "source_section:s12",
    ]


@pytest.mark.asyncio
async def test_stamped_small_section_skips_without_a_model_call():
    """Jobs queued before the size bound existed must not spend a heavy-slot
    generation on a section that is its own summary."""
    section = MagicMock()
    section.id = "source_section:s1"
    section.source = "source:x"
    section.cleaned_content = None
    section.content = "x" * (_MIN_SUMMARY_CHARS - 1)
    source = MagicMock(parse_generation=4)

    with (
        patch("commands.summary_commands.SourceSection.get", AsyncMock(return_value=section)),
        patch("commands.summary_commands.Source.get", AsyncMock(return_value=source)),
        patch("commands.summary_commands.provision_langchain_model") as provision,
    ):
        out = await summarize_section(
            SummarizeSectionInput(
                source_section_id="source_section:s1", parse_generation=4
            )
        )

    assert out.summary is None
    provision.assert_not_called()


@pytest.mark.asyncio
async def test_unstamped_small_section_still_summarizes():
    """An explicit (manual, unstamped) single-section request works at any size."""
    section = MagicMock()
    section.id = "source_section:s1"
    section.source = "source:x"
    section.cleaned_content = None
    section.content = "short but explicitly requested"
    section.summary = "old"  # had_summary → no abstract trigger to mock
    section.save = AsyncMock()

    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=_response("A routing blurb."))

    with (
        patch("commands.summary_commands.SourceSection.get", AsyncMock(return_value=section)),
        patch(
            "commands.summary_commands.provision_langchain_model",
            AsyncMock(return_value=model),
        ) as provision,
        patch.object(
            summary_commands.model_manager,
            "get_defaults",
            AsyncMock(return_value=MagicMock(default_transformation_model="model:t")),
        ),
        patch("commands.summary_commands.heavy_lane_for", AsyncMock(return_value=nullcontext())),
    ):
        out = await summarize_section(
            SummarizeSectionInput(source_section_id="source_section:s1")
        )

    assert out.summary == "A routing blurb."
    section.save.assert_awaited_once()
    # The generation is bounded — a blurb does not get a prose budget.
    assert provision.await_args.kwargs["max_tokens"] <= 1024


@pytest.mark.asyncio
async def test_fanout_with_zero_qualifying_sections_completes_instead_of_retrying():
    """A real tree where nothing needs a summary is a finished run, not a
    'chaptering still in flight' retry-to-failure."""
    source = MagicMock()
    source.parse_generation = 1
    source.get_sections = AsyncMock(
        return_value=[{"id": "source_section:a", "level": 1, "content": "tiny"}]
    )

    with (
        patch("commands.summary_commands.Source.get", AsyncMock(return_value=source)),
        patch("commands.summary_commands.blocks_in_flight", AsyncMock(return_value=False)),
        patch("commands.summary_commands.chaptering_in_flight", AsyncMock(return_value=False)),
        patch("commands.summary_commands.submit_command") as submit,
    ):
        out = await summarize_source(SummarizeSourceInput(source_id="source:x"))

    assert out.success is True
    assert out.jobs_submitted == 0
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_remaining_unsummarized_ignores_small_sections():
    """The abstract's readiness gates must not wait for summaries the size
    bound means no job will ever write — that would deadlock the abstract."""
    rows = [
        # Big + unsummarized → counts.
        {"clean_len": 0, "raw_len": _MIN_SUMMARY_CHARS + 5, "summary_len": 0},
        # Small + unsummarized → never counts (its own summary).
        {"clean_len": 0, "raw_len": _MIN_SUMMARY_CHARS - 5, "summary_len": 0},
        # Cleaned layer wins over raw when deciding size.
        {"clean_len": _MIN_SUMMARY_CHARS - 5, "raw_len": _MIN_SUMMARY_CHARS + 5, "summary_len": 0},
        # Big but already summarized → not remaining.
        {"clean_len": _MIN_SUMMARY_CHARS + 5, "raw_len": 0, "summary_len": 120},
        # Heading-only structural node.
        {"clean_len": 0, "raw_len": 0, "summary_len": 0},
    ]
    with patch("commands.summary_commands.repo_query", AsyncMock(return_value=rows)):
        assert await _remaining_unsummarized("source:x") == 1


# --- runaway-thinking guard: reasoning disabled on batch generations ---------


def test_apply_reasoning_flag_sets_think_switch_on_chatollama():
    from langchain_ollama import ChatOllama

    from open_notebook.ai.provision import apply_reasoning_flag

    model = ChatOllama(model="test")
    assert apply_reasoning_flag(model, False).reasoning is False
    assert apply_reasoning_flag(model, True).reasoning is True


def test_apply_reasoning_flag_passes_through_unsupported_models():
    from open_notebook.ai.provision import apply_reasoning_flag

    model = MagicMock()
    assert apply_reasoning_flag(model, False) is model


def test_abstract_rows_carry_text_len_for_the_pending_gate():
    tree = [
        {
            "title": "Ch 1",
            "level": 1,
            "summary": "s",
            "cleaned_content": "x" * 10,
            "children": [
                {"title": "1.1", "level": 2, "summary": None, "content": "x" * 3}
            ],
        }
    ]
    rows = _flatten_sections_for_abstract(tree)
    assert [r["text_len"] for r in rows] == [10, 3]
