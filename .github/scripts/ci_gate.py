"""Release gate: every required CI job must have concluded 'success' on the commit.

Reads all check runs (paginated) from the GitHub API JSON on stdin, so the release job's own
running check can never satisfy the gate, and a commit where CI never ran fails.

  gh api --paginate "repos/OWNER/REPO/commits/SHA/check-runs?per_page=100" | python ci_gate.py
"""

import json
import sys

REQUIRED = ("ml", "backend", "web", "e2e", "mobile", "docker")


def evaluate(pages: list[dict]) -> tuple[bool, dict[str, str]]:
    latest: dict[str, tuple[str, str]] = {}
    for page in pages:
        for run in page.get("check_runs", []):
            name = run.get("name", "")
            if name in REQUIRED:
                started = run.get("started_at") or ""
                if name not in latest or started > latest[name][0]:
                    latest[name] = (started, run.get("conclusion") or run.get("status") or "missing")
    states = {name: latest.get(name, ("", "missing"))[1] for name in REQUIRED}
    return all(state == "success" for state in states.values()), states


def parse_pages(raw: str) -> list[dict]:
    """`gh api --paginate` concatenates one JSON object per page."""
    decoder, pages, index = json.JSONDecoder(), [], 0
    raw = raw.strip()
    while index < len(raw):
        page, end = decoder.raw_decode(raw, index)
        pages.append(page)
        index = end
        while index < len(raw) and raw[index].isspace():
            index += 1
    return pages


if __name__ == "__main__":
    ok, states = evaluate(parse_pages(sys.stdin.read()))
    for name, state in states.items():
        print(f"{name:8s} {state}")
    sys.exit(0 if ok else 1)
