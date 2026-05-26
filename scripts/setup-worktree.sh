#!/usr/bin/env bash
set -euo pipefail

# Copy env file from main worktree if present
if [ -f ../main/.env.local ]; then
  cp ../main/.env.local ./.env.local
fi
