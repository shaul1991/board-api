#!/usr/bin/env bash
# Board API smoke test: stories 1-5, 404 read/delete, persistence across restart.
# Real HTTP via curl against uvicorn on 127.0.0.1:8000 (port must be free).
# Prereqs: curl, jq, app deps installed (uses .venv/bin/python if present).
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -x .venv/bin/python ]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python3"
fi

BASE="http://127.0.0.1:8000"
RESP="$(mktemp)"
SERVER_LOG="$(mktemp)"
SERVER_PID=""
STATUS=""
BODY=""

cleanup() {
  if [ -n "${SERVER_PID}" ] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  rm -f "${RESP}" "${SERVER_LOG}"
}
trap cleanup EXIT

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
pass() { printf 'PASS: %s\n' "$*"; }

# req METHOD PATH [JSON_BODY] -> sets STATUS (http code) and BODY (response body)
req() {
  local method="$1" path="$2" data="${3:-}"
  local args=(-s -o "${RESP}" -w '%{http_code}' -X "${method}")
  if [ -n "${data}" ]; then
    args+=(-H 'Content-Type: application/json' --data "${data}")
  fi
  STATUS="$(curl "${args[@]}" "${BASE}${path}")"
  BODY="$(cat "${RESP}")"
}

start_server() {
  printf 'starting uvicorn (app.main:app, port 8000)...\n'
  "${PYTHON}" -m uvicorn app.main:app --port 8000 >"${SERVER_LOG}" 2>&1 &
  SERVER_PID=$!
  for _ in $(seq 1 50); do
    if curl -sf "${BASE}/docs" >/dev/null 2>&1; then
      pass "server ready (pid ${SERVER_PID}, GET /docs -> 200)"
      return 0
    fi
    sleep 0.2
  done
  cat "${SERVER_LOG}" >&2
  fail "server did not become ready"
}

stop_server() {
  if [ -n "${SERVER_PID}" ] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  SERVER_PID=""
}

# ---- Story 1: create --------------------------------------------------------
start_server

req POST /posts '{"title":"smoke title","body":"smoke body"}'
[ "${STATUS}" = "201" ] || fail "story 1 create: expected 201, got ${STATUS} body=${BODY}"
POST_ID="$(printf '%s' "${BODY}" | jq -r '.id')"
[ -n "${POST_ID}" ] && [ "${POST_ID}" != "null" ] || fail "story 1 create: missing id in ${BODY}"
printf '%s' "${BODY}" | jq -e '.title == "smoke title" and .body == "smoke body" and .created_at == .updated_at and .created_at != ""' >/dev/null \
  || fail "story 1 create: unexpected body ${BODY}"
pass "story 1 create -> 201 (id=${POST_ID}, title/body echoed, created_at==updated_at)"

# ---- Persistence: restart, then story 2 read --------------------------------
stop_server
start_server

req GET "/posts/${POST_ID}"
[ "${STATUS}" = "200" ] || fail "story 2 read: expected 200, got ${STATUS} body=${BODY}"
printf '%s' "${BODY}" | jq -e --argjson id "${POST_ID}" \
  '.id == $id and .title == "smoke title" and .body == "smoke body" and .created_at == .updated_at' >/dev/null \
  || fail "story 2 read: unexpected body ${BODY}"
pass "story 2 read -> 200 after server restart (persistence ok, id=${POST_ID})"

# ---- Story 3: list with paging ----------------------------------------------
req POST /posts '{"title":"page post 1","body":"p1 body"}'
[ "${STATUS}" = "201" ] || fail "story 3 setup: expected 201, got ${STATUS} body=${BODY}"
ID1="$(printf '%s' "${BODY}" | jq -r '.id')"
req POST /posts '{"title":"page post 2","body":"p2 body"}'
[ "${STATUS}" = "201" ] || fail "story 3 setup: expected 201, got ${STATUS} body=${BODY}"
ID2="$(printf '%s' "${BODY}" | jq -r '.id')"

req GET "/posts?page=1&size=2"
[ "${STATUS}" = "200" ] || fail "story 3 list: expected 200, got ${STATUS} body=${BODY}"
printf '%s' "${BODY}" | jq -e --argjson id1 "${ID1}" --argjson id2 "${ID2}" \
  '(.total >= 2) and .page == 1 and .size == 2 and (.items | length) == 2 and .items[0].id == $id2 and .items[1].id == $id1' >/dev/null \
  || fail "story 3 list: unexpected body ${BODY}"
pass "story 3 list -> 200 (total>=2, page=1 size=2, newest first: [${ID2}, ${ID1}])"

req GET "/posts?page=2&size=2"
[ "${STATUS}" = "200" ] || fail "story 3 page 2: expected 200, got ${STATUS} body=${BODY}"
printf '%s' "${BODY}" | jq -e --argjson id1 "${ID1}" --argjson id2 "${ID2}" \
  '.page == 2 and .size == 2 and ([.items[].id] | index($id1) == null) and ([.items[].id] | index($id2) == null)' >/dev/null \
  || fail "story 3 page 2: unexpected body ${BODY}"
pass "story 3 page 2 -> 200 (ids ${ID1}/${ID2} not repeated)"

# ---- Story 4: update ---------------------------------------------------------
req GET "/posts/${ID1}"
[ "${STATUS}" = "200" ] || fail "story 4 setup: expected 200, got ${STATUS}"
OLD_UPDATED="$(printf '%s' "${BODY}" | jq -r '.updated_at')"
OLD_CREATED="$(printf '%s' "${BODY}" | jq -r '.created_at')"

req PUT "/posts/${ID1}" '{"title":"updated title","body":"updated body"}'
[ "${STATUS}" = "200" ] || fail "story 4 update: expected 200, got ${STATUS} body=${BODY}"
printf '%s' "${BODY}" | jq -e --argjson id1 "${ID1}" --arg old "${OLD_UPDATED}" --arg created "${OLD_CREATED}" \
  '.id == $id1 and .title == "updated title" and .body == "updated body" and .updated_at != $old and .created_at == $created' >/dev/null \
  || fail "story 4 update: unexpected body ${BODY}"
pass "story 4 update -> 200 (title/body replaced, updated_at advanced, created_at kept)"

req GET "/posts/${ID1}"
[ "${STATUS}" = "200" ] || fail "story 4 re-read: expected 200, got ${STATUS}"
printf '%s' "${BODY}" | jq -e '.title == "updated title" and .body == "updated body"' >/dev/null \
  || fail "story 4 re-read: unexpected body ${BODY}"
pass "story 4 re-read -> 200 (update persisted)"

# ---- Story 5: delete ---------------------------------------------------------
req DELETE "/posts/${ID2}"
[ "${STATUS}" = "204" ] || fail "story 5 delete: expected 204, got ${STATUS} body=${BODY}"
[ -z "${BODY}" ] || fail "story 5 delete: expected empty body, got ${BODY}"
pass "story 5 delete -> 204 empty body (id=${ID2})"

req GET "/posts/${ID2}"
[ "${STATUS}" = "404" ] || fail "story 5 read-after-delete: expected 404, got ${STATUS}"
[ "${BODY}" = '{"detail":"post not found"}' ] || fail "story 5 read-after-delete: unexpected body ${BODY}"
pass "story 5 read after delete -> 404 {\"detail\":\"post not found\"}"

# ---- 404s --------------------------------------------------------------------
req GET /posts/999999999
[ "${STATUS}" = "404" ] || fail "404 read: expected 404, got ${STATUS}"
[ "${BODY}" = '{"detail":"post not found"}' ] || fail "404 read: unexpected body ${BODY}"
pass "404 read (GET /posts/999999999) -> 404 with detail"

req DELETE /posts/999999999
[ "${STATUS}" = "404" ] || fail "404 delete: expected 404, got ${STATUS}"
[ "${BODY}" = '{"detail":"post not found"}' ] || fail "404 delete: unexpected body ${BODY}"
pass "404 delete (DELETE /posts/999999999) -> 404 with detail"

printf '\nALL SMOKE CHECKS PASSED\n'
