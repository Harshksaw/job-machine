#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$ROOT/backups/$(date +%Y%m%d-%H%M%S)}"

mkdir -p "$DEST"
cp -a "$ROOT/data" "$DEST/"
if [[ -d "$ROOT/output" ]]; then
  cp -a "$ROOT/output" "$DEST/"
fi

echo "Backed up job-machine data to $DEST"
