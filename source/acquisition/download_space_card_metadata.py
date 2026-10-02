#!/usr/bin/env python3
"""Download parsed Hugging Face Space-card front matter in bulk.

Created: 2026-09-24
Version: v2026.09.24-01
Purpose: Build a resumable Space-card snapshot for direct Space attributes,
         including any GitHub URLs explicitly recorded in card metadata.

This collector creates new artifacts only and does not modify existing graph
or metadata files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from huggingface_hub import get_token


CHANGE_ID = "v2026.09.24-01"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "all_space_card_metadata_2026Sep24.jsonl"
API_URL = "https://huggingface.co/api/spaces"
TRANSIENT = {429, 500, 502, 503, 504}
NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect parsed Space-card metadata.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--request-interval", type=float, default=0.7)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-retries", type=int, default=8)
    parser.add_argument("--max-pages", type=int, default=0)
    return parser.parse_args()


def state_get(db: sqlite3.Connection, key: str) -> str | None:
    row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return None if row is None else str(row[0])


def state_set(db: sqlite3.Connection, key: str, value: Any) -> None:
    db.execute(
        "INSERT INTO state(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS emitted(space_id TEXT PRIMARY KEY)")
    db.commit()
    return db


def next_url(header: str | None) -> str | None:
    if not header:
        return None
    for part in header.split(","):
        match = NEXT_LINK.search(part)
        if match:
            return match.group(1)
    return None


def get_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any] | None,
    timeout: float,
    retries: int,
) -> requests.Response:
    error: Exception | None = None
    for attempt in range(retries + 1):
        response: requests.Response | None = None
        try:
            response = session.get(url, params=params, timeout=timeout)
            if response.status_code not in TRANSIENT:
                response.raise_for_status()
                return response
            error = RuntimeError(f"transient HTTP {response.status_code}")
        except requests.RequestException as exc:
            error = exc
        if attempt == retries:
            break
        delay = min(120.0, 2.0 ** attempt)
        if response is not None and response.headers.get("Retry-After", "").isdigit():
            delay = max(delay, float(response.headers["Retry-After"]))
        time.sleep(delay)
    raise RuntimeError(f"Unable to download {url}: {error}")


def main() -> int:
    args = parse_args()
    if not 1 <= args.page_size <= 1000:
        raise ValueError("--page-size must be between 1 and 1000")
    if args.request_interval < 0 or args.timeout <= 0:
        raise ValueError("Invalid timing arguments")
    output = args.output.expanduser().resolve()
    state_path = (
        args.state_db.expanduser().resolve()
        if args.state_db
        else output.with_name(output.name + ".state.sqlite3")
    )
    if output == state_path:
        raise ValueError("Output and state paths must differ")
    output.parent.mkdir(parents=True, exist_ok=True)
    db = connect(state_path)
    config = json.dumps(
        {"change_id": CHANGE_ID, "output": str(output), "page_size": args.page_size},
        sort_keys=True,
    )
    stored = state_get(db, "configuration")
    if stored is not None and stored != config:
        raise RuntimeError("State database belongs to another configuration")
    if stored is None:
        if output.exists() and output.stat().st_size:
            raise RuntimeError("Non-empty output exists without matching state")
        with db:
            state_set(db, "configuration", config)
            state_set(db, "output_offset", 0)
            state_set(db, "next_url", API_URL)
            state_set(db, "first_page", 1)
            state_set(db, "pages", 0)
            state_set(db, "spaces", 0)
            state_set(db, "with_metadata", 0)
            state_set(db, "finished", 0)
    if state_get(db, "finished") == "1":
        print(f"Already complete: {output}")
        return 0

    stream = output.open("a+b")
    committed = int(state_get(db, "output_offset") or 0)
    stream.seek(0, os.SEEK_END)
    if stream.tell() < committed:
        raise RuntimeError("Output is shorter than committed state")
    if stream.tell() > committed:
        stream.truncate(committed)
        stream.seek(committed)
        stream.flush()
        os.fsync(stream.fileno())

    session = requests.Session()
    session.headers["User-Agent"] = f"HuggingGraph-SpaceCards/{CHANGE_ID}"
    token = get_token()
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    url = state_get(db, "next_url") or API_URL
    first = state_get(db, "first_page") == "1"
    run_pages = 0
    try:
        while url and (args.max_pages == 0 or run_pages < args.max_pages):
            started = time.monotonic()
            params = {"limit": args.page_size, "expand": ["cardData"]} if first else None
            response = get_page(session, url, params, args.timeout, args.max_retries)
            payload = response.json()
            if not isinstance(payload, list):
                raise RuntimeError("Hub response is not a list")
            retrieved = datetime.now(timezone.utc).isoformat()
            records: list[tuple[str, bytes, int]] = []
            for item in payload:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    continue
                space_id = item["id"].strip()
                if not space_id or db.execute(
                    "SELECT 1 FROM emitted WHERE space_id=?", (space_id,)
                ).fetchone():
                    continue
                card = item.get("cardData")
                has_metadata = int(isinstance(card, dict) and bool(card))
                record = {
                    "spaceId": space_id,
                    "card_metadata": card if isinstance(card, dict) else {},
                    "retrieved_at_utc": retrieved,
                    "source": "https://huggingface.co/api/spaces?expand=cardData",
                    "status": "with_metadata" if has_metadata else "empty_metadata",
                }
                line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
                records.append((space_id, line, has_metadata))
            for _, line, _ in records:
                stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
            following = next_url(response.headers.get("Link"))
            with db:
                db.executemany("INSERT OR IGNORE INTO emitted(space_id) VALUES(?)", [(x[0],) for x in records])
                pages = int(state_get(db, "pages") or 0) + 1
                spaces = int(state_get(db, "spaces") or 0) + len(records)
                with_metadata = int(state_get(db, "with_metadata") or 0) + sum(x[2] for x in records)
                state_set(db, "output_offset", stream.tell())
                state_set(db, "next_url", following or "")
                state_set(db, "first_page", 0)
                state_set(db, "pages", pages)
                state_set(db, "spaces", spaces)
                state_set(db, "with_metadata", with_metadata)
                if following is None:
                    state_set(db, "finished", 1)
            run_pages += 1
            print(f"pages={pages:,} spaces={spaces:,} with_metadata={with_metadata:,}", flush=True)
            url, first = following, False
            elapsed = time.monotonic() - started
            if url and elapsed < args.request_interval:
                time.sleep(args.request_interval - elapsed)
    finally:
        stream.close()
        db.close()
    print("Complete." if not url else "Stopped at --max-pages; rerun to resume.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
