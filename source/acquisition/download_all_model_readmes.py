#!/usr/bin/env python3
"""Download full README Markdown for the complete saved model population.

Created: 2026-09-25
Version: v2026.09.25-02
Purpose: Collect resumable README-body evidence for full Model-GitHub coverage.

The three saved population partitions are indexed into SQLite in the requested
order. Completed records from the focused model-tree crawl are reused. The
script fetches text only; it does not clone repositories or execute model code.
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


CHANGE_ID = "v2026.09.25-02"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUTS = (
    SCRIPT_DIR / "models_with_metadata.jsonl",
    SCRIPT_DIR / "models_without_metadata.jsonl",
    SCRIPT_DIR / "models_not_returned_by_api.jsonl",
)
DEFAULT_REUSE = SCRIPT_DIR / "model_tree_source_readmes_2026Sep25.jsonl"
DEFAULT_OUTPUT = SCRIPT_DIR / "all_model_readmes_full_2026Sep25.jsonl"
TRANSIENT = {429, 500, 502, 503, 504}
MAX_README_BYTES = 10 * 1024 * 1024
RATE_LIMIT_COOLDOWN_SECONDS = 120.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download all model README files.")
    parser.add_argument("--inputs", nargs=3, type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--reuse", type=Path, default=DEFAULT_REUSE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--max-models", type=int, default=0)
    return parser.parse_args()


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS wanted("
        "model_id TEXT PRIMARY KEY,population TEXT NOT NULL,priority INTEGER NOT NULL,"
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


def configuration(inputs: list[Path], reuse: Path, output: Path) -> str:
    def identity(path: Path) -> dict[str, object]:
        stat = path.stat()
        return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}

    return json.dumps(
        {
            "change_id": CHANGE_ID,
            "inputs": [identity(path) for path in inputs],
            "reuse": identity(reuse),
            "output": str(output),
        },
        sort_keys=True,
    )


def records(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}") from exc
            yield record


def initialize(db: sqlite3.Connection, inputs: list[Path], reuse: Path, output: Path) -> None:
    config = configuration(inputs, reuse, output)
    stored = state_get(db, "configuration")
    if stored is not None and stored != config:
        previous = json.loads(stored)
        current = json.loads(config)
        previous.pop("change_id", None)
        current.pop("change_id", None)
        if previous != current:
            raise RuntimeError("State database belongs to another configuration")
        with db:
            state_set(db, "configuration", config)
    if stored is not None:
        return
    if output.exists() and output.stat().st_size:
        raise RuntimeError("Non-empty output exists without matching state")

    population_names = ("with_metadata", "without_metadata", "not_returned_by_api")
    for priority, (path, population) in enumerate(zip(inputs, population_names)):
        batch: list[tuple[str, str, int]] = []
        for record in records(path):
            model_id = str(record.get("modelId") or "").strip()
            if not model_id:
                continue
            batch.append((model_id, population, priority))
            if len(batch) >= 10_000:
                with db:
                    db.executemany(
                        "INSERT OR IGNORE INTO wanted(model_id,population,priority) VALUES(?,?,?)",
                        batch,
                    )
                batch.clear()
        if batch:
            with db:
                db.executemany(
                    "INSERT OR IGNORE INTO wanted(model_id,population,priority) VALUES(?,?,?)",
                    batch,
                )

    reusable: dict[str, dict] = {}
    for record in records(reuse):
        model_id = str(record.get("modelId") or "").strip()
        if model_id and record.get("status") in {"ok", "no_readme", "restricted", "too_large"}:
            reusable[model_id] = record

    with output.open("a+b") as stream:
        reused_counts: dict[str, int] = {}
        reused = 0
        for model_id in sorted(reusable):
            row = db.execute("SELECT population FROM wanted WHERE model_id=?", (model_id,)).fetchone()
            if row is None:
                continue
            record = dict(reusable[model_id])
            record["population"] = row[0]
            record["reused_from"] = reuse.name
            stream.write((json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
            status = str(record["status"])
            db.execute("UPDATE wanted SET emitted=1,status=? WHERE model_id=?", (status, model_id))
            reused_counts[status] = reused_counts.get(status, 0) + 1
            reused += 1
        stream.flush()
        os.fsync(stream.fileno())
        with db:
            state_set(db, "configuration", config)
            state_set(db, "output_offset", stream.tell())
            state_set(db, "total", db.execute("SELECT COUNT(*) FROM wanted").fetchone()[0])
            state_set(db, "completed", reused)
            for status in ("ok", "no_readme", "restricted", "too_large", "error"):
                state_set(db, status, reused_counts.get(status, 0))
            state_set(db, "reused", reused)
            state_set(db, "finished", 0)


def readme_url(model_id: str) -> str:
    encoded = "/".join(quote(part, safe="._-") for part in model_id.split("/"))
    return f"https://huggingface.co/{encoded}/raw/main/README.md"


def fetch(model_id: str, token: str | None, timeout: float, retries: int) -> dict:
    url = readme_url(model_id)
    headers = {"User-Agent": f"HuggingGraph-Full-README/{CHANGE_ID}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    error = None
    for attempt in range(retries + 1):
        response = None
        try:
            response = requests.get(url, headers=headers, timeout=timeout, stream=True)
            if response.status_code == 404:
                return {"modelId": model_id, "url": url, "status": "no_readme", "readme": None}
            if response.status_code in {401, 403}:
                return {"modelId": model_id, "url": url, "status": "restricted", "readme": None}
            if response.status_code not in TRANSIENT:
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_content(65_536):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > MAX_README_BYTES:
                        return {"modelId": model_id, "url": url, "status": "too_large", "readme": None}
                    chunks.append(chunk)
                markdown = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                return {"modelId": model_id, "url": url, "status": "ok", "readme": markdown}
            error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            error = str(exc)
        if attempt < retries:
            delay = min(60.0, 2.0**attempt)
            if response is not None and response.headers.get("Retry-After", "").isdigit():
                delay = max(delay, float(response.headers["Retry-After"]))
            time.sleep(delay)
    status = "retry_later" if error == "HTTP 429" else "error"
    return {"modelId": model_id, "url": url, "status": status, "error": error, "readme": None}


def main() -> int:
    args = parse_args()
    if args.workers < 1 or args.batch_size < 1 or args.timeout <= 0 or args.max_models < 0:
        raise ValueError("Invalid arguments")
    inputs = [path.expanduser().resolve() for path in args.inputs]
    reuse = args.reuse.expanduser().resolve()
    output = args.output.expanduser().resolve()
    state_path = (
        args.state_db.expanduser().resolve()
        if args.state_db
        else output.with_name(output.name + ".state.sqlite3")
    )
    if not all(path.is_file() for path in [*inputs, reuse]):
        raise FileNotFoundError("One or more input files do not exist")
    if len({*inputs, reuse, output, state_path}) != 6:
        raise ValueError("Input and output paths must be distinct")
    output.parent.mkdir(parents=True, exist_ok=True)

    db = connect(state_path)
    initialize(db, inputs, reuse, output)
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

    token = get_token()
    processed_this_run = 0
    try:
        while args.max_models == 0 or processed_this_run < args.max_models:
            remaining = args.batch_size
            if args.max_models:
                remaining = min(remaining, args.max_models - processed_this_run)
            rows = db.execute(
                "SELECT model_id,population FROM wanted WHERE emitted=0 "
                "ORDER BY priority,model_id LIMIT ?",
                (remaining,),
            ).fetchall()
            if not rows:
                with db:
                    state_set(db, "finished", 1)
                break
            populations = {model_id: population for model_id, population in rows}
            results = []
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {
                    pool.submit(fetch, model_id, token, args.timeout, args.max_retries): model_id
                    for model_id, _ in rows
                }
                for future in as_completed(futures):
                    result = future.result()
                    result["population"] = populations[result["modelId"]]
                    result["retrieved_at_utc"] = datetime.now(timezone.utc).isoformat()
                    results.append(result)
            results.sort(key=lambda item: item["modelId"])
            retry_later = [item for item in results if item["status"] == "retry_later"]
            terminal_results = [item for item in results if item["status"] != "retry_later"]
            for result in terminal_results:
                stream.write((json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())

            completed = int(state_get(db, "completed") or 0) + len(terminal_results)
            counts = {
                status: int(state_get(db, status) or 0)
                for status in ("ok", "no_readme", "restricted", "too_large", "error")
            }
            for result in terminal_results:
                counts[result["status"]] += 1
            with db:
                db.executemany(
                    "UPDATE wanted SET emitted=1,status=? WHERE model_id=?",
                    [(item["status"], item["modelId"]) for item in terminal_results],
                )
                state_set(db, "output_offset", stream.tell())
                state_set(db, "completed", completed)
                for status, count in counts.items():
                    state_set(db, status, count)
            processed_this_run += len(terminal_results)
            print(
                f"completed={completed:,}/{int(state_get(db, 'total') or 0):,} "
                f"ok={counts['ok']:,} no_readme={counts['no_readme']:,} "
                f"restricted={counts['restricted']:,} too_large={counts['too_large']:,} "
                f"errors={counts['error']:,} retry_later={len(retry_later):,}",
                flush=True,
            )
            if retry_later:
                print(
                    f"HTTP 429 persisted for {len(retry_later):,} model(s); "
                    f"cooling down for {RATE_LIMIT_COOLDOWN_SECONDS:.0f} seconds.",
                    flush=True,
                )
                time.sleep(RATE_LIMIT_COOLDOWN_SECONDS)
    finally:
        stream.close()
        db.close()
    print("Complete." if not rows else "Stopped at --max-models; rerun to resume.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
