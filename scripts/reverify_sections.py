"""Re-run vision verify on a SUBSET of a source's sections, chosen by verdict.

!!! FROZEN — see to-fix/005. Verify currently CORRUPTS data as it runs.
Sections that occupy part of a page get their page-neighbours' text written into
their `cleaned_content`, which the agent's `get_section` tool, summary generation,
and the sections API all prefer over the raw parse. (The reader view, full_text and
vector search read `document_block` instead, and are unaffected.) Running this script
made one section 537% of its original size, filled with the model's commentary. Do not
use it until to-fix/005 Finding 1 (crop-to-section rendering) lands. `--apply` refuses
unless you pass --i-understand-005.

`POST /sources/{id}/verify-clean` re-proofs every leaf section — 382 of them on a
472-section textbook, each a serialized generation on the single heavy Ollama slot,
including the hundreds that are already clean. That's the right tool after a
re-parse and the wrong one when a handful of sections failed.

Migration 27 put a verdict on each section, so the failures are now addressable:

    # what would run
    uv run python scripts/reverify_sections.py source:xxx --status rejected

    # actually submit
    uv run python scripts/reverify_sections.py source:xxx --status rejected --apply

Worth knowing which failures are worth retrying:
  - empty-content rejections are INTERMITTENT (the model spent its whole output
    budget on the thinking prelude — to-fix/004 Finding 4). A retry often succeeds,
    especially now that `think:false` and num_ctx=32768 are in place.
  - shrink-floor rejections are DETERMINISTIC. Same model, same prompt, same floor
    → same rejection. Retrying them changes nothing; either recalibrate
    _MIN_CLEANED_RATIO or split the section.
  - 'skipped' sections exceed _MAX_VERIFY_PAGES. Re-chapter them; a retry re-skips.

Submits jobs and returns. Watch them land in /activity, or:
    journalctl --user -u on-worker -f | grep verify_clean_section
"""

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

# `open_notebook` is an installed package; `commands` is not — it only resolves
# from the repo root, which is absent from sys.path when running a file in scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv(".env")

from surreal_commands import submit_command  # noqa: E402

# The @command decorator registers on import, and submit_command validates the
# name against that registry — without this, every submit fails with "Command not
# found: open_notebook.verify_clean_section". api/command_service.py does the same.
import commands  # noqa: E402, F401 — registers verify_clean_section
from open_notebook.database.repository import repo_query  # noqa: E402
from open_notebook.domain.notebook import Source  # noqa: E402

_EMPTY_MARKER = "returned empty content"


async def _select(source_id: str, status: str):
    # `order` must appear in the projection to be usable in ORDER BY (SurrealDB
    # rejects "Idiom missing here" otherwise) — same shape as Source.get_outline.
    if status != "unverified":
        return await repo_query(
            "SELECT id, title, order, verify_reason FROM source_section "
            "WHERE source = type::thing($s) AND verify_status = $v ORDER BY order",
            {"s": source_id, "v": status},
        )

    # Leaf sections with a page range that carry no verdict at all. Verify fans out
    # over leaves only, so a leaf with pages is one verify SHOULD have covered.
    # These exist because the pre-migration-27 code returned silently on an empty
    # model reply — the section looks untouched. Parents are excluded: they are
    # unverified by design (leaf-only fan-out, to-fix/004 Finding 1).
    return await repo_query(
        "SELECT id, title, order, verify_reason FROM source_section "
        "WHERE source = type::thing($s) AND verify_status = NONE "
        "AND page_start != NONE "
        "AND id NOT IN (SELECT VALUE parent FROM source_section "
        "               WHERE source = type::thing($s) AND parent != NONE) "
        "ORDER BY order",
        {"s": source_id},
    )


async def main(source_id: str, status: str, only_empty: bool, apply: bool, override: bool) -> None:
    source = await Source.get(source_id)

    rows = await _select(source_id, status)
    if only_empty:
        rows = [r for r in rows if _EMPTY_MARKER in (r["verify_reason"] or "")]

    if not rows:
        print(f"No sections with verify_status='{status}'" + (" and an empty-content reason." if only_empty else "."))
        return

    print(f"{len(rows)} section(s) to re-verify on {source_id}:")
    for r in rows:
        reason = " ".join((r["verify_reason"] or "").split())
        if not reason:
            # No verdict was ever recorded — pre-migration-27 silent failure. The
            # cause is unrecoverable from the DB, but an empty model reply is the
            # only path that used to return without writing anything.
            kind = "no verdict recorded (probably empty output) — retry worthwhile"
        elif _EMPTY_MARKER in reason:
            kind = "empty output (intermittent) — retry worthwhile"
        else:
            kind = "shrink floor (deterministic) — a retry will reject again"
        print(f"  - {r['title'][:48]:<48} {kind}")

    if not apply:
        print("\nDry run. Re-run with --apply to submit jobs.")
        return

    if not override:
        raise SystemExit(
            "\nREFUSING TO RUN — verify is frozen (to-fix/005).\n"
            "Verify renders whole pages, so a sub-page section's cleaned_content\n"
            "absorbs its neighbours' text. The agent's get_section tool, summary\n"
            "generation and the sections API all read that layer.\n"
            "Re-running degrades data. Pass --i-understand-005 to override."
        )

    submitted = 0
    for r in rows:
        try:
            cmd_id = submit_command(
                "open_notebook",
                "verify_clean_section",
                {
                    "source_section_id": str(r["id"]),
                    # Staleness stamp: a re-parse between submit and run kills the
                    # section id, and the job self-skips rather than crashing.
                    "parse_generation": source.parse_generation,
                    # Job-tray metadata (ignored by the Pydantic input model).
                    "source_id": source_id,
                    "label": r["title"],
                },
            )
            print(f"  submitted {cmd_id} for {r['id']}")
            submitted += 1
        except Exception as exc:  # isolation: one bad submit must not stop the rest
            print(f"  FAILED to submit for {r['id']}: {exc}")

    print(f"\n{submitted}/{len(rows)} jobs submitted. They run one at a time on the heavy slot.")
    print("Watch: journalctl --user -u on-worker -f | grep verify_clean_section")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source_id", help="e.g. source:bms5qu1xfaq9vvlpm11f")
    p.add_argument(
        "--status",
        default="rejected",
        choices=["rejected", "skipped", "unverified"],
        help="'unverified' = leaf sections with pages but no verdict (pre-fix silent failures)",
    )
    p.add_argument(
        "--only-empty",
        action="store_true",
        help="only the intermittent empty-output rejections (worth retrying)",
    )
    p.add_argument("--apply", action="store_true", help="submit (default: dry run)")
    p.add_argument(
        "--i-understand-005",
        dest="override",
        action="store_true",
        help="acknowledge that verify corrupts sub-page sections (to-fix/005)",
    )
    a = p.parse_args()
    asyncio.run(main(a.source_id, a.status, a.only_empty, a.apply, a.override))
