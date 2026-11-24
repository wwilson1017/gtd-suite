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
# A Springform install's connect: start a code (one of its 5 an hour from this address), poll it once.
started=$(curl --disable --silent --show-error --connect-timeout 10 --max-time 30 --request POST \
  --header 'Content-Type: application/json' --data '{"client":"springform"}' "$base/api/connect" 2>/dev/null)
device=$(printf '%s' "$started" | grep -o '"device_token":"[A-Za-z0-9]*"' | cut -d'"' -f4)
if [[ -n "$device" && "$started" == *'&client=springform"'* ]]; then
  printf 'PASS POST %s/api/connect (springform): a code\n' "$base"
  polled=$(curl --disable --silent --show-error --connect-timeout 10 --max-time 30 --request POST \
    --header 'Content-Type: application/json' --data "{\"device_token\":\"$device\"}" "$base/api/connect/poll" 2>/dev/null)
  if [[ "$polled" == '{"status":"pending"}' ]]; then
    printf 'PASS POST %s/api/connect/poll: pending\n' "$base"
  else
    printf 'FAIL POST %s/api/connect/poll: expected {"status":"pending"}\n' "$base"
    failed=1
  fi
else
  printf 'FAIL POST %s/api/connect (springform): expected a code with a Springform approve link\n' "$base"
  failed=1
fi
exit "$failed"
