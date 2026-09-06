"""
The shared command line::

    python -m uishot                     capture every scene to artifacts/ui/
    python -m uishot --only dashboard
    python -m uishot --list
    python -m uishot --update-golden     record the current look as expected
    python -m uishot --check             fail if anything drifted from golden
    python -m uishot --probe             exit 0 if capture works here, 2 if not

Everything here is application-agnostic. An application supplies its scene
registry and a factory that builds a `TkSession` wired to its own entry point;
`run()` does the argument parsing, the capture loop, and the golden comparison.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from .capture import compare, write_diff
from .registry import SceneRegistry
from .session import TkSession, is_supported


def run(argv: list[str] | None,
        *,
        registry: SceneRegistry,
        project_root: Path,
        session_factory: Callable[[Path, Path], TkSession],
        prog: str = "uishot") -> int:
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("--only", action="append", metavar="SCENE",
                        help="run only this scene (repeatable)")
    parser.add_argument("--out", default="artifacts/ui", type=Path)
    parser.add_argument("--golden", default="tests/golden/ui", type=Path)
    parser.add_argument("--update-golden", action="store_true",
                        help="overwrite the golden images with this run")
    parser.add_argument("--check", action="store_true",
                        help="compare against golden and exit non-zero on drift")
    parser.add_argument("--tolerance", type=int, default=8,
                        help="per-channel difference treated as unchanged")
    parser.add_argument("--list", action="store_true", help="list scenes and exit")
    parser.add_argument("--probe", action="store_true",
                        help="exit 0 if hidden-desktop capture works here, 2 if not")
    args = parser.parse_args(argv)

    scenes = registry.all_scenes()
    if args.list:
        for name in sorted(scenes):
            print(name)
        return 0

    ok, reason = is_supported()
    if args.probe:
        print("uishot: capture supported" if ok else f"uishot: unsupported — {reason}")
        return 0 if ok else 2
    if not ok:
        print(f"uishot: cannot capture here — {reason}", file=sys.stderr)
        return 2

    selected = args.only or sorted(scenes)
    unknown = [name for name in selected if name not in scenes]
    if unknown:
        print(f"uishot: unknown scene(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    out_dir = (project_root / args.out) if not args.out.is_absolute() else args.out
    golden_dir = ((project_root / args.golden)
                  if not args.golden.is_absolute() else args.golden)

    print(f"uishot: {len(selected)} scene(s) -> {out_dir}")
    captured = []
    with session_factory(out_dir, project_root) as session:
        for name in selected:
            before = len(session.shots)
            session.current_scene = name
            scenes[name](session)
            new = session.shots[before:]
            print(f"  {name:<16} {len(new)} shot(s): "
                  f"{', '.join(s.name for s in new)}")
            captured.extend(new)

    comparable = registry.golden_scenes()
    skipped_live = [n for n in selected if n not in comparable]

    if args.update_golden:
        golden_dir.mkdir(parents=True, exist_ok=True)
        recorded = [s for s in captured if s.scene in comparable]
        for shot in recorded:
            (golden_dir / shot.path.name).write_bytes(shot.path.read_bytes())
        print(f"uishot: recorded {len(recorded)} golden image(s) in {golden_dir}")
        if skipped_live:
            print(f"uishot: live scenes not recorded: {', '.join(skipped_live)}")
        return 0

    if args.check:
        from PIL import Image

        drift, missing = [], []
        for shot in captured:
            if shot.scene not in comparable:
                continue          # live data — see SceneRegistry.scene(golden=False)
            reference = golden_dir / shot.path.name
            if not reference.exists():
                missing.append(shot.name)
                continue
            result = compare(Image.open(shot.path), Image.open(reference),
                             tolerance=args.tolerance)
            if not result["match"]:
                diff_path = out_dir / "diff" / shot.path.name
                write_diff(Image.open(shot.path), Image.open(reference), diff_path)
                drift.append((shot.name, result, diff_path))

        for name, result, diff_path in drift:
            if result["size_changed"]:
                print(f"  DRIFT {name}: size changed {result['detail']}")
            else:
                print(f"  DRIFT {name}: {result['differing']:,} px "
                      f"({result['ratio'] * 100:.2f}%) in {result['bbox']}")
            print(f"        side-by-side: {diff_path}")
        for name in missing:
            print(f"  NEW   {name}: no golden image yet")

        if drift:
            print(f"uishot: {len(drift)} scene(s) drifted")
            return 1
        if missing:
            print(f"uishot: {len(missing)} scene(s) have no golden — "
                  f"run --update-golden to record them")
            return 1
        compared = [s for s in captured if s.scene in comparable]
        print(f"uishot: all {len(compared)} comparable shot(s) match golden")
        if skipped_live:
            print(f"uishot: live scenes not compared: {', '.join(skipped_live)}")

    return 0
