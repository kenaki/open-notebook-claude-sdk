"""Rebuild `source_parse.section_index` for existing parses (to-fix/006).

The reader outline was every heading block Docling emitted: unfiltered (callout
boxes, watermarks and lead-in sentences appeared as entries) and uniformly
level 1, because Docling's PDF pipeline never assigns a heading level.

`section_index` is pure derived data — the heading blocks it indexes are already
stored, and the PDF's TOC bookmarks are still on disk — so it can be rebuilt in
place. **No reparse.** Nothing else reads `section_index` (only the reader's
outline dropdown), so this is a read-path repair with no downstream effect.

    uv run python scripts/backfill_section_index.py            # dry run
    uv run python scripts/backfill_section_index.py --apply
    uv run python scripts/backfill_section_index.py --apply --source <key>

Sources whose PDF is missing, or that carry no bookmarks, get the flat
junk-filtered outline instead — same as a fresh parse would.
"""

import argparse
import asyncio
import collections
import sys
from pathlib import Path

from loguru import logger

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.blocks import PARSE_TABLE, parse_rid
from open_notebook.parsers.outline import build_outline, read_pdf_toc


async def _ready_parses(only: str | None) -> list[dict]:
    rows = await repo_query(
        "SELECT source, gen, page_index, section_index FROM source_parse "
        "WHERE status = 'ready'"
    )
    out = []
    for row in rows:
        key = str(row["source"]).split(":", 1)[-1]
        if only and key != only:
            continue
        row["_key"] = key
        out.append(row)
    return out


async def _pdf_path(source_key: str) -> Path | None:
    rows = await repo_query(f"SELECT asset FROM source:{source_key}")
    if not rows:
        return None
    file_path = (rows[0].get("asset") or {}).get("file_path")
    if not file_path:
        return None
    path = Path(file_path)
    return path if path.exists() else None


async def _headings(source_key: str, gen: int) -> list[dict]:
    rows = await repo_query(
        "SELECT seq, page, text, level FROM document_block "
        "WHERE source = $s AND gen = $g AND type = 'heading' ORDER BY seq",
        {"s": ensure_record_id(f"source:{source_key}"), "g": gen},
    )
    return [dict(r) for r in rows]


async def _last_seq(source_key: str, gen: int) -> int:
    rows = await repo_query(
        "SELECT math::max(seq) AS last FROM document_block "
        "WHERE source = $s AND gen = $g GROUP ALL",
        {"s": ensure_record_id(f"source:{source_key}"), "g": gen},
    )
    return int(rows[0]["last"]) if rows and rows[0].get("last") is not None else -1


def _levels(entries: list[dict]) -> dict:
    return dict(sorted(collections.Counter(e["level"] for e in entries).items()))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write; default is dry run")
    parser.add_argument("--source", help="restrict to one source key")
    args = parser.parse_args()

    parses = await _ready_parses(args.source)
    if not parses:
        logger.error("No ready parse headers found")
        return 1

    for row in parses:
        key, gen = row["_key"], int(row["gen"])
        headings = await _headings(key, gen)
        if not headings:
            logger.warning(f"{key} gen={gen}: no heading blocks — skipped")
            continue

        pdf = await _pdf_path(key)
        toc = read_pdf_toc(pdf) if pdf else []
        if not toc:
            logger.warning(
                f"{key} gen={gen}: no TOC bookmarks "
                f"({'PDF missing' if not pdf else 'none embedded'}) — flat outline"
            )

        new = build_outline(
            headings,
            row.get("page_index") or [],
            toc,
            last_seq=await _last_seq(key, gen),
        )
        old = row.get("section_index") or []

        logger.info(
            f"{key} gen={gen}: {len(old)} -> {len(new)} entries | "
            f"levels {_levels(old)} -> {_levels(new)}"
        )

        if args.apply:
            await repo_query(
                f"UPDATE $rid SET section_index = $si",
                {"rid": parse_rid(key, gen), "si": new},
            )
            logger.success(f"{key} gen={gen}: {PARSE_TABLE}.section_index rewritten")

    if not args.apply:
        logger.info("Dry run — nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
