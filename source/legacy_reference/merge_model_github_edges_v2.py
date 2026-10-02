#!/usr/bin/env python3
"""Merge metadata- and README-derived model-GitHub evidence.

Created: 2026-09-25
Version: v2026.09.25-01
Purpose: Produce a versioned, deduplicated model-GitHub subgraph without
         overwriting the original metadata-only result.
"""

from __future__ import annotations

import argparse,csv,json
from pathlib import Path

SCRIPT_DIR=Path(__file__).resolve().parent
FIELDS=["source","edge_type","target"]
DETAIL=FIELDS+["evidence","confidence"]

def parse_args():
 p=argparse.ArgumentParser(); p.add_argument("--metadata",type=Path,default=SCRIPT_DIR/"model_github_edges_detailed.csv"); p.add_argument("--readme",type=Path,default=SCRIPT_DIR/"model_github_edges_readme_detailed.csv"); p.add_argument("--output-dir",type=Path,default=SCRIPT_DIR); return p.parse_args()

def main():
 a=parse_args(); inputs=[a.metadata.resolve(),a.readme.resolve()]; out=a.output_dir.resolve(); out.mkdir(parents=True,exist_ok=True)
 for p in inputs:
  if not p.is_file(): raise FileNotFoundError(p)
 paths=[out/"model_github_edges_v2.csv",out/"model_github_edges_v2.jsonl",out/"model_github_edges_v2_detailed.csv",out/"model_github_edges_v2_detailed.jsonl"]
 existing=[p for p in paths if p.exists()]
 if existing: raise FileExistsError("Refusing to overwrite:\n"+"\n".join(map(str,existing)))
 evidence={}
 for path in inputs:
  with path.open(newline="",encoding="utf-8") as f:
   for r in csv.DictReader(f): evidence.setdefault((r["source"],r["edge_type"],r["target"]),set()).add((r["evidence"],r["confidence"]))
 with (paths[0].open("x",newline="",encoding="utf-8") as cf,paths[1].open("x",encoding="utf-8") as jf,paths[2].open("x",newline="",encoding="utf-8") as df,paths[3].open("x",encoding="utf-8") as dj):
  cw=csv.DictWriter(cf,fieldnames=FIELDS); dw=csv.DictWriter(df,fieldnames=DETAIL); cw.writeheader(); dw.writeheader()
  corroborated=0
  for key in sorted(evidence):
   items=sorted(evidence[key]); sources={"readme" if x[1].startswith("readme_") or x[1]=="badge_reference" else "metadata" for x in items}
   confidence="corroborated" if len(sources)>1 else items[0][1]
   corroborated += confidence=="corroborated"
   simple=dict(zip(FIELDS,key)); detailed={**simple,"evidence":";".join(x[0] for x in items),"confidence":confidence}
   cw.writerow(simple); dw.writerow(detailed); jf.write(json.dumps(simple,separators=(",",":"))+"\n"); dj.write(json.dumps(detailed,separators=(",",":"))+"\n")
 print(f"Merged edges: {len(evidence):,}\nCorroborated edges: {corroborated:,}")
 return 0

if __name__=="__main__": raise SystemExit(main())
