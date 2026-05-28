#!/usr/bin/env bash
#
# asana-post-comment.sh — post a comment (story) to an Asana task
#
# Usage:
#   asana-post-comment.sh <task-gid> "<body>"
#
# Pass the comment body as-authored. The script inspects the body and
# routes it through the correct Asana API field automatically:
#
#   - Body contains HTML tags (<strong>, <em>, <ul>, <a>, etc.) → POSTed
#     as `html_text`. If the body is not already wrapped in
#     <body>...</body>, the script wraps it before sending.
#   - Body contains no HTML tags → POSTed as `text` (plain text). URLs
#     in the body are auto-linked by Asana.
#
# Callers do not need to choose a field. Authoring the content as plain
# text or as HTML is sufficient — the script handles the rest.
#
# Supported tags inside <body>: <strong>, <em>, <u>, <s>, <code>,
# <a href="...">, <ul><li>, <ol><li>, <h1>, <h2>, <blockquote>.
#
# Line breaks are literal "\n" characters inside the body — NOT <br>.
# Asana does not support <br> in rich text; if Asana sees <br> in
# html_text it silently rejects the rich-text body and stores the raw
# content as plain text (which renders with visible HTML tags). To
# protect callers, this script auto-replaces any <br>, <br/>, or
# <br /> in the body with a "\n" character before posting.
#
# Token resolution (in order):
#   1. ASANA_TOKEN env var if set and non-empty
#   2. ASANA_PERSONAL_ACCESS_TOKEN env var
# If neither is set, exits non-zero with guidance.
#
# Exit codes:
#   0  comment posted successfully (story GID printed to stdout)
#   1  invalid usage, missing token, or Asana API failure

set -euo pipefail

usage() {
  sed -n '3,30p' "$0" | sed 's/^# \{0,1\}//'
}

if [[ $# -eq 0 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 2 ]]; then
  echo "asana-post-comment: expected exactly 2 arguments (<task-gid> <body>), got $#" >&2
  usage >&2
  exit 1
fi

task_gid="$1"
body="$2"

if ! [[ "$task_gid" =~ ^[0-9]+$ ]]; then
  echo "asana-post-comment: task-gid must be numeric (got '$task_gid')" >&2
  exit 1
fi

if [[ -z "$body" ]]; then
  echo "asana-post-comment: body is empty" >&2
  exit 1
fi

# Detect field and normalise body via Python — same HTML-tag pattern used
# previously, allow-list of known tag names so plain-text comparisons like
# "x < 5 and y > 3" don't trip false positives. Python emits two lines:
# the chosen field name, then the serialised JSON payload (single-line —
# json.dumps escapes newlines in the body).
detection="$(python3 - "$body" <<'PY'
import json
import re
import sys

body = sys.argv[1]

HTML_TAG_PATTERN = re.compile(
    r"<\s*/?\s*("
    r"body|strong|em|u|s|code|a|ul|ol|li|br|p|div|span|b|i|"
    r"h[1-6]|html|head|table|tr|td|th|tbody|thead|img|pre"
    r")(\s[^>]*)?/?\s*>",
    re.IGNORECASE,
)

if HTML_TAG_PATTERN.search(body):
    # Asana rejects rich text containing <br> and silently degrades the
    # entire payload to plain text — visible HTML tags in the UI.
    # Replace <br>, <br/>, <br /> (any case) with a newline before
    # routing as html_text.
    body = re.sub(r"<\s*br\s*/?\s*>", "\n", body, flags=re.IGNORECASE)

    stripped = body.strip()
    if not (stripped.startswith("<body>") and stripped.endswith("</body>")):
        body = f"<body>{body}</body>"
    print("html_text")
    print(json.dumps({"data": {"html_text": body}}))
else:
    print("text")
    print(json.dumps({"data": {"text": body}}))
PY
)"

mode="$(printf '%s' "$detection" | sed -n '1p')"
payload="$(printf '%s' "$detection" | sed -n '2p')"

# Token resolution
token="${ASANA_TOKEN:-${ASANA_PERSONAL_ACCESS_TOKEN:-}}"
if [[ -z "$token" ]]; then
  echo "asana-post-comment: neither ASANA_TOKEN nor ASANA_PERSONAL_ACCESS_TOKEN is set." >&2
  echo "Get a personal access token at https://app.asana.com/0/my-apps and export it in ~/.zshrc." >&2
  exit 1
fi

response="$(curl -sS -w '\n__HTTP_STATUS__:%{http_code}' \
  -X POST \
  -H "Authorization: Bearer $token" \
  -H "Content-Type: application/json" \
  -d "$payload" \
  "https://app.asana.com/api/1.0/tasks/$task_gid/stories")"

status="$(printf '%s' "$response" | sed -n 's/.*__HTTP_STATUS__:\([0-9][0-9]*\).*/\1/p' | tail -1)"
body_response="$(printf '%s' "$response" | sed '$d')"

if [[ "$status" =~ ^2[0-9][0-9]$ ]]; then
  story_gid="$(printf '%s' "$body_response" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["data"]["gid"])
except Exception as e:
    print(f"<could-not-parse-gid: {e}>", file=sys.stderr)
')"
  echo "Posted comment $story_gid on task $task_gid (field=$mode)"
  exit 0
else
  echo "asana-post-comment: HTTP $status from Asana" >&2
  printf '%s\n' "$body_response" >&2
  exit 1
fi
