#!/usr/bin/env python3
"""Extract GitHub repository links from full model-card Markdown.

Created: 2026-09-25
Version: v2026.09.25-02
Purpose: Add README-body evidence omitted by the Hub ``cardData`` response.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from model_license_task_github_edges import github_repositories


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "model_tree_source_readmes_2026Sep25.jsonl"
SIMPLE_FIELDS = ["source", "edge_type", "target"]
DETAILED_FIELDS = SIMPLE_FIELDS + ["evidence", "confidence"]
MARKDOWN_LINK = re.compile(r"(?P<image>!)?\[(?P<label>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+[^)]*)?\)")
STRONG_LABEL = re.compile(r"\b(github|source|source code|code|repository|implementation)\b", re.I)
RESERVED_OWNERS = {
    "about", "apps", "collections", "contact", "customer-stories", "enterprise",
    "features", "issues", "join", "login", "marketplace", "new", "notifications",
    "orgs", "organizations", "pricing", "pulls", "search", "security", "settings",
    "site", "sponsors", "topics", "trending", "users",
}
PRIORITY = {"readme_declared_link": 0, "readme_reference": 1, "badge_reference": 2}


def parse_args() -> argparse.Namespace:
    parser=argparse.ArgumentParser(description="Extract README GitHub links.")
    parser.add_argument("--input",type=Path,default=DEFAULT_INPUT)
    parser.add_argument("--output-dir",type=Path,default=SCRIPT_DIR)
    return parser.parse_args()


def accepted_repositories(text: str) -> set[str]:
    return {repo for repo in github_repositories(text) if repo.split("/",1)[0] not in RESERVED_OWNERS}


def candidates(markdown: str) -> dict[str, tuple[str,str]]:
    found={}
    markdown_repositories=set()
    for match in MARKDOWN_LINK.finditer(markdown):
        context = markdown[max(0, match.start() - 100):match.start()]
        confidence = "badge_reference" if match.group("image") else (
            "readme_declared_link"
            if STRONG_LABEL.search(match.group("label")) or STRONG_LABEL.search(context)
            else "readme_reference"
        )
        for repo in accepted_repositories(match.group("url")):
            markdown_repositories.add(repo)
            current=found.get(repo)
            if current is None or PRIORITY[confidence] < PRIORITY[current[1]]:
                found[repo]=(f"model_card_markdown:{match.group('label').strip() or 'unlabelled_link'}",confidence)
    # Bare URLs and URLs not captured by Markdown syntax.
    for repo in accepted_repositories(markdown) - markdown_repositories:
        current=found.get(repo)
        proposed=("model_card_markdown:embedded_url","readme_reference")
        if current is None or PRIORITY[proposed[1]] < PRIORITY[current[1]]:
            found[repo]=proposed
    return found


def main() -> int:
    args=parse_args(); input_path=args.input.expanduser().resolve(); out=args.output_dir.expanduser().resolve()
    if not input_path.is_file(): raise FileNotFoundError(input_path)
    out.mkdir(parents=True,exist_ok=True)
    paths={
        "csv":out/"model_github_edges_readme.csv",
        "jsonl":out/"model_github_edges_readme.jsonl",
        "dcsv":out/"model_github_edges_readme_detailed.csv",
        "djsonl":out/"model_github_edges_readme_detailed.jsonl",
    }
    existing=[p for p in paths.values() if p.exists()]
    if existing: raise FileExistsError("Refusing to overwrite:\n"+"\n".join(map(str,existing)))
    edges={}; records=ok=0; statuses={}
    with input_path.open(encoding="utf-8") as stream:
        for number,line in enumerate(stream,1):
            try: record=json.loads(line)
            except json.JSONDecodeError as exc: raise ValueError(f"Invalid JSON line {number}: {exc}") from exc
            records+=1; status=record.get("status"); statuses[status]=statuses.get(status,0)+1
            if status!="ok" or not isinstance(record.get("readme"),str): continue
            ok+=1; model=record.get("modelId")
            if not isinstance(model,str) or not model.strip(): continue
            for repo,detail in candidates(record["readme"]).items():
                key=(f"model::{model.strip()}","links_to_github",f"github::{repo}")
                current=edges.get(key)
                if current is None or PRIORITY[detail[1]] < PRIORITY[current[1]]: edges[key]=detail
    with (paths["csv"].open("x",newline="",encoding="utf-8") as cf,
          paths["jsonl"].open("x",encoding="utf-8") as jf,
          paths["dcsv"].open("x",newline="",encoding="utf-8") as df,
          paths["djsonl"].open("x",encoding="utf-8") as dj):
        cw=csv.DictWriter(cf,fieldnames=SIMPLE_FIELDS); dw=csv.DictWriter(df,fieldnames=DETAILED_FIELDS)
        cw.writeheader(); dw.writeheader()
        for key in sorted(edges):
            source,etype,target=key; evidence,confidence=edges[key]
            simple={"source":source,"edge_type":etype,"target":target}; detailed={**simple,"evidence":evidence,"confidence":confidence}
            cw.writerow(simple); dw.writerow(detailed)
            jf.write(json.dumps(simple,separators=(",",":"))+"\n"); dj.write(json.dumps(detailed,separators=(",",":"))+"\n")
    print(f"Records: {records:,}\nReadable READMEs: {ok:,}\nStatuses: {statuses}\nREADME GitHub edges: {len(edges):,}")
    return 0


if __name__=="__main__": raise SystemExit(main())
