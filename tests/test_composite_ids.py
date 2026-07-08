"""A0 pre-flight smoke — P-sdk-roundtrip (db-design §8.1).

Live-DB integration test proving the Python SurrealDB SDK can round-trip
COMPOSITE RecordIDs of the shape `document_block:[src_key, gen, seq]` that the
whole block substrate keys on:

  - `repo_insert` preserves explicit composite RecordIDs (no server re-id),
  - a param-bound range scan `t:[$k,$g,0]..=[$k,$g,N]` returns rows in key
    order WITHOUT an ORDER BY (the keyspace IS the index),
  - point-get by composite id works,
  - a param-bound range DELETE removes exactly the range,
  - `parse_record_ids` stringifies composite ids to the documented shape.

Uses a throwaway table `zz_smoke_block`, dropped in teardown. If this test
fails, P-composite-ids (S4) must be re-decided (fallback: string-interpolated
ids via type::thing) before any schema work proceeds.
"""

import pytest
import pytest_asyncio
from surrealdb import RecordID

from open_notebook.database.repository import (
    parse_record_ids,
    repo_insert,
    repo_query,
)

SMOKE_TABLE = "zz_smoke_block"
KEY = "zzsmoke_src"
GEN = 1
N = 10


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    """Drop the throwaway table before and after each test (idempotent)."""
    await repo_query(f"REMOVE TABLE IF EXISTS {SMOKE_TABLE};")
    yield
    await repo_query(f"REMOVE TABLE IF EXISTS {SMOKE_TABLE};")


@pytest.mark.asyncio
async def test_composite_recordid_roundtrip():
    # --- insert with explicit composite RecordIDs -------------------------
    records = [
        {
            "id": RecordID(SMOKE_TABLE, [KEY, GEN, seq]),
            "seq": seq,
            "note": f"block-{seq}",
        }
        for seq in range(N + 1)  # seqs 0..10 inclusive
    ]
    inserted = await repo_insert(SMOKE_TABLE, records)
    assert len(inserted) == N + 1, f"expected {N + 1} rows, got {len(inserted)}"

    # ids must be preserved verbatim (server did not re-key) — the returned
    # ids stringify to the composite shape and carry our key/gen/seq.
    inserted_ids = {str(r["id"]) for r in inserted}
    assert len(inserted_ids) == N + 1
    sample_id = str(inserted[0]["id"])
    assert SMOKE_TABLE in sample_id and KEY in sample_id, sample_id

    # --- param-bound range scan, NO ORDER BY -----------------------------
    rows = await repo_query(
        f"SELECT * FROM {SMOKE_TABLE}:[$k, $g, 0]..=[$k, $g, {N}];",
        {"k": KEY, "g": GEN},
    )
    assert len(rows) == N + 1, f"range scan returned {len(rows)} rows"
    # returned in key order without an explicit ORDER BY
    seqs = [r["seq"] for r in rows]
    assert seqs == list(range(N + 1)), f"not key-ordered: {seqs}"

    # --- point get by composite id ---------------------------------------
    point = await repo_query(
        f"SELECT * FROM {SMOKE_TABLE}:[$k, $g, 5];", {"k": KEY, "g": GEN}
    )
    assert len(point) == 1 and point[0]["seq"] == 5, point

    # --- param-bound range DELETE (a sub-range) --------------------------
    await repo_query(
        f"DELETE {SMOKE_TABLE}:[$k, $g, 3]..=[$k, $g, 6];",
        {"k": KEY, "g": GEN},
    )
    remaining = await repo_query(
        f"SELECT seq FROM {SMOKE_TABLE}:[$k, $g, 0]..=[$k, $g, {N}];",
        {"k": KEY, "g": GEN},
    )
    remaining_seqs = sorted(r["seq"] for r in remaining)
    assert remaining_seqs == [0, 1, 2, 7, 8, 9, 10], remaining_seqs

    # --- parse_record_ids string round-trip format -----------------------
    # A raw RecordID stringifies to the composite-array shape; parse_record_ids
    # walks nested structures and produces the same string form on read.
    raw = {"id": RecordID(SMOKE_TABLE, [KEY, GEN, 42])}
    parsed = parse_record_ids(raw)
    assert isinstance(parsed["id"], str)
    assert parsed["id"].startswith(f"{SMOKE_TABLE}:")
    assert "42" in parsed["id"] and KEY in parsed["id"], parsed["id"]
