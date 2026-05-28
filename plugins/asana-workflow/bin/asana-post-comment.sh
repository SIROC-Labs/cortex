#!/usr/bin/env bash
#
# asana-post-comment.sh — post a comment (story) to an Asana task with the
# correct body field, with hard-enforced field-shape rules
#
# Usage:
#   asana-post-comment.sh <task-gid> --text       "<plain text body>"
#   asana-post-comment.sh <task-gid> --html-text  "<body>...rich body...</body>"
#
# Exactly one of --text or --html-text must be provided. This is the single
# supported path for posting Asana task comments from the asana-workflow
# plugin — it exists because the raw POST /tasks/<gid>/stories endpoint has
# two mutually-exclusive body fields whose shape rules the model has
# repeatedly forgotten when constructing curl invocations directly. By
# routing every comment through this wrapper, the broken-payload bug
# becomes structurally impossible.
#
# Behavior:
#   --text       Body must NOT contain HTML tags. Asana renders tags as
#                literal characters in the `text` field. URLs in the body
#                are auto-linked by Asana.
#   --html-text  Body MUST be wrapped in <body>...</body>. Asana rejects
#                rich-text bodies that aren't body-wrapped, and we reject
#                them locally before issuing the POST. Supported tags
#                inside <body> include: <strong>, <em>, <u>, <s>, <code>,
#                <a href="...">, <ul><li>, <ol><li>, <br>, <h1>-<h2>.
#
# Token resolution (in order):
#   1. ASANA_TOKEN env var if set and non-empty
#   2. ASANA_PERSONAL_ACCESS_TOKEN env var
# If neither is set, exits non-zero with guidance.
#
# Exit codes:
#   0  comment posted successfully (story GID printed to stdout)
#   1  invalid usage / missing token / network or Asana API failure
#   2  --text body contains HTML tags (rejected before POST)
#   3  --html-text body missing <body>...</body> wrapper (rejected before POST)
#   4  both --text and --html-text supplied
#   5  neither --text nor --html-text supplied

set -euo pipefail

usage() {
  sed -n '3,35p' "$0" | sed 's/^# \{0,1\}//'
}

if [[ $# -eq 0 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

task_gid=""
mode=""
body=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --text)
      if [[ -n "$mode" ]]; then
        echo "asana-post-comment: --text and --html-text are mutually exclusive" >&2
        exit 4
      fi
      mode="text"
      body="${2:-}"
      shift 2
      ;;
    --html-text)
      if [[ -n "$mode" ]]; then
        echo "asana-post-comment: --text and --html-text are mutually exclusive" >&2
        exit 4
      fi
      mode="html_text"
      body="${2:-}"
      shift 2
      ;;
    --*)
      echo "asana-post-comment: unknown flag: $1" >&2
      exit 1
      ;;
    *)
      if [[ -z "$task_gid" ]]; then
        task_gid="$1"
        shift
      else
        echo "asana-post-comment: unexpected positional arg: $1" >&2
        exit 1
      fi
      ;;
  esac
done

if [[ -z "$task_gid" ]]; then
  echo "asana-post-comment: missing <task-gid>" >&2
  usage >&2
  exit 1
fi

if ! [[ "$task_gid" =~ ^[0-9]+$ ]]; then
  echo "asana-post-comment: task-gid must be numeric (got '$task_gid')" >&2
  exit 1
fi

if [[ -z "$mode" ]]; then
  echo "asana-post-comment: must supply exactly one of --text or --html-text" >&2
  exit 5
fi

if [[ -z "$body" ]]; then
  echo "asana-post-comment: --$mode body is empty" >&2
  exit 1
fi

# Field-shape lint (deterministic; mirrors asana-lint-comment-payload.sh rules).
# We re-validate here even though there is no other entry point, so the script
# is self-contained and auditable.
python3 - "$mode" "$body" <<'PY'
import re
import sys

mode, body = sys.argv[1], sys.argv[2]

HTML_TAG_PATTERN = re.compile(
    r"<\s*/?\s*("
    r"body|strong|em|u|s|code|a|ul|ol|li|br|p|div|span|b|i|"
    r"h[1-6]|html|head|table|tr|td|th|tbody|thead|img|pre"
    r")(\s[^>]*)?/?\s*>",
    re.IGNORECASE,
)

if mode == "text":
    if HTML_TAG_PATTERN.search(body):
        print(
            "asana-post-comment: --text body contains HTML tags. "
            "Use --html-text with a <body>...</body> wrapper for rich text.",
            file=sys.stderr,
        )
        sys.exit(2)
elif mode == "html_text":
    stripped = body.strip()
    if not (stripped.startswith("<body>") and stripped.endswith("</body>")):
        print(
            "asana-post-comment: --html-text body must be wrapped in <body>...</body>",
            file=sys.stderr,
        )
        sys.exit(3)
PY

# Token resolution
token="${ASANA_TOKEN:-${ASANA_PERSONAL_ACCESS_TOKEN:-}}"
if [[ -z "$token" ]]; then
  echo "asana-post-comment: neither ASANA_TOKEN nor ASANA_PERSONAL_ACCESS_TOKEN is set." >&2
  echo "Get a personal access token at https://app.asana.com/0/my-apps and export it in ~/.zshrc." >&2
  exit 1
fi

payload="$(python3 -c '
import json, sys
mode, body = sys.argv[1], sys.argv[2]
print(json.dumps({"data": {mode: body}}))
' "$mode" "$body")"

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
  echo "Posted comment $story_gid on task $task_gid (mode=$mode)"
  exit 0
else
  echo "asana-post-comment: HTTP $status from Asana" >&2
  printf '%s\n' "$body_response" >&2
  exit 1
fi
