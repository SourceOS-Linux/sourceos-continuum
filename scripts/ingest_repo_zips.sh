#!/usr/bin/env bash
set -euo pipefail
# Usage: ./ingest_repo_zips.sh /path/to/zips outdir
IN=${1:?zipdir}
OUT=${2:-third_party}
mkdir -p "$OUT"
shopt -s nullglob
for z in "$IN"/*.zip; do
  name="$(basename "$z" .zip)"
  echo "[+] extracting $z -> $OUT/$name"
  mkdir -p "$OUT/$name"
  unzip -q "$z" -d "$OUT/$name"
done
echo "Done. Consider running scripts/triage_repos.py on $OUT."
