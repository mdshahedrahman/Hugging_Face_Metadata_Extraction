# HuggingGraph v3 — October 2, 2026 reproducibility package

Created: 2026-10-02
Version: v2026.10.02-04

This directory keeps the source code and final edge projections for the
October 2, 2026 HuggingGraph v3 release in one place.

## Contents

- `source/`: 17 selected Python scripts and `requirements.txt`.
- `edges/csv/`: the 17 final graph-ready CSV subgraphs.
- `edges/jsonl/`: exact JSONL projections of the 17 CSV files.
- `SUBGRAPH_COUNTS.csv`: relationship edge and node counts.
- `MANIFEST.sha256`: SHA-256 digest for every packaged file except the
  manifest itself.

Each edge file has the schema `source,edge_type,target`. JSONL files contain
the same three fields and the same rows as their corresponding CSV files.

## Relationship-to-script mapping

| # | Relationship | Primary generator |
|---:|---|---|
| 1 | Model–Model | `model_lineage_edges.py` |
| 2 | Dataset–Model | `dataset_model_edges.py` |
| 3 | Dataset–Dataset candidate union | `extract_dataset_dataset_extended.py` |
| 4 | Model–Library | `model_library_edges.py`, `build_model_readme_attribute_subgraphs.py` |
| 5 | Dataset–Library | `build_latest_dataset_attributes.py` |
| 6 | Model–License | `model_license_task_github_edges.py`, `build_model_readme_attribute_subgraphs.py` |
| 7 | Dataset–License | `build_latest_dataset_attributes.py` |
| 8 | Model–Task | `model_license_task_github_edges.py`, `build_model_readme_attribute_subgraphs.py` |
| 9 | Dataset–Task | `build_latest_dataset_attributes.py` |
| 10 | Model–GitHub | `extract_model_github_edges_streaming.py` |
| 11 | Dataset–GitHub | `extract_dataset_github_edges_streaming.py` |
| 12 | Model–Space | `build_space_subgraphs.py` |
| 13 | Dataset–Space | `build_space_subgraphs.py` |
| 14 | Space–GitHub | `extract_space_github_edges_streaming_full.py` |
| 15 | Space–License | `build_space_license_task_agent_subgraphs.py` |
| 16 | Space–Task | `build_space_license_task_agent_subgraphs.py` |
| 17 | Space–Agent | `build_space_license_task_agent_subgraphs.py` |

Shared normalization is provided by `model_dataset_attribute_edges.py` and
`count_model_types.py`. `audit_dataset_subgraphs.py` validates the Dataset
families. `prepare_hugginggraph_v3_edges.py` prepares the numbered inputs, and
`build_hugginggraph_v3.py` validates their counts and constructs the DOT file.

## Release totals

- Relationship edges: 7,775,872
- Global typed nodes: 3,137,207
- Dataset–Dataset candidate pairs: 12,541
- Dataset–Dataset participating nodes: 15,172

The Dataset–Dataset layer is an extended candidate union. The conservative
metadata-only baseline remains 5,217 edges and 5,974 nodes.
