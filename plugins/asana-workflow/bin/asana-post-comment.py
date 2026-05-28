#!/usr/bin/env python3
r"""asana-post-comment.py — post a comment (story) to an Asana task.

Usage:
  asana-post-comment.py <task-gid> "<body>"

Pass the comment body as-authored. The script inspects the body and
routes it through the correct Asana API field automatically:

  - Body contains HTML tags (<strong>, <em>, <ul>, <a>, etc.) -> POSTed
    as `html_text`. If the body is not already wrapped in
    <body>...</body>, the script wraps it before sending.
  - Body contains no HTML tags -> POSTed as `text` (plain text). URLs
    in the body are auto-linked by Asana.

Callers do not need to choose a field. Authoring the content as plain
text or as HTML is sufficient — the script handles the rest.

Supported tags inside <body>: <strong>, <em>, <u>, <s>, <code>,
<a href="...">, <ul><li>, <ol><li>, <h1>, <h2>, <blockquote>.

Line breaks are literal "\n" characters inside the body — NOT <br>.
Asana does not support <br> in rich text; if Asana sees <br> in
html_text it silently rejects the rich-text body and stores the raw
content as plain text (which renders with visible HTML tags). To
protect callers, this script auto-replaces any <br>, <br/>, or
<br /> in the body with a "\n" character before posting.

Token resolution (in order):
  1. ASANA_TOKEN env var if set and non-empty
  2. ASANA_PERSONAL_ACCESS_TOKEN env var
If neither is set, exits non-zero with guidance.

Exit codes:
  0  comment posted successfully (story GID printed to stdout)
  1  invalid usage, missing token, or Asana API failure
"""

from __future__ import annotations

import json
import os
import re
import sys
from urllib import error, request

HTML_TAG_PATTERN = re.compile(
    r"<\s*/?\s*("
    r"body|strong|em|u|s|code|a|ul|ol|li|br|p|div|span|b|i|"
    r"h[1-6]|html|head|table|tr|td|th|tbody|thead|img|pre"
    r")(\s[^>]*)?/?\s*>",
    re.IGNORECASE,
)
BR_PATTERN = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
NEWLINE_RUN_PATTERN = re.compile(r"(?:[ \t]*\n[ \t]*){3,}")


def build_payload(body: str) -> tuple[str, dict]:
    if HTML_TAG_PATTERN.search(body):
        body = BR_PATTERN.sub("\n", body)
        body = NEWLINE_RUN_PATTERN.sub("\n\n", body)
        stripped = body.strip()
        if not (stripped.startswith("<body>") and stripped.endswith("</body>")):
            body = f"<body>{body}</body>"
        return "html_text", {"data": {"html_text": body}}
    return "text", {"data": {"text": body}}


def main(argv: list[str]) -> int:
    if len(argv) <= 1 or argv[1] in ("-h", "--help"):
        print(__doc__ or "")
        return 0

    if len(argv) != 3:
        print(
            f"asana-post-comment: expected exactly 2 arguments (<task-gid> <body>), got {len(argv) - 1}",
            file=sys.stderr,
        )
        print(__doc__ or "", file=sys.stderr)
        return 1

    task_gid, body = argv[1], argv[2]

    if not re.fullmatch(r"[0-9]+", task_gid):
        print(
            f"asana-post-comment: task-gid must be numeric (got '{task_gid}')",
            file=sys.stderr,
        )
        return 1

    if not body:
        print("asana-post-comment: body is empty", file=sys.stderr)
        return 1

    mode, payload = build_payload(body)

    token = os.environ.get("ASANA_TOKEN") or os.environ.get("ASANA_PERSONAL_ACCESS_TOKEN")
    if not token:
        print(
            "asana-post-comment: neither ASANA_TOKEN nor ASANA_PERSONAL_ACCESS_TOKEN is set.",
            file=sys.stderr,
        )
        print(
            "Get a personal access token at https://app.asana.com/0/my-apps and export it in ~/.zshrc.",
            file=sys.stderr,
        )
        return 1

    req = request.Request(
        f"https://app.asana.com/api/1.0/tasks/{task_gid}/stories",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(req) as resp:
            response_body = resp.read().decode("utf-8")
    except error.HTTPError as e:
        response_body = e.read().decode("utf-8", errors="replace")
        print(f"asana-post-comment: HTTP {e.code} from Asana", file=sys.stderr)
        print(response_body, file=sys.stderr)
        return 1
    except error.URLError as e:
        print(f"asana-post-comment: network error: {e.reason}", file=sys.stderr)
        return 1

    try:
        story_gid = json.loads(response_body)["data"]["gid"]
    except (KeyError, ValueError) as e:
        print(f"asana-post-comment: could not parse story gid from response: {e}", file=sys.stderr)
        print(response_body, file=sys.stderr)
        return 1

    print(f"Posted comment {story_gid} on task {task_gid} (field={mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
