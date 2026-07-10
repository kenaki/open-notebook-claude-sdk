"""One-shot backfill: recover verify verdicts from the legacy `verify_flag` insights.

Run this ONCE, after migration 27 and BEFORE `drop_verify_flag_insights.py`.

Migration 27's own backfill can only infer the happy path — a section with
`cleaned_content` was proofed, so it is 'clean'. The *rejected* and *skipped*
verdicts were never written to the section at all; they existed only in the text
of a `verify_flag` source_insight. Deleting those insights without this script
loses them (recoverable only by re-running verify-clean, which is ~27 serialized
vision generations on the single heavy slot).

Mapping insight -> section is not trivial: the note names the section by TITLE,
and titles repeat ("Exercises" appears 9 times in Hands-On ML). The rejection note
also embeds the raw section length ("... for a 11208-char section"), and the skip
note embeds the page span — both far more selective than the title. We match on
(title, discriminator) and refuse to guess when that is still ambiguous.

    uv run python scripts/backfill_verify_status.py           # dry run
    uv run python scripts/backfill_verify_status.py --apply   # write
"""

import argparse
import asyncio
import re
from typing import Optional

from dotenv import load_dotenv

load_dotenv(".env")

from open_notebook.database.repository import repo_query  # noqa: E402

# "Section 'X' verify output rejected: the model returned 7716 chars for a 11208-char section"
_REJECTED = re.compile(
    r"^Section '(?P<title>.+?)' verify output rejected:.*?for a (?P<raw>\d+)-char section",
    re.S,
)
# "Section 'X' spans 123 pages (> 50) — too large for a single-pass vision verify; skipped."
_SKIPPED = re.compile(r"^Section '(?P<title>.+?)' spans (?P<span>\d+) pages", re.S)


async def _match_section(sid: str, title: str, raw: Optional[int], span: Optional[int]):
    """Return the single section this note describes, or None if not unique.

    Candidates are restricted to sections that are NOT already 'clean' — a proofed
    section cannot be the subject of a rejection.
    """
    rows = await repo_query(
        "SELECT id, string::len(content) AS raw, page_start, page_end "
        "FROM source_section WHERE source = type::thing($sid) AND title = $t "
        "AND (verify_status = NONE OR verify_status != 'clean')",
        {"sid": sid, "t": title},
    )
    if raw is not None:
        rows = [r for r in rows if r["raw"] == raw]
    if span is not None:
        rows = [
            r
            for r in rows
            if r.get("page_start") is not None
            and ((r.get("page_end") or r["page_start"]) - r["page_start"] + 1) == span
        ]
    return rows[0]["id"] if len(rows) == 1 else None


async def main(apply: bool) -> None:
    flags = await repo_query(
        "SELECT source, content FROM source_insight WHERE insight_type = 'verify_flag'"
    )
    planned, unmatched, narration = [], [], 0

    for f in flags:
        content = f["content"] or ""
        sid = str(f["source"])
        if m := _REJECTED.match(content):
            status, raw, span = "rejected", int(m.group("raw")), None
        elif m := _SKIPPED.match(content):
            status, raw, span = "skipped", None, int(m.group("span"))
        else:
            narration += 1  # freeform model commentary; carries no verdict
            continue

        section_id = await _match_section(sid, m.group("title"), raw, span)
        if section_id is None:
            unmatched.append((m.group("title"), status))
        else:
            planned.append((str(section_id), status, content))

    print(f"{len(flags)} verify_flag insights")
    print(f"  {narration:>4} narration (no verdict, nothing to backfill)")
    print(f"  {len(planned):>4} verdicts matched to exactly one section")
    print(f"  {len(unmatched):>4} verdicts NOT matched (left as NONE)")
    for title, status in unmatched:
        print(f"       ! {status}: {title!r}")

    by_status = {}
    for _, status, _ in planned:
        by_status[status] = by_status.get(status, 0) + 1
    print(f"  breakdown: {by_status}")

    if not apply:
        print("\nDry run. Re-run with --apply to write verify_status/verify_reason.")
        return

    for section_id, status, reason in planned:
        await repo_query(
            "UPDATE type::thing($id) SET verify_status = $s, verify_reason = $r",
            {"id": section_id, "s": status, "r": reason},
        )

    dist = await repo_query(
        "SELECT verify_status, count() AS n FROM source_section GROUP BY verify_status"
    )
    print(f"\nWrote {len(planned)} verdicts. verify_status distribution: {dist}")
    if unmatched:
        print(
            f"NOTE: {len(unmatched)} verdict(s) could not be attributed to a unique "
            f"section and remain NONE. Re-run verify-clean to regenerate them."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    asyncio.run(main(parser.parse_args().apply))
