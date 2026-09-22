#!/usr/bin/env bash
# List checkpoints; delete the ones whose repo is gone.
#   cleanup-checkpoints.sh          list
#   cleanup-checkpoints.sh --prune  delete the dead ones
set -euo pipefail

DIR="${CORTEX_CHECKPOINTS_DIR:-$HOME/.cortex/cortex-workflow/checkpoints}"
PRUNE="${1:-}"

for f in "$DIR"/*.md; do
  [[ -f "$f" ]] || { echo "no checkpoints"; exit 0; }
  ref=$(basename "$f" .md)
  repo=$(sed -n 's/^repo: "\(.*\)"$/\1/p' "$f" | head -1)

  if [[ -n "$repo" && ! -d "$repo" ]]; then
    if [[ "$PRUNE" == "--prune" ]]; then
      rm -f "$f"; echo "DELETED $ref  ($repo gone)"
    else
      echo "DEAD    $ref  ($repo gone)"
    fi
  else
    echo "keep    $ref  ${repo:-no repo recorded}"
  fi
done
