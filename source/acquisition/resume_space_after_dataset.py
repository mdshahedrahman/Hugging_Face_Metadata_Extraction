#!/usr/bin/env python3
"""Resume the checkpointed Space crawl after Dataset-GitHub completion.

Created: 2026-09-28
Version: v2026.09.28-06
Purpose: Serialize the full Dataset and Space README/GitHub collection jobs.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DATASET_CRAWL_STATE = SCRIPT_DIR / "all_dataset_readmes_full_2026Sep28.jsonl.state.sqlite3"
DATASET_EXTRACT_STATE = SCRIPT_DIR / "dataset_github_edges_full.state.sqlite3"
WATCH_LOG = SCRIPT_DIR / "resume_space_after_dataset.log"
POLL_SECONDS = 5


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with WATCH_LOG.open("a", encoding="utf-8") as stream:
        stream.write(f"{stamp} {message}\n")
        stream.flush()
        os.fsync(stream.fileno())


def state_finished(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        try:
            row = db.execute("SELECT value FROM state WHERE key='finished'").fetchone()
            return row is not None and str(row[0]) == "1"
        finally:
            db.close()
    except sqlite3.Error as exc:
        log(f"waiting: cannot read {path.name}: {exc}")
        return False


def matching_process(fragment: str) -> bool:
    result = subprocess.run(
        ["pgrep", "-af", fragment],
        check=False,
        capture_output=True,
        text=True,
    )
    return any(fragment in line and "resume_space_after_dataset.py" not in line
               for line in result.stdout.splitlines())


def write_pid(path: Path, pid: int) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(f"{pid}\n", encoding="utf-8")
    temporary.replace(path)


def launch(command: list[str], log_name: str, pid_name: str) -> int:
    log_stream = (SCRIPT_DIR / log_name).open("a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=SCRIPT_DIR,
        stdin=subprocess.DEVNULL,
        stdout=log_stream,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_stream.close()
    write_pid(SCRIPT_DIR / pid_name, process.pid)
    return process.pid


def main() -> int:
    log("watcher started; waiting for dataset crawl and extractor completion")
    while not (state_finished(DATASET_CRAWL_STATE) and state_finished(DATASET_EXTRACT_STATE)):
        time.sleep(POLL_SECONDS)

    log("both dataset completion markers found")
    if matching_process("download_all_space_readmes.py") or matching_process(
        "extract_space_github_edges_streaming_full.py"
    ):
        log("Space process already exists; no duplicate launch performed")
        return 2

    downloader_pid = launch(
        [str(SCRIPT_DIR / ".venv/bin/python"), "download_all_space_readmes.py",
         "--workers", "2", "--batch-size", "20"],
        "all_space_readmes_full_2026Sep28.log",
        "all_space_readmes_full_2026Sep28.pid",
    )
    extractor_pid = launch(
        [str(SCRIPT_DIR / ".venv/bin/python"), "extract_space_github_edges_streaming_full.py"],
        "space_github_edges_full.log",
        "space_github_edges_full.pid",
    )
    log(f"resumed Space downloader pid={downloader_pid} extractor pid={extractor_pid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
