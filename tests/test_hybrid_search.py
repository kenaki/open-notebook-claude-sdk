"""Unit tests for the Python RRF fusion behind hybrid_search (C2).

Covers the pure fusion function only (no DB / embedding model needed):
fusion score math, cross-arm dedupe, ordering, field-merge passthrough, and
limit truncation.
"""

from open_notebook.utils.hybrid_search import RRF_K, reciprocal_rank_fusion

_KEY = lambda r: r.get("id")


def test_score_is_sum_of_reciprocal_ranks():
    # "a" appears at rank 1 in list1 and rank 2 in list2 → both contributions.
    list1 = [{"id": "a"}, {"id": "b"}]
    list2 = [{"id": "c"}, {"id": "a"}]
    fused = reciprocal_rank_fusion([list1, list2], key=_KEY)

    by_id = {row["id"]: row["score"] for row in fused}
    assert by_id["a"] == 1.0 / (RRF_K + 1) + 1.0 / (RRF_K + 2)
    assert by_id["b"] == 1.0 / (RRF_K + 2)
    assert by_id["c"] == 1.0 / (RRF_K + 1)


def test_item_in_both_lists_outranks_single_list_items():
    # "a" is found by both retrievers, so it must fuse to the top.
    list1 = [{"id": "x"}, {"id": "a"}]
    list2 = [{"id": "y"}, {"id": "a"}]
    fused = reciprocal_rank_fusion([list1, list2], key=_KEY)

    assert fused[0]["id"] == "a"
    # Exactly three distinct keys: a, x, y (no duplicate "a").
    assert [r["id"] for r in fused].count("a") == 1
    assert {r["id"] for r in fused} == {"a", "x", "y"}


def test_ordering_is_descending_by_score():
    list1 = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    list2 = [{"id": "b"}]  # boosts b above a
    fused = reciprocal_rank_fusion([list1, list2], key=_KEY)

    scores = [r["score"] for r in fused]
    assert scores == sorted(scores, reverse=True)
    assert fused[0]["id"] == "b"


def test_merge_prefers_first_non_none_across_arms():
    # Vector arm carries title but no content; sparse arm fills content.
    vec = [{"id": "a", "title": "Doc A", "content": None}]
    ft = [{"id": "a", "title": None, "content": "matched text"}]
    fused = reciprocal_rank_fusion([vec, ft], key=_KEY)

    assert len(fused) == 1
    assert fused[0]["title"] == "Doc A"
    assert fused[0]["content"] == "matched text"


def test_limit_truncates_after_fusion():
    list1 = [{"id": c} for c in "abcde"]
    fused = reciprocal_rank_fusion([list1], key=_KEY, limit=2)
    assert len(fused) == 2
    assert [r["id"] for r in fused] == ["a", "b"]


def test_none_keys_are_skipped():
    rows = [{"id": None}, {"id": "a"}]
    fused = reciprocal_rank_fusion([rows], key=_KEY)
    assert [r["id"] for r in fused] == ["a"]
