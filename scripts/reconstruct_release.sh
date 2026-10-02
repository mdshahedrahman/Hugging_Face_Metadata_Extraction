#!/usr/bin/env bash
set -euo pipefail

asset_dir=${1:-.}
output_dir=${2:-.}
prefix="hugginggraph_v3_2026oct02_reproducibility.tar.zst.part-"

if ! command -v zstd >/dev/null 2>&1; then
    echo "zstd is required but was not found" >&2
    exit 1
fi

if ! compgen -G "${asset_dir}/${prefix}*" >/dev/null; then
    echo "No release parts found in ${asset_dir}" >&2
    exit 1
fi

mkdir -p -- "${output_dir}"
cat "${asset_dir}"/"${prefix}"* \
    | zstd --decompress --stdout \
    | tar -xf - -C "${output_dir}"

archive_dir="${output_dir}/hugginggraph_v3_2026oct02_reproducibility"
if [[ ! -f "${archive_dir}/MANIFEST.sha256" ]]; then
    echo "Archive manifest not found after extraction" >&2
    exit 1
fi

(
    cd "${archive_dir}"
    sha256sum -c MANIFEST.sha256
)

echo "Archive reconstructed and verified: ${archive_dir}"
