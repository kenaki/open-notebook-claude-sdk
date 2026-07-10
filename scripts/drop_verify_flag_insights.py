"""One-shot cleanup: delete every `verify_flag` source_insight.

Companion to migration 27. Verify used to record its verdicts and the vision
model's freeform narration as insights on the source. That was the wrong table:
`Notebook.get_context()` injects every insight into the LLM prompt verbatim and
uncapped, and `create_insight_command` embeds each one into vector search — so
proofreading notes about *how well we parsed the book* were being retrieved and
prompted as if they were *content of the book*. On one 472-section textbook that
was 170 rows and ~114K characters per chat turn.

Migration 27 moves the verdict to `source_section.verify_status`/`verify_reason`
and `verify_commands.py` stops writing insights entirely. This script removes the
rows already written. It is NOT part of the migration on purpose: migrations here
run automatically on every API startup, and silently deleting user-visible rows
on startup is not something a schema migration should do. Run it deliberately.

The embedding is a column on `source_insight`, not a separate table, so deleting
the row takes the vector with it.

The verdicts are cheap to rebuild — re-run verify-clean on the source and the
'rejected'/'skipped' sections repopulate. The narration is not rebuilt, by design.

    uv run python scripts/drop_verify_flag_insights.py            # dry run
    uv run python scripts/drop_verify_flag_insights.py --apply    # delete
"""

import argparse
import asyncio

from dotenv import load_dotenv

load_dotenv(".env")

from open_notebook.database.repository import repo_query  # noqa: E402

# Matches the note written by the old output-sanity guard. Everything else under
# `verify_flag` is the model's freeform discrepancy narration.
_REJECTION_MARKER = "verify output rejected"


async def main(apply: bool) -> None:
    rows = await repo_query(
        "SELECT id, source, content FROM source_insight WHERE insight_type = 'verify_flag'"
    )
    if not rows:
        print("No verify_flag insights found — nothing to do.")
        return

    rejections = [r for r in rows if _REJECTION_MARKER in (r["content"] or "")]
    narration = [r for r in rows if r not in rejections]
    chars = sum(len(r["content"] or "") for r in rows)
    sources = {str(r["source"]) for r in rows}

    print(f"{len(rows)} verify_flag insights across {len(sources)} source(s)")
    print(f"  {len(rejections):>4} rejection/skip verdicts (rebuildable via verify-clean)")
    print(f"  {len(narration):>4} model discrepancy narration (dropped, not rebuilt)")
    print(f"  {chars:,} chars — this much left every chat turn that included these sources")

    if not apply:
        print("\nDry run. Re-run with --apply to delete.")
        return

    deleted = await repo_query(
        "DELETE source_insight WHERE insight_type = 'verify_flag' RETURN BEFORE"
    )
    remaining = await repo_query(
        "SELECT count() AS n FROM source_insight WHERE insight_type = 'verify_flag' GROUP ALL"
    )
    left = remaining[0]["n"] if remaining else 0
    print(f"\nDeleted {len(deleted)} rows. Remaining verify_flag insights: {left}")
    if left:
        raise SystemExit(f"Expected 0 remaining, found {left}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="actually delete (default: dry run)"
    )
    asyncio.run(main(parser.parse_args().apply))
