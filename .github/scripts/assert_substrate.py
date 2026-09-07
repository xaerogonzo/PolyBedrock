"""Fail the consumer job unless the PolyBedrock being imported is the one under test.

`polybedrock` is a PEP 420 namespace package, which makes this failure mode both
easy to hit and invisible. A namespace merges **every** matching directory on
`sys.path`, so a consumer that declares `polybedrock-core @ git+https://…` can
leave a second copy in `site-packages` that keeps contributing submodules after
the local editable install lands. The job then goes green against a substrate
that is not the one being changed — the single result the consumer stage must
never produce, and one that looks exactly like success.

Printing `polybedrock.__path__` is not enough: the namespace legitimately lists
several portions, and reading which one *wins* off that list is guesswork. So
this imports real modules from both distributions and asks each one where it
actually came from, which is the only answer that settles it.

Usage:  python .github/scripts/assert_substrate.py <checkout-dir>
"""
from __future__ import annotations

import pathlib
import sys


#: One module from each distribution. Both must resolve inside the checkout, or
#: the two packages disagree about which PolyBedrock this job is testing.
PROBES = ("polybedrock.win_security", "polybedrock.ui.theme")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2

    root = pathlib.Path(argv[1]).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    import importlib

    strays: list[str] = []
    for name in PROBES:
        module = importlib.import_module(name)
        origin = getattr(module, "__file__", None)
        if origin is None:
            strays.append(f"{name}: no __file__ (namespace shadow?)")
            continue
        resolved = pathlib.Path(origin).resolve()
        where = "OK  " if root in resolved.parents else "STRAY"
        print(f"  {where}  {name}\n           {resolved}")
        if root not in resolved.parents:
            strays.append(f"{name} -> {resolved}")

    if strays:
        print(
            "\nThis job is NOT testing the PolyBedrock in this checkout.\n"
            "A consumer's own dependency (a git URL or an index) left a copy\n"
            "that the namespace package is still serving. The editable install\n"
            "step has to win, or a green result here means nothing:\n  "
            + "\n  ".join(strays),
            file=sys.stderr,
        )
        return 1

    print(f"\nBoth distributions resolve inside {root} — substrate confirmed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
