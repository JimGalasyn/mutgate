"""`mutgate run tests/mutations.py` — check every named mutation's contract.

Exit codes: 0 every contract holds; 1 a verdict is not OK; 2 the baseline is red or the
declaration cannot be loaded.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .core import load, run


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="mutgate",
                                 description="Named mutations as contracts on a test suite.")
    ap.add_argument("--version", action="version", version=f"mutgate {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="apply each mutation in a sandbox and judge its contract")
    r.add_argument("file", help="the mutations file (defines MUTATIONS, optionally TESTS/PATHS/ROOT/PYTHON)")
    r.add_argument("--tests", nargs="+", help="pytest targets (override the file's TESTS)")
    r.add_argument("--only", nargs="+", metavar="NAME", help="run only these mutations")
    r.add_argument("--python", help="interpreter to run pytest with (default: this one)")
    r.add_argument("--timeout", type=float, default=None, metavar="SECONDS",
                   help="abort a pytest run that takes longer (verdict ERROR)")
    r.add_argument("--pytest-arg", action="append", default=[], metavar="ARG",
                   help="extra argument passed to pytest (repeatable)")
    r.add_argument("--markdown", action="store_true", help="print the build-record table instead of the plain one")
    r.add_argument("--keep", action="store_true", help="keep the sandbox directory")
    r.add_argument("-x", "--stop", action="store_true", help="stop at the first verdict that is not OK")
    r.add_argument("-v", "--verbose", action="store_true")

    ls = sub.add_parser("list", help="list the mutations a file declares")
    ls.add_argument("file")
    return ap


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        decl = load(Path(args.file))
    except Exception as exc:  # noqa: BLE001 — every load failure is a usage error here
        print(f"mutgate: cannot load {args.file}: {exc}", file=sys.stderr)
        return 2
    if args.cmd == "list":
        w = max(len(m.name) for m in decl.mutations) if decl.mutations else 8
        for m in decl.mutations:
            exp = "invisible" if m.invisible else ", ".join(m.fires)
            print(f"{m.name:<{w}}  {m.file}  ->  {exp}")
        print(f"\nroot {decl.root}\ntests {' '.join(decl.tests)}\npaths {' '.join(decl.paths)}")
        return 0
    log = (lambda s: print(f"mutgate: {s}", file=sys.stderr, flush=True)) if args.verbose else None
    python = args.python or decl.python or sys.executable
    # absolutise here, in the caller's cwd: pytest runs with cwd=sandbox, where a relative
    # path resolves to nothing (issue #1). which() first keeps a bare `python3.12` working,
    # but returns a path containing a separator verbatim, hence abspath; not resolve(), which
    # would follow a venv's bin/python symlink to the base interpreter and lose the venv.
    found = shutil.which(python) or (python if Path(python).is_file() else None)
    if found is None:
        print(f"mutgate: interpreter not found: {python}", file=sys.stderr)
        return 2
    python = os.path.abspath(found)
    try:
        report = run(decl.mutations, decl.root, args.tests or decl.tests,
                     python=python, paths=decl.paths, only=args.only, keep=args.keep,
                     stop_early=args.stop, extra_pytest_args=args.pytest_arg, log=log,
                     timeout=args.timeout)
    except ValueError as exc:
        print(f"mutgate: {exc}", file=sys.stderr)
        return 2
    if report.baseline_failed or report.baseline_error:
        print(report.table())
        return 2
    print(report.markdown() if args.markdown else report.table())
    return 0 if report.ok else 1


def run_cli() -> None:
    sys.exit(main())


if __name__ == "__main__":
    run_cli()
