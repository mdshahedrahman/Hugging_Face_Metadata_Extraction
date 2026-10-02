#!/usr/bin/env python3
"""Download README files for unique source models in model_tree_models.csv.

Created: 2026-09-25
Version: v2026.09.25-01
Purpose: Collect full model-card Markdown for focused GitHub-link extraction.

The crawl is resumable and fetches text only. It never clones repositories or
executes model code. Existing HuggingGraph artifacts are not modified.
"""

from __future__ import annotations

import argparse
import csv
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


CHANGE_ID = "v2026.09.25-01"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "model_tree_models.csv"
DEFAULT_OUTPUT = SCRIPT_DIR / "model_tree_source_readmes_2026Sep25.jsonl"
TRANSIENT = {429, 500, 502, 503, 504}
MAX_README_BYTES = 10 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download model-tree source READMEs.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=120)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--max-models", type=int, default=0)
    return parser.parse_args()


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS wanted(model_id TEXT PRIMARY KEY, emitted INTEGER NOT NULL DEFAULT 0)")
    db.commit()
    return db


def state_get(db: sqlite3.Connection, key: str) -> str | None:
    row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return None if row is None else str(row[0])


def state_set(db: sqlite3.Connection, key: str, value: object) -> None:
    db.execute(
        "INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def initialize(db: sqlite3.Connection, input_path: Path, output_path: Path) -> None:
    stat = input_path.stat()
    configuration = json.dumps(
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
    if stored is not None and stored != configuration:
        raise RuntimeError("State database belongs to another configuration")
    if stored is not None:
        return
    if output_path.exists() and output_path.stat().st_size:
        raise RuntimeError("Non-empty output exists without matching state")
    with input_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if "Source" not in (reader.fieldnames or []):
            raise ValueError("Input must contain Source")
        model_ids = sorted({row["Source"].strip() for row in reader if row["Source"].strip()})
    with db:
        db.executemany("INSERT INTO wanted(model_id) VALUES(?)", [(x,) for x in model_ids])
        state_set(db, "configuration", configuration)
        state_set(db, "output_offset", 0)
        state_set(db, "total", len(model_ids))
        state_set(db, "completed", 0)
        state_set(db, "ok", 0)
        state_set(db, "no_readme", 0)
        state_set(db, "restricted", 0)
        state_set(db, "errors", 0)
        state_set(db, "finished", 0)


def readme_url(model_id: str) -> str:
    encoded = "/".join(quote(part, safe="._-") for part in model_id.split("/"))
    return f"https://huggingface.co/{encoded}/raw/main/README.md"


def fetch(model_id: str, token: str | None, timeout: float, retries: int) -> dict:
    url = readme_url(model_id)
    headers = {"User-Agent": f"HuggingGraph-README/{CHANGE_ID}"}
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
                chunks=[]; size=0
                for chunk in response.iter_content(65536):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > MAX_README_BYTES:
                        return {"modelId": model_id, "url": url, "status": "too_large", "readme": None}
                    chunks.append(chunk)
                text = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                return {"modelId": model_id, "url": url, "status": "ok", "readme": text}
            error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            error = str(exc)
        if attempt < retries:
            delay = min(60.0, 2.0 ** attempt)
            if response is not None and response.headers.get("Retry-After", "").isdigit():
                delay = max(delay, float(response.headers["Retry-After"]))
            time.sleep(delay)
    return {"modelId": model_id, "url": url, "status": "error", "error": error, "readme": None}


def main() -> int:
    args = parse_args()
    if args.workers < 1 or args.batch_size < 1 or args.timeout <= 0 or args.max_models < 0:
        raise ValueError("Invalid arguments")
    input_path = args.input.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    state_path = args.state_db.expanduser().resolve() if args.state_db else output_path.with_name(output_path.name + ".state.sqlite3")
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
        stream.truncate(committed); stream.seek(committed); stream.flush(); os.fsync(stream.fileno())
    token = get_token(); processed_this_run = 0
    try:
        while args.max_models == 0 or processed_this_run < args.max_models:
            remaining = args.batch_size
            if args.max_models:
                remaining = min(remaining, args.max_models - processed_this_run)
            rows = db.execute("SELECT model_id FROM wanted WHERE emitted=0 ORDER BY model_id LIMIT ?", (remaining,)).fetchall()
            if not rows:
                with db: state_set(db, "finished", 1)
                break
            model_ids = [row[0] for row in rows]
            results=[]
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures={pool.submit(fetch, mid, token, args.timeout, args.max_retries):mid for mid in model_ids}
                for future in as_completed(futures):
                    result=future.result()
                    result["retrieved_at_utc"] = datetime.now(timezone.utc).isoformat()
                    results.append(result)
            results.sort(key=lambda x:x["modelId"])
            for result in results:
                stream.write((json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
            stream.flush(); os.fsync(stream.fileno())
            counts = {key:int(state_get(db,key) or 0) for key in ("completed","ok","no_readme","restricted","errors")}
            for result in results:
                counts["completed"] += 1
                status=result["status"]
                if status == "ok": counts["ok"] += 1
                elif status == "no_readme": counts["no_readme"] += 1
                elif status == "restricted": counts["restricted"] += 1
                else: counts["errors"] += 1
            with db:
                db.executemany("UPDATE wanted SET emitted=1 WHERE model_id=?", [(x["modelId"],) for x in results])
                state_set(db, "output_offset", stream.tell())
                for key,value in counts.items(): state_set(db,key,value)
            processed_this_run += len(results)
            print(
                f"completed={counts['completed']:,}/{int(state_get(db,'total') or 0):,} "
                f"ok={counts['ok']:,} no_readme={counts['no_readme']:,} "
                f"restricted={counts['restricted']:,} errors={counts['errors']:,}",
                flush=True,
            )
    finally:
        stream.close(); db.close()
    print("Complete." if not rows else "Stopped at --max-models; rerun to resume.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
