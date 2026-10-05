# Hugging Face metadata extraction — October 02, 2026

This repository preserves the final HuggingGraph v3 analysis archive based on
the October 2, 2026 snapshot. 

The Git tree contains the complete source set, documentation, environment
record, graph counts, archive inventory, and checksums. The full 31 GB archive
is distributed as split, compressed assets in the GitHub Release because it is
too large for ordinary Git objects and Git LFS limits.

## Release contents

The reconstructed archive contains:

- 31 Python scripts, including the 17 authoritative v3 builders and validators;
- the released `HuggingGraph_v3.dot` graph;
- 17 CSV and 17 JSONL subgraphs;
- complete collected model, Dataset, and Space cards;
- parsed model, Dataset, and Space metadata;
- extraction state databases and logs;
- detailed, inferred, unresolved, and externally validated evidence outputs;
- 7,775,872 graph edges and 3,137,207 globally unique typed nodes.

See [`SUBGRAPH_COUNTS.csv`](SUBGRAPH_COUNTS.csv) and
[`VALIDATION_SUMMARY.json`](VALIDATION_SUMMARY.json) for the final counts.

## Download and reconstruct

Download every asset whose name starts with:

```text
hugginggraph_v3_2026oct02_reproducibility.tar.zst.part-
```

Also download `RELEASE_ASSETS.sha256`, then place all files in one directory.
Verify and reconstruct with:

```bash
sha256sum -c RELEASE_ASSETS.sha256
./scripts/reconstruct_release.sh /path/to/downloaded/assets /path/to/output
```

The reconstruction script concatenates the numbered parts, decompresses the
stream, extracts the archive, and verifies every extracted file against the
archive's internal `MANIFEST.sha256`.

Required command-line programs are `bash`, `sha256sum`, `zstd`, and `tar`.

## Repository layout

- `source/`: curated v3 code plus acquisition, baseline, and reference scripts.
- `documentation/`: the HuggingGraph README and release-package documentation.
- `environment/`: direct dependencies and archive-creation environment.
- `archive_metadata/FILE_INVENTORY.csv`: path and size of archived files.
- `archive_metadata/ARCHIVE_MANIFEST.sha256`: checksums for extracted files.
- `scripts/reconstruct_release.sh`: verified reconstruction workflow.

## HuggingGraph v3 source pipeline

The authoritative October 2, 2026 graph-construction code is in the
[`source/`](source/) directory. The release uses 17 selected Python scripts
plus [`source/requirements.txt`](source/requirements.txt). Install its direct
Python dependencies with:

```bash
python -m pip install -r source/requirements.txt
```

Python 3.10 or later is recommended.

### Relationship generators

| # | Relationship | Primary generator(s) |
|---:|---|---|
| 1 | Model to model | [`model_lineage_edges.py`](source/model_lineage_edges.py) |
| 2 | Dataset to model | [`dataset_model_edges.py`](source/dataset_model_edges.py) |
| 3 | Dataset to dataset candidate union | [`extract_dataset_dataset_extended.py`](source/extract_dataset_dataset_extended.py) |
| 4 | Model to library | [`model_library_edges.py`](source/model_library_edges.py), [`build_model_readme_attribute_subgraphs.py`](source/build_model_readme_attribute_subgraphs.py) |
| 5 | Dataset to library | [`build_latest_dataset_attributes.py`](source/build_latest_dataset_attributes.py) |
| 6 | Model to license | [`model_license_task_github_edges.py`](source/model_license_task_github_edges.py), [`build_model_readme_attribute_subgraphs.py`](source/build_model_readme_attribute_subgraphs.py) |
| 7 | Dataset to license | [`build_latest_dataset_attributes.py`](source/build_latest_dataset_attributes.py) |
| 8 | Model to task | [`model_license_task_github_edges.py`](source/model_license_task_github_edges.py), [`build_model_readme_attribute_subgraphs.py`](source/build_model_readme_attribute_subgraphs.py) |
| 9 | Dataset to task | [`build_latest_dataset_attributes.py`](source/build_latest_dataset_attributes.py) |
| 10 | Model to GitHub repository | [`extract_model_github_edges_streaming.py`](source/extract_model_github_edges_streaming.py) |
| 11 | Dataset to GitHub repository | [`extract_dataset_github_edges_streaming.py`](source/extract_dataset_github_edges_streaming.py) |
| 12 | Model to Space | [`build_space_subgraphs.py`](source/build_space_subgraphs.py) |
| 13 | Dataset to Space | [`build_space_subgraphs.py`](source/build_space_subgraphs.py) |
| 14 | Space to GitHub repository | [`extract_space_github_edges_streaming_full.py`](source/extract_space_github_edges_streaming_full.py) |
| 15 | Space to license | [`build_space_license_task_agent_subgraphs.py`](source/build_space_license_task_agent_subgraphs.py) |
| 16 | Space to task | [`build_space_license_task_agent_subgraphs.py`](source/build_space_license_task_agent_subgraphs.py) |
| 17 | Space to agent framework | [`build_space_license_task_agent_subgraphs.py`](source/build_space_license_task_agent_subgraphs.py) |

### Shared preparation, validation, and assembly

- [`count_model_types.py`](source/count_model_types.py) classifies model
  derivation evidence used by the model-lineage builder.
- [`model_dataset_attribute_edges.py`](source/model_dataset_attribute_edges.py)
  provides shared model and Dataset attribute normalization.
- [`audit_dataset_subgraphs.py`](source/audit_dataset_subgraphs.py) audits the
  Dataset relationship families and reports coverage and consistency checks.
- [`prepare_hugginggraph_v3_edges.py`](source/prepare_hugginggraph_v3_edges.py)
  normalizes and count-checks the 17 numbered edge inputs.
- [`build_hugginggraph_v3.py`](source/build_hugginggraph_v3.py) validates the
  final edge and node totals and constructs `HuggingGraph_v3.dot`.

The 17 scripts named above are the curated v3 source set. Large metadata
snapshots, final CSV/JSONL edge projections, and intermediate analysis outputs
are intentionally not committed to `source/`.

## HuggingGraph v3 scale

HuggingGraph v3 contains 17 logical relationship families. This refreshed v3
is based on the October 2, 2026 analysis. It includes the extended
Dataset-to-Dataset candidate union, refreshed Dataset attributes, Space
relationships, and one normalized GitHub repository identity across model,
Dataset, and Space sources.

| Relationship | Unique edges | Unique nodes within subgraph |
|---|---:|---:|
| Model to model | 966,035 | 978,868 |
| Dataset to model | 362,064 | 287,539 |
| Dataset to dataset | 12,541 | 15,172 |
| Model to library | 1,311,386 | 1,214,466 |
| Dataset to library | 16,864 | 16,467 |
| Model to license | 1,090,845 | 1,092,560 |
| Dataset to license | 331,317 | 332,328 |
| Model to task | 577,077 | 541,491 |
| Dataset to task | 317,412 | 211,454 |
| Model to GitHub repository | 962,855 | 729,920 |
| Dataset to GitHub repository | 188,888 | 196,768 |
| Model to Space | 941,121 | 487,287 |
| Dataset to Space | 83,061 | 85,762 |
| Space to GitHub repository | 113,755 | 90,895 |
| Space to license | 420,369 | 420,557 |
| Space to task | 43,223 | 42,229 |
| Space to agent framework | 37,059 | 37,016 |
| **Unified HuggingGraph v3** | **7,775,872** | **See the node-type breakdown below** |

The node total is the global union of all endpoints. Relationship-specific
node counts must not be added because the same node can occur in several
subgraphs.

| Node type | Unique nodes in v3 |
|---|---:|
| Model | 1,888,591 |
| Dataset | 431,324 |
| Space | 712,728 |
| Library | 2,148 |
| License | 4,888 |
| Task | 839 |
| GitHub repository | 96,678 |
| Agent framework | 11 |
| **Total** | **3,137,207** |

The Dataset-to-Dataset value is an extended candidate union rather than the
5,217-edge conservative metadata-only baseline. Its 12,541 unique Dataset
pairs combine the official metadata baseline with high-confidence README
lineage evidence and externally revalidated Dataset references. Because the
aggregate DOT stores one edge per unique pair, these edges use
`dataset_relationship_candidate`; evidence-specific relationship types remain
available in the analysis outputs used to construct the release.

The verified Space population contains 1,481,220 repositories: 413,102 have
at least one model or dataset relationship and 1,068,118 do not. Three Space
IDs present in the card snapshot were unavailable during relationship
reconciliation and are excluded from that verified population. Among connected
Space nodes, 59,747 link to 31,148 normalized GitHub repositories through
113,755 unique Space-to-GitHub edges.

## Crawled populations

| Population outcome | Models | Datasets |
|---|---:|---:|
| Readable README/card | 1,975,515 | 698,202 |
| No readable README | 1,005,324 | 286,579 |
| Restricted repository | 48,538 | 38,353 |
| **Total processed** | **3,029,377** | **1,023,134** |

## Node identifiers

Versions 1 through 3 prefix Hugging Face and categorical node IDs with their
entity type. Version 3 uses seven typed prefixes plus canonical GitHub repository URLs:

```text
model::owner/repository
dataset::owner/repository
space::owner/repository
library::library-name
license::license-identifier
task::task-identifier
agent::framework-name
https://github.com/owner/repository
```

Typed IDs prevent a model repository and a dataset repository with the same
`owner/repository` string from collapsing into one graph node. To recover the
underlying identifier, split once on `::` and use the second component.
GitHub repository nodes are instead stored as normalized HTTPS repository URLs
so that they can be followed directly.

## Edge schema

Lineage edges are directed from an upstream artifact to a downstream artifact.
Attribute edges are directed from a model, dataset, or Space to the relevant
artifact or category node.

| Canonical `edge_type` | Source | Target | Meaning |
|---|---|---|---|
| `finetune` | model | model | Target is fine-tuned from source. |
| `adapter` | model | model | Target is an adapter derived from source. |
| `quantized` | model | model | Target is a quantized form of source. |
| `merged` | model | model | Target is a merge containing source. |
| `trained_on` | dataset | model | Source dataset is declared as training data for target model. |
| `derived_from` | dataset | dataset | Target dataset is derived from source dataset. |
| `dataset_relationship_candidate` | dataset | dataset | Candidate Dataset relationship from the October 2 expanded union. |
| `uses_library` | model or dataset | library | Source declares or is associated with the target library. |
| `has_license` | model, dataset, or Space | license | Source declares or is associated with the target license. |
| `performs_task` | model | task | Model performs or is associated with the target task. |
| `supports_task` | dataset or Space | task | Source supports or is associated with the target task. |
| `links_to_github` | model, dataset, or Space | GitHub repository | Source metadata contains a link to the target repository. |
| `used_by_space` | model or dataset | Space | A Space declares use of the source artifact. |
| `uses_agent_framework` | Space | agent framework | A Space declares or is classified with the target framework. |

Each edge carries two relationship attributes:

```dot
"model::parent" -> "model::child"
    [label="finetune", edge_type="finetune"];
```

`edge_type` is the canonical attribute. 

## Integrity

The source archive was validated before publication:

- all archive checksums passed;
- all 31 Python scripts parsed successfully;
- all 17 CSV and 17 JSONL subgraphs were present;
- the DOT graph matched the released SHA-256 digest;
- all core raw snapshots matched their source files byte-for-byte.

## Data-safety notice

The raw snapshots contain untrusted third-party text collected from public
Hugging Face model, Dataset, and Space cards. Do not execute code snippets,
commands, URLs, or credential-like strings found inside those snapshots. See
[`THIRD_PARTY_DATA_NOTICE.md`](THIRD_PARTY_DATA_NOTICE.md).

## Citation

If you use this graph or its figures, please cite the paper:

```bibtex
@inproceedings{rahman2025hugginggraph,
  title={Hugginggraph: Understanding the supply chain of llm ecosystem},
  author={Rahman, Mohammad Shahedur and Gao, Peng and Ji, Yuede},
  booktitle={Proceedings of the 34th ACM International Conference on Information and Knowledge Management},
  pages={5997--6005},
  year={2025}
}
```
