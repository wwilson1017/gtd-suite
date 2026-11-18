#!/usr/bin/env bash
# Run the CI checks locally.
# Agents run this before opening a PR.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

uv run --locked ruff check backend scripts
uv run --locked ruff format --check backend scripts
uv run --locked pyright
if [[ -d /dev/shm ]]; then
  TMPDIR=${TMPDIR:-/dev/shm} uv run --locked pytest backend/tests
else
  uv run --locked pytest backend/tests
fi
cd frontend
npm run lint
npm run format:check
npm test
npm run build -- --outDir "$(mktemp -d)"
