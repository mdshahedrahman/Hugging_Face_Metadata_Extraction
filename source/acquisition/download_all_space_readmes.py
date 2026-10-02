#!/usr/bin/env python3
"""Download full README Markdown for the fixed Space card-crawl manifest.

Created: 2026-09-28
Version: v2026.09.28-05
Purpose: Collect full Space README evidence without changing prior crawls.

This specializes the tested dataset README downloader while retaining its
durable offsets, HTTP 429 cooldown, bounded concurrency, and terminal status
accounting. The internal ``datasetId`` alias is retained for compatibility;
every output record also has the authoritative ``spaceId`` field.
"""

from __future__ import annotations

import json
import argparse
from pathlib import Path
from urllib.parse import quote

import download_all_dataset_readmes as base


CHANGE_ID = "v2026.09.28-05"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "all_space_card_metadata_2026Sep24.jsonl"
DEFAULT_OUTPUT = SCRIPT_DIR / "all_space_readmes_full_2026Sep28.jsonl"
PRIORITY = {"with_metadata": 0, "no_metadata": 1}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download all Space README files.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--max-spaces", dest="max_datasets", type=int, default=0)
    return parser.parse_args()


def initialize(db, input_path: Path, output_path: Path) -> None:
    stat = input_path.stat()
    config = json.dumps(
        {
            "change_id": CHANGE_ID,
            "input": str(input_path),
            "input_size": stat.st_size,
            "input_mtime_ns": stat.st_mtime_ns,
            "output": str(output_path),
            "entity": "space",
        },
        sort_keys=True,
    )
    stored = base.state_get(db, "configuration")
    if stored is not None and stored != config:
        raise RuntimeError("State database belongs to another configuration")
    if stored is not None:
        return
    if output_path.exists() and output_path.stat().st_size:
        raise RuntimeError("Non-empty output exists without matching state")
    batch = []
    with input_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {input_path}:{line_number}") from exc
            space_id = str(record.get("spaceId") or "").strip()
            if not space_id:
                continue
            population = str(record.get("status") or "unknown")
            batch.append((space_id, population, PRIORITY.get(population, 2)))
            if len(batch) >= 10_000:
                with db:
                    db.executemany(
                        "INSERT OR IGNORE INTO wanted(dataset_id,population,priority) VALUES(?,?,?)",
                        batch,
                    )
                batch.clear()
    if batch:
        with db:
            db.executemany(
                "INSERT OR IGNORE INTO wanted(dataset_id,population,priority) VALUES(?,?,?)",
                batch,
            )
    with db:
        base.state_set(db, "configuration", config)
        base.state_set(db, "output_offset", 0)
        base.state_set(db, "total", db.execute("SELECT COUNT(*) FROM wanted").fetchone()[0])
        base.state_set(db, "completed", 0)
        for status in ("ok", "no_readme", "restricted", "too_large", "error"):
            base.state_set(db, status, 0)
        base.state_set(db, "finished", 0)


def readme_url(space_id: str) -> str:
    encoded = "/".join(quote(part, safe="._-") for part in space_id.split("/"))
    return f"https://huggingface.co/spaces/{encoded}/raw/main/README.md"


ORIGINAL_FETCH = base.fetch


def fetch(space_id: str, token: str | None, timeout: float, retries: int) -> dict:
    result = ORIGINAL_FETCH(space_id, token, timeout, retries)
    result["spaceId"] = space_id
    return result


def main() -> int:
    base.CHANGE_ID = CHANGE_ID
    base.DEFAULT_INPUT = DEFAULT_INPUT
    base.DEFAULT_OUTPUT = DEFAULT_OUTPUT
    base.PRIORITY = PRIORITY
    base.parse_args = parse_args
    base.initialize = initialize
    base.readme_url = readme_url
    base.fetch = fetch
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
