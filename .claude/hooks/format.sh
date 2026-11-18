#!/usr/bin/env bash
# Format files written or edited by Claude Code.
file=$(python3 -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))' 2>/dev/null) || exit 0
[[ "$file" = /* ]] || file="${CLAUDE_PROJECT_DIR:-$PWD}/$file"
[[ -f "$file" ]] || exit 0
file=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$file") || exit 0
# The checkout that holds the file: sessions often edit a worktree under .claude/worktrees/.
root=$(git -C "$(dirname "$file")" rev-parse --show-toplevel 2>/dev/null) || exit 0
[[ -f "$root/pyproject.toml" && -d "$root/frontend" ]] || exit 0  # todo-gtd checkouts only
case "$file" in
  "$root"/backend/*.py|"$root"/scripts/*.py)
    (cd "$root" && uv run --quiet ruff format "$file") >/dev/null 2>&1
    ;;
  "$root"/frontend/*)
    case "$file" in
      *.ts|*.tsx|*.js|*.jsx|*.css|*.json|*.html|*.md)
        (cd "$root/frontend" && npx --no-install prettier --write "$file") >/dev/null 2>&1
        ;;
    esac
    ;;
esac
exit 0
