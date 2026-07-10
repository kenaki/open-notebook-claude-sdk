"""Unit tests for the notebook-chat annotation-reference path (cross-study B1).

Covers the shared resolver primitives in ``api.annotation_refs`` and the
notebook-chat serialization seam in ``api.routers.chat.citations`` on synthetic
data — no DB, no LLM, no checkpoint. Mirrors ``tests/test_source_chat_refs.py``.

- ``make_source_in_notebook_check``: ownership predicate (repo call mocked),
  including per-source caching.
- ``resolve_annotations_for_chat``: refs carry ``source_id`` on the notebook path.
- ``_parse_annotation_refs`` / ``_build_chat_message``: annotation refs surface on
  the human message and unknown keys are dropped (degrade-never-fail).
- ``ChatCompletionInput``: the typed annotation fields survive on the notebook
  branch too.
"""

from types import SimpleNamespace

import pytest

import api.annotation_refs as ar
from api.routers.chat.citations import _build_chat_message, _parse_annotation_refs
from commands.chat_commands import ChatCompletionInput

# --- notebook ownership predicate (repo call mocked) --------------------------


@pytest.mark.asyncio
async def test_source_in_notebook_check_true(monkeypatch):
    async def fake_repo_query(_q, _params):
        return [{"id": "reference:1"}]

    monkeypatch.setattr(ar, "repo_query", fake_repo_query)
    check = ar.make_source_in_notebook_check("notebook:nb")
    assert await check(SimpleNamespace(source="source:s1")) is True


@pytest.mark.asyncio
async def test_source_in_notebook_check_false(monkeypatch):
    async def fake_repo_query(_q, _params):
        return []

    monkeypatch.setattr(ar, "repo_query", fake_repo_query)
    check = ar.make_source_in_notebook_check("notebook:nb")
    assert await check(SimpleNamespace(source="source:foreign")) is False


@pytest.mark.asyncio
async def test_source_in_notebook_check_caches_per_source(monkeypatch):
    calls = {"n": 0}

    async def fake_repo_query(_q, _params):
        calls["n"] += 1
        return [{"id": "reference:1"}]

    monkeypatch.setattr(ar, "repo_query", fake_repo_query)
    check = ar.make_source_in_notebook_check("notebook:nb")
    ann = SimpleNamespace(source="source:s1")
    assert await check(ann) is True
    assert await check(ann) is True
    # Second call for the same source is served from the per-request cache.
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_source_in_notebook_check_none_source_is_false():
    check = ar.make_source_in_notebook_check("notebook:nb")
    assert await check(SimpleNamespace(source=None)) is False


# --- resolver: refs carry source_id on the notebook path ----------------------


@pytest.mark.asyncio
async def test_resolve_annotations_refs_include_source_id(monkeypatch):
    ann = SimpleNamespace(
        id="source_annotation:a1",
        source="source:s1",
        quote="hello",
        note=None,
        block_seq=None,  # quote-only path: no block window fetch
        anchor_gen=None,
        page=3,
    )

    async def fake_get(_aid):
        return ann

    async def fake_relate(_sid, _aid):
        return None

    async def owns(_a):
        return True

    async def resolve_source(_a):
        return SimpleNamespace(parse_generation=None)

    monkeypatch.setattr(ar.SourceAnnotation, "get", fake_get)
    monkeypatch.setattr(ar, "relate_citation", fake_relate)

    ctx, refs = await ar.resolve_annotations_for_chat(
        ["source_annotation:a1"],
        "chat_session:x",
        check_ownership=owns,
        resolve_source=resolve_source,
    )
    assert len(refs) == 1
    assert refs[0]["source_id"] == "source:s1"
    assert refs[0]["id"] == "source_annotation:a1"
    assert refs[0]["quote"] == "hello"
    assert refs[0]["page"] == 3
    # Context section is the shared pure builder's output.
    assert "REFERENCED ANNOTATION 1" in ctx


@pytest.mark.asyncio
async def test_resolve_annotations_skips_failed_ownership(monkeypatch):
    ann = SimpleNamespace(
        id="source_annotation:a1",
        source="source:foreign",
        quote="hi",
        note=None,
        block_seq=None,
        anchor_gen=None,
        page=1,
    )

    async def fake_get(_aid):
        return ann

    relate_calls = {"n": 0}

    async def fake_relate(_sid, _aid):
        relate_calls["n"] += 1

    async def owns(_a):
        return False

    async def resolve_source(_a):
        raise AssertionError("source must not be fetched for a rejected annotation")

    monkeypatch.setattr(ar.SourceAnnotation, "get", fake_get)
    monkeypatch.setattr(ar, "relate_citation", fake_relate)

    ctx, refs = await ar.resolve_annotations_for_chat(
        ["source_annotation:a1"],
        "chat_session:x",
        check_ownership=owns,
        resolve_source=resolve_source,
    )
    assert refs == []
    assert ctx == ""
    assert relate_calls["n"] == 0  # no edge recorded for a rejected annotation


# --- notebook-chat serialization seam -----------------------------------------


def test_parse_annotation_refs_serializes_and_drops_unknown_keys():
    refs = _parse_annotation_refs(
        {
            "annotation_refs": [
                {
                    "id": "source_annotation:a1",
                    "source_id": "source:s1",
                    "quote": "hello",
                    "block_seq": 5,
                    "page": 2,
                    "bogus": "must be dropped",
                }
            ]
        }
    )
    assert refs is not None and len(refs) == 1
    ref = refs[0]
    assert ref.id == "source_annotation:a1"
    assert ref.source_id == "source:s1"
    assert ref.block_seq == 5
    assert ref.page == 2
    assert "bogus" not in ref.model_dump()


def test_parse_annotation_refs_absent_or_empty_yields_none():
    assert _parse_annotation_refs({}) is None
    assert _parse_annotation_refs({"annotation_refs": []}) is None
    assert _parse_annotation_refs({"media": [{"type": "image"}]}) is None


@pytest.mark.asyncio
async def test_build_chat_message_surfaces_annotation_refs():
    msg = SimpleNamespace(
        type="human",
        content="What does this mean?",
        id="msg_1",
        additional_kwargs={
            "annotation_refs": [
                {
                    "id": "source_annotation:a1",
                    "source_id": "source:s1",
                    "quote": "hello",
                    "block_seq": 5,
                    "page": 2,
                }
            ]
        },
    )
    out = await _build_chat_message(msg, 0)
    assert out.annotation_refs is not None and len(out.annotation_refs) == 1
    assert out.annotation_refs[0].source_id == "source:s1"
    assert out.annotation_refs[0].id == "source_annotation:a1"


@pytest.mark.asyncio
async def test_build_chat_message_no_annotation_refs_is_none():
    msg = SimpleNamespace(
        type="human", content="plain question", id="msg_2", additional_kwargs={}
    )
    out = await _build_chat_message(msg, 0)
    assert out.annotation_refs is None


# --- router->worker transport (typed command fields, notebook branch) ---------


def test_chat_input_carries_notebook_annotation_fields():
    context = "REFERENCED ANNOTATION 1: [Intro] hello"
    refs = [
        {
            "id": "source_annotation:a",
            "source_id": "source:s",
            "quote": "hello",
            "block_seq": 5,
            "page": 2,
        }
    ]
    inp = ChatCompletionInput(
        session_id="chat_session:x",
        message="What does this mean?",
        kind="notebook",
        notebook_id="notebook:nb",
        annotation_context=context,
        annotation_refs=refs,
    )
    assert inp.message == "What does this mean?"
    assert inp.annotation_context == context
    assert inp.annotation_refs[0]["source_id"] == "source:s"
