#!/usr/bin/env bash
# Scan added lines in a diff range for things that must never reach this public repo.
# Usage: scripts/leakcheck.sh [RANGE]   (default: origin/main...HEAD, or the whole tree if no origin/main)
# Exit 1 on any hit. This file and AGENTS.md are excluded because they name the patterns.
set -euo pipefail

EMPTY_TREE=4b825dc642cb6eb9a060e54bf8d69288fbee4904

range="${1:-}"
if [ -z "$range" ]; then
  if git rev-parse --verify -q origin/main >/dev/null; then
    range="origin/main...HEAD"
  else
    range="$EMPTY_TREE HEAD"
  fi
fi

pattern='accountName|[a-z0-9._-]+@[a-z0-9-]+\.(com|net|org|io)\b|C:[\\/]+Users[\\/]+|/c/Users/|%USERPROFILE%|WTF[\\/]+Account[\\/]+[0-9]|\b[A-Za-z][A-Za-z0-9]{2,11}#[0-9]{4,5}\b|thread[_-]?(id)?[_-]?[0-9a-f]{8,}|\b(token|secret|password|api[_-]?key)\s*[:=]'

# shellcheck disable=SC2086
hits=$(git diff --no-color -U0 $range -- . ':!scripts/leakcheck.sh' ':!AGENTS.md' \
  | grep -E '^\+[^+]' \
  | grep -inE "$pattern" || true)

# Obviously synthetic fixture values are allowed.
hits=$(printf '%s\n' "$hits" | grep -vE 'Example#0000|000000000|noreply@(anthropic\.com|github\.com|users\.noreply\.github\.com)' | sed '/^$/d' || true)

if [ -n "$hits" ]; then
  echo "leakcheck: possible sensitive content in $range:" >&2
  printf '%s\n' "$hits" >&2
  echo "Review each hit. If all are false positives: git push --no-verify" >&2
  exit 1
fi
echo "leakcheck: clean ($range)"
