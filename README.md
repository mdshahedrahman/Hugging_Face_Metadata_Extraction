# Hugging Face metadata extraction workings — October 2026

This repository preserves the final HuggingGraph v3 analysis archive based on
the October 2, 2026 snapshot. Only one archived version is published:
`v2026.10.02-07`.

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
