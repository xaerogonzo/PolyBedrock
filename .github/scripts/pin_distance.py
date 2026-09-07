"""Report how far each pinned consumer revision is behind its master.

Run from the repository root, or via ``docs/ECOSYSTEM_HEALTH.md``. Needs the
``gh`` CLI authenticated; every comparison is a read.

This exists because a stale pin is silent. The consumer job stays green, and
fast, against a revision nobody is shipping -- so the only way it surfaces is
if something goes looking. It does not bump anything: see ``docs/adr/0001``
for why that stays a deliberate act.

Exit status is 0 whether or not the pins have drifted. Distance is information,
not a failure -- a pin is meant to lag while a consumer moves. It is 1 only if
the report itself could not be produced, because a check that could not run
must never look like a check that passed.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "tests.yml"

#: Deliberately a regex over the workflow text rather than a YAML parse. The
#: workflow is where the pins actually live, and reading them the way a person
#: reads them keeps this honest about where the authority is -- there is no
#: second list here that could quietly disagree with the thing CI obeys.
_PIN = re.compile(
    r"repo:\s*(?P<repo>\S+)\s+ref:\s*(?P<ref>[0-9a-f]{40})"
)


def pins() -> list[tuple[str, str]]:
    """Every ``(repo, pinned revision)`` the consumer matrix names."""
    return [(m.group("repo"), m.group("ref"))
            for m in _PIN.finditer(WORKFLOW.read_text(encoding="utf-8"))]


def distance(repo: str, ref: str) -> int | None:
    """Commits on ``repo``'s master that the pinned revision does not have.

    ``None`` means the question could not be answered -- gh missing, no network,
    or a pin that is no longer on that repository. That is reported as such
    rather than as zero, which would read as "healthy".
    """
    proc = subprocess.run(
        ["gh", "api", f"repos/{repo}/compare/{ref}...master", "--jq", ".ahead_by"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


def main() -> int:
    found = pins()
    if not found:
        print("no consumer pins found in the workflow -- has its shape changed?",
              file=sys.stderr)
        return 1

    failed = False
    for repo, ref in found:
        ahead = distance(repo, ref)
        if ahead is None:
            print(f"{repo}: could not compare -- gh unavailable, or the pin is "
                  f"no longer on that repository", file=sys.stderr)
            failed = True
        elif ahead == 0:
            print(f"{repo}: pinned at master ({ref[:7]})")
        else:
            print(f"{repo}: {ahead} commit(s) behind master -- pinned at "
                  f"{ref[:7]}, validating none of them")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
