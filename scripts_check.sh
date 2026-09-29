#!/bin/sh
# House checks before a commit: no em or en dashes in prose, no key material anywhere.
set -e
cd "$(dirname "$0")"
if grep -rn $'\xe2\x80\x93\|\xe2\x80\x94' README.md CHANGELOG.md docs src tests examples pyproject.toml 2>/dev/null; then
  echo "dash found"; exit 1
fi
if git grep -n "apikey_" -- . ':!scripts_check.sh' >/dev/null 2>&1 || grep -rn "apikey_" src tests examples docs README.md 2>/dev/null; then
  echo "key material found"; exit 1
fi
echo "house checks ok"
