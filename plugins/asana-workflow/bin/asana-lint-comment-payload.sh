#!/usr/bin/env bash
#
# lint-comment-payload.sh — validate an Asana stories POST payload before sending it
#
# Usage:
#   lint-comment-payload.sh '<json>'
#   echo '<json>' | lint-comment-payload.sh
#
# Validates the JSON body that would be POSTed to
# /tasks/<task-gid>/stories. Exits 0 if the payload conforms to Asana's
# comment-body field rules, non-zero with a description of the violation on
# stderr otherwise. See asana-api SKILL.md → "Post Comment on Task" for the
# rules being enforced.
#
# Rules:
#   - data.text and data.html_text are mutually exclusive. Provide exactly one.
#   - data.text must not contain HTML tags. Asana renders them as literal
#     angle brackets.
#   - data.html_text must be wrapped in <body>...</body>. Asana rejects
#     rich-text bodies without it.
#
# Exit codes:
#   0  payload OK
#   1  invalid usage / not valid JSON / missing data object
#   2  data.text contains HTML tags
#   3  data.html_text is missing the <body> wrapper
#   4  both data.text and data.html_text are set
#   5  neither data.text nor data.html_text is set

set -euo pipefail

usage() {
  sed -n '3,30p' "$0" | sed 's/^# \{0,1\}//'
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ge 1 ]]; then
  payload="$1"
else
  payload="$(cat)"
fi

python3 - "$payload" <<'PY'
import json
import re
import sys

raw = sys.argv[1]

try:
    obj = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"lint-comment-payload: invalid JSON: {e}", file=sys.stderr)
    sys.exit(1)

data = obj.get("data") if isinstance(obj, dict) else None
if not isinstance(data, dict):
    print("lint-comment-payload: payload missing 'data' object", file=sys.stderr)
    sys.exit(1)

text = data.get("text")
html_text = data.get("html_text")

has_text = isinstance(text, str) and text != ""
has_html = isinstance(html_text, str) and html_text != ""

if has_text and has_html:
    print(
        "lint-comment-payload: data.text and data.html_text are mutually exclusive; "
        "provide only one",
        file=sys.stderr,
    )
    sys.exit(4)

if not has_text and not has_html:
    print(
        "lint-comment-payload: payload must include data.text (plain) "
        "or data.html_text (rich)",
        file=sys.stderr,
    )
    sys.exit(5)

HTML_TAG_PATTERN = re.compile(
    r"<\s*/?\s*("
    r"body|strong|em|u|s|code|a|ul|ol|li|br|p|div|span|b|i|"
    r"h[1-6]|html|head|table|tr|td|th|tbody|thead|img|pre"
    r")(\s[^>]*)?/?\s*>",
    re.IGNORECASE,
)

if has_text and HTML_TAG_PATTERN.search(text):
    print(
        "lint-comment-payload: data.text contains HTML tags. "
        "Use data.html_text wrapped in <body>...</body> for rich text.",
        file=sys.stderr,
    )
    sys.exit(2)

if has_html:
    stripped = html_text.strip()
    if not (stripped.startswith("<body>") and stripped.endswith("</body>")):
        print(
            "lint-comment-payload: data.html_text must be wrapped in <body>...</body>",
            file=sys.stderr,
        )
        sys.exit(3)

sys.exit(0)
PY
