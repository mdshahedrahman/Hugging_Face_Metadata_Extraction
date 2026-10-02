#!/usr/bin/env python3
"""Download Hugging Face Space-to-model and Space-to-dataset metadata.

Created: 2026-09-24
Version: v2026.09.24-02
Purpose: Enumerate public Spaces through the Hub API and preserve the
         platform-indexed ``models`` and ``datasets`` relationships.

This is a standalone, resumable collector. It does not modify any existing
HuggingGraph artifact. The SQLite state file records the committed JSONL byte
offset and the exact next-page URL so an interrupted crawl can resume safely.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import requests
from huggingface_hub import get_token


CHANGE_ID = "v2026.09.24-02"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "all_space_relationship_metadata_2026Sep24.jsonl"
API_URL = "https://huggingface.co/api/spaces"
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
LINK_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect Space IDs and their linked models/datasets."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--state-db", type=Path,
        help="Resume database (default: <output>.state.sqlite3)",
    )
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--request-interval", type=float, default=0.7)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-retries", type=int, default=8)
    parser.add_argument(
        "--max-pages", type=int, default=0,
        help="Maximum pages in this invocation; 0 means no limit.",
    )
    return parser.parse_args()


def state_get(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute(
        "SELECT value FROM state WHERE key = ?", (key,)
    ).fetchone()
    return None if row is None else str(row[0])


def state_set(connection: sqlite3.Connection, key: str, value: Any) -> None:
    connection.execute(
        """
        INSERT INTO state(key, value) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, str(value)),
    )


def connect_state(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS emitted_spaces(space_id TEXT PRIMARY KEY)"
    )
    connection.commit()
    return connection


def next_link(header: str | None) -> str | None:
    if not header:
        return None
    for part in header.split(","):
        match = LINK_NEXT.search(part)
        if match:
            return match.group(1)
    return None


def retry_delay(response: requests.Response | None, attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                try:
                    when = parsedate_to_datetime(retry_after)
                    return max(0.0, when.timestamp() - time.time())
                except (TypeError, ValueError):
                    pass
    return min(120.0, 2.0 ** attempt)


def request_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any] | None,
    timeout: float,
    max_retries: int,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        response: requests.Response | None = None
        try:
            response = session.get(url, params=params, timeout=timeout)
            if response.status_code not in TRANSIENT_STATUS_CODES:
                response.raise_for_status()
                return response
            last_error = RuntimeError(
                f"Hub returned transient HTTP {response.status_code}"
            )
        except requests.RequestException as exc:
            last_error = exc
        if attempt == max_retries:
            break
        time.sleep(retry_delay(response, attempt))
    raise RuntimeError(f"Unable to download {url}: {last_error}")


def validate_args(args: argparse.Namespace) -> tuple[Path, Path]:
    output = args.output.expanduser().resolve()
    state = (
        args.state_db.expanduser().resolve()
        if args.state_db
        else output.with_name(output.name + ".state.sqlite3")
    )
    if output == state:
        raise ValueError("Output and state database paths must differ")
    if not 1 <= args.page_size <= 1000:
        raise ValueError("--page-size must be between 1 and 1000")
    if args.request_interval < 0 or args.timeout <= 0:
        raise ValueError("Invalid request interval or timeout")
    if args.max_retries < 0 or args.max_pages < 0:
        raise ValueError("Retry and page limits cannot be negative")
    return output, state


def initialize_state(
    connection: sqlite3.Connection, output: Path, args: argparse.Namespace
) -> None:
    configuration = json.dumps(
        {
            "change_id": CHANGE_ID,
            "output": str(output),
            "page_size": args.page_size,
            "expand": ["models", "datasets"],
        },
        sort_keys=True,
    )
    stored = state_get(connection, "configuration")
    if stored is not None and stored != configuration:
        raise RuntimeError("State database belongs to another configuration")
    if stored is None:
        if output.exists() and output.stat().st_size:
            raise RuntimeError("Non-empty output exists without matching state")
        with connection:
            state_set(connection, "configuration", configuration)
            state_set(connection, "output_offset", 0)
            state_set(connection, "next_url", API_URL)
            state_set(connection, "first_page", 1)
            state_set(connection, "pages", 0)
            state_set(connection, "spaces", 0)
            state_set(connection, "finished", 0)


def reconcile_output(
    connection: sqlite3.Connection, output: Path
):
    output.parent.mkdir(parents=True, exist_ok=True)
    stream = output.open("a+b")
    committed = int(state_get(connection, "output_offset") or "0")
    stream.seek(0, os.SEEK_END)
    actual = stream.tell()
    if actual < committed:
        stream.close()
        raise RuntimeError(f"Output is shorter than committed state: {actual} < {committed}")
    if actual > committed:
        stream.truncate(committed)
        stream.seek(committed)
        stream.flush()
        os.fsync(stream.fileno())
    return stream


def normalized_record(item: dict[str, Any], retrieved: str) -> dict[str, Any] | None:
    space_id = item.get("id")
    if not isinstance(space_id, str) or not space_id.strip():
        return None
    models = sorted({x.strip() for x in item.get("models") or [] if isinstance(x, str) and x.strip()})
    datasets = sorted({x.strip() for x in item.get("datasets") or [] if isinstance(x, str) and x.strip()})
    return {
        "spaceId": space_id.strip(),
        "models": models,
        "datasets": datasets,
        "retrieved_at_utc": retrieved,
        "source": "https://huggingface.co/api/spaces?expand=models&expand=datasets",
        "status": "ok",
    }


def main() -> int:
    args = parse_args()
    output, state_path = validate_args(args)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_state(state_path)
    initialize_state(connection, output, args)
    if state_get(connection, "finished") == "1":
        print(f"Already complete: {output}")
        return 0

    token = get_token()
    session = requests.Session()
    session.headers.update({"User-Agent": f"HuggingGraph-Spaces/{CHANGE_ID}"})
    if token:
        session.headers["Authorization"] = f"Bearer {token}"

    stream = reconcile_output(connection, output)
    next_url = state_get(connection, "next_url") or API_URL
    first_page = state_get(connection, "first_page") == "1"
    pages_this_run = 0

    try:
        while next_url and (args.max_pages == 0 or pages_this_run < args.max_pages):
            started = time.monotonic()
            params = (
                {
                    "limit": args.page_size,
                    "expand": ["models", "datasets"],
                }
                if first_page
                else None
            )
            response = request_page(
                session, next_url, params, args.timeout, args.max_retries
            )
            payload = response.json()
            if not isinstance(payload, list):
                raise RuntimeError("Hub response is not a list")
            retrieved = datetime.now(timezone.utc).isoformat()
            records: list[tuple[str, bytes]] = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                record = normalized_record(item, retrieved)
                if record is None:
                    continue
                space_id = record["spaceId"]
                exists = connection.execute(
                    "SELECT 1 FROM emitted_spaces WHERE space_id = ?", (space_id,)
                ).fetchone()
                if exists is None:
                    line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                    records.append((space_id, line))

            for _, line in records:
                stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
            offset = stream.tell()
            following = next_link(response.headers.get("Link"))
            with connection:
                connection.executemany(
                    "INSERT OR IGNORE INTO emitted_spaces(space_id) VALUES(?)",
                    [(space_id,) for space_id, _ in records],
                )
                pages = int(state_get(connection, "pages") or "0") + 1
                spaces = int(state_get(connection, "spaces") or "0") + len(records)
                state_set(connection, "output_offset", offset)
                state_set(connection, "pages", pages)
                state_set(connection, "spaces", spaces)
                state_set(connection, "next_url", following or "")
                state_set(connection, "first_page", 0)
                if following is None:
                    state_set(connection, "finished", 1)
            pages_this_run += 1
            print(
                f"pages={pages:,} spaces={spaces:,} new={len(records):,}",
                flush=True,
            )
            next_url = following
            first_page = False
            elapsed = time.monotonic() - started
            if next_url and elapsed < args.request_interval:
                time.sleep(args.request_interval - elapsed)
    finally:
        stream.close()
        connection.close()

    if next_url:
        print("Stopped at --max-pages; rerun the same command to resume.")
    else:
        print(f"Complete: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
