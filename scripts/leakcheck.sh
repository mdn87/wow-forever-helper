#!/usr/bin/env bash
# Scan lines ADDED in a commit range for content that must never reach this public repo.
#
# Usage: scripts/leakcheck.sh                 default: origin/main...HEAD, or the whole tree if no origin/main
#        scripts/leakcheck.sh RANGE           any git diff range, e.g. origin/main...HEAD
#        scripts/leakcheck.sh BASE HEAD       two revisions (what .githooks/pre-push passes)
#
# Prints "file:line: content" for every hit and exits 1. Exits 0 when clean.
# This script and AGENTS.md are excluded from the scan because they name the patterns.
set -euo pipefail

EMPTY_TREE=4b825dc642cb6eb9a060e54bf8d69288fbee4904

case $# in
  0)
    if git rev-parse --verify -q origin/main >/dev/null; then
      set -- origin/main...HEAD
    else
      set -- "$EMPTY_TREE" HEAD
    fi
    ;;
  1|2) ;;
  *) echo "usage: $0 [RANGE | BASE HEAD]" >&2; exit 2 ;;
esac
label="$*"

# Matched case-insensitively against each added line. Every alternative is anchored to a
# *value*, not a bare keyword, so prose that names a setting (for example "SET accountName")
# does not trip the check while a pasted Config.wtf line does.
patterns=(
  'accountname\s*["=:]'                                              # SET accountName "..." from a real Config.wtf
  '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}'                            # email addresses, any TLD or subdomain
  'c:[\\/]+users[\\/]+|/c/users/|/home/[a-z]|(^|[^a-z0-9])/users/[a-z]'   # local paths, incl. JSON-escaped backslashes
  'wtf[\\/]+account[\\/]+[0-9]'                                      # real numeric account folder
  '\b[a-z][a-z0-9]{2,11}#[0-9]{4,5}\b'                               # BattleTag Name#1234
  'thread[_-]?id\W{0,4}[0-9a-f]{8}|thread[_-][0-9a-f]{8}'            # Codex thread ids, also as JSON "thread_id": "..."
  '\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b'  # UUIDs: session, request, and frame ids
  '\b(token|secret|password|passwd|api[_-]?key)["'"'"']?\s*[:=]\s*["'"'"'][^"'"'"']{4,}'  # a literal secret value
)
pattern=$(IFS='|'; echo "${patterns[*]}")

# Obviously synthetic values are allowed (see AGENTS.md "Fixtures and examples must be synthetic").
# They are blanked out of the line before matching, not used to skip the line, so a line that
# mixes a synthetic value with a real one is still caught.
allow='[Aa]ccount[Nn]ame "[^"]*@example\.(com|net|org)"|[Ee]xample#0000|000000000|[A-Za-z0-9._%+-]+@example\.(com|net|org)\b|noreply@(anthropic\.com|github\.com)|[A-Za-z0-9._-]+@users\.noreply\.github\.com|00000000-0000-0000-0000-000000000000'

# Turn the unified diff into "file:line: content" for added lines only, then filter.
added=$(git diff --no-color -U0 "$@" -- . ':!scripts/leakcheck.sh' ':!AGENTS.md' \
  | awk '
      /^\+\+\+ / { file = substr($0, 7); if (file == "dev/null") file = ""; next }
      /^--- /    { next }
      /^@@ /     { match($0, /\+[0-9]+/); line = substr($0, RSTART + 1, RLENGTH - 1) + 0; next }
      /^\+/      { if (file != "") print file ":" line ": " substr($0, 2); line++ }
    ')

hits=$(printf '%s\n' "$added" | sed -E "s/$allow/[synthetic]/g" | grep -iE "$pattern" || true)

if [ -n "$hits" ]; then
  echo "leakcheck: possible sensitive content in $label:" >&2
  printf '%s\n' "$hits" >&2
  echo "Review each hit. If every hit is a false positive: git push --no-verify" >&2
  exit 1
fi
echo "leakcheck: clean ($label)"
