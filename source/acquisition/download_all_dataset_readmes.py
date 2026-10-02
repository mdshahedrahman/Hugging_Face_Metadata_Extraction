#!/usr/bin/env python3
"""Download full README Markdown for the saved Hugging Face dataset population.

Created: 2026-09-28
Version: v2026.09.28-01
Purpose: Collect resumable README-body evidence for Dataset-GitHub coverage.

The script fetches text only. It does not clone repositories or execute code.
Persistent HTTP 429 responses remain pending and trigger a global cooldown.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from huggingface_hub import get_token


CHANGE_ID = "v2026.09.28-01"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "all_dataset_readme_metadata_2026Aug28.jsonl"
DEFAULT_OUTPUT = SCRIPT_DIR / "all_dataset_readmes_full_2026Sep28.jsonl"
TRANSIENT = {429, 500, 502, 503, 504}
MAX_README_BYTES = 10 * 1024 * 1024
RATE_LIMIT_COOLDOWN_SECONDS = 120.0
PRIORITY = {"with_metadata": 0, "no_metadata": 1, "not_returned_by_datasets_api": 2}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download all dataset README files.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--max-datasets", type=int, default=0)
    return parser.parse_args()


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS wanted("
        "dataset_id TEXT PRIMARY KEY,population TEXT NOT NULL,priority INTEGER NOT NULL,"
        "emitted INTEGER NOT NULL DEFAULT 0,status TEXT)"
    )
    db.commit()
    return db


def state_get(db: sqlite3.Connection, key: str) -> str | None:
    row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return None if row is None else str(row[0])


def state_set(db: sqlite3.Connection, key: str, value: object) -> None:
    db.execute(
        "INSERT INTO state(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def initialize(db: sqlite3.Connection, input_path: Path, output_path: Path) -> None:
    stat = input_path.stat()
    config = json.dumps(
        {
            "change_id": CHANGE_ID,
            "input": str(input_path),
            "input_size": stat.st_size,
            "input_mtime_ns": stat.st_mtime_ns,
            "output": str(output_path),
        },
        sort_keys=True,
    )
    stored = state_get(db, "configuration")
    if stored is not None and stored != config:
        raise RuntimeError("State database belongs to another configuration")
    if stored is not None:
        return
    if output_path.exists() and output_path.stat().st_size:
        raise RuntimeError("Non-empty output exists without matching state")

    batch: list[tuple[str, str, int]] = []
    with input_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {input_path}:{line_number}") from exc
            dataset_id = str(record.get("datasetId") or "").strip()
            if not dataset_id:
                continue
            population = str(record.get("status") or "unknown")
            batch.append((dataset_id, population, PRIORITY.get(population, 3)))
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
        state_set(db, "configuration", config)
        state_set(db, "output_offset", 0)
        state_set(db, "total", db.execute("SELECT COUNT(*) FROM wanted").fetchone()[0])
        state_set(db, "completed", 0)
        for status in ("ok", "no_readme", "restricted", "too_large", "error"):
            state_set(db, status, 0)
        state_set(db, "finished", 0)


def readme_url(dataset_id: str) -> str:
    encoded = "/".join(quote(part, safe="._-") for part in dataset_id.split("/"))
    return f"https://huggingface.co/datasets/{encoded}/raw/main/README.md"


def fetch(dataset_id: str, token: str | None, timeout: float, retries: int) -> dict:
    url = readme_url(dataset_id)
    headers = {"User-Agent": f"HuggingGraph-Dataset-README/{CHANGE_ID}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    error = None
    for attempt in range(retries + 1):
        response = None
        try:
            response = requests.get(url, headers=headers, timeout=timeout, stream=True)
            if response.status_code == 404:
                return {"datasetId": dataset_id, "url": url, "status": "no_readme", "readme": None}
            if response.status_code in {401, 403}:
                return {"datasetId": dataset_id, "url": url, "status": "restricted", "readme": None}
            if response.status_code not in TRANSIENT:
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_content(65_536):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > MAX_README_BYTES:
                        return {"datasetId": dataset_id, "url": url, "status": "too_large", "readme": None}
                    chunks.append(chunk)
                markdown = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                return {"datasetId": dataset_id, "url": url, "status": "ok", "readme": markdown}
            error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            error = str(exc)
        if attempt < retries:
            delay = min(60.0, 2.0**attempt)
            if response is not None and response.headers.get("Retry-After", "").isdigit():
                delay = max(delay, float(response.headers["Retry-After"]))
            time.sleep(delay)
    status = "retry_later" if error == "HTTP 429" else "error"
    return {"datasetId": dataset_id, "url": url, "status": status, "error": error, "readme": None}


def main() -> int:
    args = parse_args()
    if args.workers < 1 or args.batch_size < 1 or args.timeout <= 0 or args.max_datasets < 0:
        raise ValueError("Invalid arguments")
    input_path = args.input.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    state_path = (
        args.state_db.expanduser().resolve()
        if args.state_db
        else output_path.with_name(output_path.name + ".state.sqlite3")
    )
    if not input_path.is_file() or len({input_path, output_path, state_path}) != 3:
        raise ValueError("Invalid or overlapping paths")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    db = connect(state_path)
    initialize(db, input_path, output_path)
    if state_get(db, "finished") == "1":
        print(f"Already complete: {output_path}")
        return 0

    stream = output_path.open("a+b")
    committed = int(state_get(db, "output_offset") or 0)
    stream.seek(0, os.SEEK_END)
    if stream.tell() < committed:
        raise RuntimeError("Output is shorter than committed state")
    if stream.tell() > committed:
        stream.truncate(committed)
        stream.seek(committed)
        stream.flush()
        os.fsync(stream.fileno())

    token = get_token()
    processed_this_run = 0
    rows = []
    try:
        while args.max_datasets == 0 or processed_this_run < args.max_datasets:
            remaining = args.batch_size
            if args.max_datasets:
                remaining = min(remaining, args.max_datasets - processed_this_run)
            rows = db.execute(
                "SELECT dataset_id,population FROM wanted WHERE emitted=0 "
                "ORDER BY priority,dataset_id LIMIT ?",
                (remaining,),
            ).fetchall()
            if not rows:
                with db:
                    state_set(db, "finished", 1)
                break
            populations = {dataset_id: population for dataset_id, population in rows}
            results = []
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {
                    pool.submit(fetch, dataset_id, token, args.timeout, args.max_retries): dataset_id
                    for dataset_id, _ in rows
                }
                for future in as_completed(futures):
                    result = future.result()
                    result["population"] = populations[result["datasetId"]]
                    result["retrieved_at_utc"] = datetime.now(timezone.utc).isoformat()
                    results.append(result)
            results.sort(key=lambda item: item["datasetId"])
            retry_later = [item for item in results if item["status"] == "retry_later"]
            terminal = [item for item in results if item["status"] != "retry_later"]
            for result in terminal:
                stream.write((json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
            completed = int(state_get(db, "completed") or 0) + len(terminal)
            counts = {
                status: int(state_get(db, status) or 0)
                for status in ("ok", "no_readme", "restricted", "too_large", "error")
            }
            for result in terminal:
                counts[result["status"]] += 1
            with db:
                db.executemany(
                    "UPDATE wanted SET emitted=1,status=? WHERE dataset_id=?",
                    [(item["status"], item["datasetId"]) for item in terminal],
                )
                state_set(db, "output_offset", stream.tell())
                state_set(db, "completed", completed)
                for status, count in counts.items():
                    state_set(db, status, count)
            processed_this_run += len(terminal)
            print(
                f"completed={completed:,}/{int(state_get(db, 'total') or 0):,} "
                f"ok={counts['ok']:,} no_readme={counts['no_readme']:,} "
                f"restricted={counts['restricted']:,} too_large={counts['too_large']:,} "
                f"errors={counts['error']:,} retry_later={len(retry_later):,}",
                flush=True,
            )
            if retry_later:
                print(
                    f"HTTP 429 persisted for {len(retry_later):,} dataset(s); "
                    f"cooling down for {RATE_LIMIT_COOLDOWN_SECONDS:.0f} seconds.",
                    flush=True,
                )
                time.sleep(RATE_LIMIT_COOLDOWN_SECONDS)
    finally:
        stream.close()
        db.close()
    print("Complete." if not rows else "Stopped at --max-datasets; rerun to resume.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
