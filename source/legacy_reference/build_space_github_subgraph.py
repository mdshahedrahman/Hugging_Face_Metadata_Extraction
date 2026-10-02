#!/usr/bin/env python3
"""Build a direct Space-to-GitHub subgraph from Space-card metadata.

Created: 2026-09-24
Version: v2026.09.24-01
Purpose: Emit graph-ready and evidence-preserving Space-GitHub relationships
         without inferring transitive links through models or datasets.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from model_license_task_github_edges import candidate_github


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "all_space_card_metadata_2026Sep24.jsonl"
SIMPLE_FIELDS = ["source", "edge_type", "target"]
DETAILED_FIELDS = SIMPLE_FIELDS + ["evidence", "confidence"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Space-GitHub subgraph.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=SCRIPT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "csv": output_dir / "space_github_edges.csv",
        "jsonl": output_dir / "space_github_edges.jsonl",
        "detailed_csv": output_dir / "space_github_edges_detailed.csv",
        "detailed_jsonl": output_dir / "space_github_edges_detailed.jsonl",
    }
    existing = [p for p in paths.values() if p.exists()]
    if existing:
        raise FileExistsError("Refusing to overwrite:\n" + "\n".join(map(str, existing)))

    edges: dict[tuple[str, str, str], tuple[str, str]] = {}
    records = metadata_records = invalid = 0
    with input_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON line {line_number}: {exc}") from exc
            records += 1
            space_id = record.get("spaceId")
            metadata = record.get("card_metadata")
            if not isinstance(space_id, str) or not space_id.strip():
                invalid += 1
                continue
            if not isinstance(metadata, dict) or not metadata:
                continue
            metadata_records += 1
            for repository, (evidence, confidence) in candidate_github(metadata).items():
                key = (f"space::{space_id.strip()}", "links_to_github", f"github::{repository}")
                previous = edges.get(key)
                if previous is None or (previous[1] != "declared_link" and confidence == "declared_link"):
                    edges[key] = (evidence, confidence)

    with (
        paths["csv"].open("x", newline="", encoding="utf-8") as csv_file,
        paths["jsonl"].open("x", encoding="utf-8") as jsonl_file,
        paths["detailed_csv"].open("x", newline="", encoding="utf-8") as detailed_csv,
        paths["detailed_jsonl"].open("x", encoding="utf-8") as detailed_jsonl,
    ):
        writer = csv.DictWriter(csv_file, fieldnames=SIMPLE_FIELDS)
        detailed_writer = csv.DictWriter(detailed_csv, fieldnames=DETAILED_FIELDS)
        writer.writeheader()
        detailed_writer.writeheader()
        for key in sorted(edges):
            source, edge_type, target = key
            evidence, confidence = edges[key]
            simple = {"source": source, "edge_type": edge_type, "target": target}
            detailed = {**simple, "evidence": evidence, "confidence": confidence}
            writer.writerow(simple)
            detailed_writer.writerow(detailed)
            jsonl_file.write(json.dumps(simple, ensure_ascii=False, separators=(",", ":")) + "\n")
            detailed_jsonl.write(json.dumps(detailed, ensure_ascii=False, separators=(",", ":")) + "\n")

    print(f"Space records:          {records:12,}")
    print(f"Cards with metadata:    {metadata_records:12,}")
    print(f"Space-GitHub edges:     {len(edges):12,}")
    print(f"Invalid Space records:  {invalid:12,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
