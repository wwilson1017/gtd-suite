#!/usr/bin/env bash
# Check the public endpoints after a deploy, without credentials.
set -uo pipefail
base=${1:-https://todogtd.com}
base=${base%/}
failed=0

check_status() {
  local method=$1 url=$2 expected=$3 actual
  actual=$(curl --disable --silent --show-error --connect-timeout 10 --max-time 30 \
    --request "$method" --output /dev/null --write-out '%{http_code}' "$url" 2>/dev/null)
  if [[ $? == 0 && "$actual" == "$expected" ]]; then
    printf 'PASS %s %s: %s\n' "$method" "$url" "$actual"
  else
    printf 'FAIL %s %s: expected %s, got %s\n' "$method" "$url" "$expected" "$actual"
    failed=1
  fi
}

# Append a sentinel so command substitution preserves any trailing body newlines.
health=$(curl --disable --silent --show-error --connect-timeout 10 --max-time 30 \
  --write-out '|%{http_code}' "$base/healthz" 2>/dev/null)
if [[ $? == 0 && "$health" == '{"ok":true}|200' ]]; then
  printf 'PASS GET %s/healthz: 200 {"ok":true}\n' "$base"
else
  printf 'FAIL GET %s/healthz: expected 200 and exact {"ok":true} body\n' "$base"
  failed=1
fi
check_status GET "$base/api/config" 200
for host in todogtd.com commonbrain.ai simplesites.app; do
  check_status GET "https://$host/" 200
done
# Notes and Projects live at the main address; their old hosts send a signed-out visitor there.
for app in notes projects; do
  check_status GET "https://todogtd.com/$app" 200
  check_status GET "https://${app}gtd.com/" 303
done
check_status GET https://ss.page/ 302
check_status POST "$base/mcp" 401
exit "$failed"
