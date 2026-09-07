"""Named mutations as contracts on a test suite.

A *mutation* is an exact-string replacement in one source file of the project under test,
applied in a sandbox copy (the working tree is never touched), together with a *contract*:
the set of tests it must turn red, or the statement that it must turn nothing red.

Four verdicts do the work:

  OK           the mutation fired exactly the tests the contract names (plus any it may fire)
  DECORATION   a test the contract says must fire did not — the guard is a decoration
  OVERREACH    a test outside the contract fired — the mutation reaches further than its
               author believed, which is the tell for two copies of one convention
  VISIBLE      an `invisible` mutation (an invariance: swap a convention the measurement
               must not depend on) fired something

and two failure modes that are not verdicts about the suite:

  NOT_APPLIED  the `old` text was not found exactly `count` times, so nothing was mutated —
               a mutation that silently does not land looks identical to a working guard
  ERROR        the suite could not run (a mutation that does not compile, a collection
               error, a usage error)

A red baseline aborts the whole run: mutations are meaningless on a suite that already fails.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

__all__ = ["Mutation", "Verdict", "Report", "Sandbox", "run", "load", "run_pytest"]

_IGNORE_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
                ".ruff_cache", "node_modules", ".tox", ".nox", "dist", "build"}
_STATUSES = ("OK", "DECORATION", "OVERREACH", "VISIBLE", "NOT_APPLIED", "ERROR")


@dataclass(frozen=True)
class Mutation:
    """One named mutation and its contract.

    file      path of the source file, relative to the project root
    old/new   exact text to replace; `old` must occur exactly `count` times in the file
    fires     test-id fragments (any substring of a pytest node id, e.g. "TestK2ElderRule"
              or "test_x.py::TestK2::test_ratio") that MUST fail under the mutation
    may_fire  fragments that are allowed to fail as well, without being required
    invisible True for an invariance: the mutation must fail NOTHING
    count     how many occurrences of `old` the file must contain (all are replaced)
    note      free text, carried into reports
    """
    name: str
    file: str
    old: str
    new: str
    fires: tuple[str, ...] = ()
    may_fire: tuple[str, ...] = ()
    invisible: bool = False
    count: int = 1
    note: str = ""

    def __post_init__(self):
        for attr in ("fires", "may_fire"):
            val = getattr(self, attr)
            if isinstance(val, str):
                # a bare string would become its own letters, each matching every node id,
                # and every contract would read OK (review 2026-09-07, item 3)
                raise ValueError(f"{self.name}: {attr} must be a tuple of fragments, not a string; "
                                 f"write ({val!r},)")
            val = tuple(val)
            if any(not isinstance(f, str) or not f.strip() for f in val):
                raise ValueError(f"{self.name}: every {attr} entry must be a non-empty string")
            object.__setattr__(self, attr, val)
        if not self.name:
            raise ValueError("a mutation needs a name")
        if self.old == self.new:
            raise ValueError(f"{self.name}: old and new are identical; nothing would change")
        if not self.old:
            raise ValueError(f"{self.name}: old must be non-empty")
        if self.count < 1:
            raise ValueError(f"{self.name}: count must be >= 1")
        if self.invisible and (self.fires or self.may_fire):
            raise ValueError(f"{self.name}: an invisible mutation fires nothing; drop fires/may_fire")
        if not self.invisible and not self.fires:
            raise ValueError(f"{self.name}: name the tests it must fire, or mark it invisible")


@dataclass(frozen=True)
class Verdict:
    mutation: Mutation
    status: str
    fired: tuple[str, ...] = ()        # failing test node ids under the mutation
    missing: tuple[str, ...] = ()      # contract entries that matched no failing test
    unexpected: tuple[str, ...] = ()   # failing tests matching neither fires nor may_fire
    detail: str = ""

    def __post_init__(self):
        if self.status not in _STATUSES:
            raise ValueError(self.status)

    @property
    def ok(self) -> bool:
        return self.status == "OK"


@dataclass
class Report:
    root: Path
    tests: tuple[str, ...]
    baseline_failed: tuple[str, ...] = ()
    baseline_error: str = ""
    verdicts: list[Verdict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.baseline_failed and not self.baseline_error and all(v.ok for v in self.verdicts)

    def summary(self) -> str:
        counts = {s: sum(v.status == s for v in self.verdicts) for s in _STATUSES}
        parts = [f"{n} {s}" for s, n in counts.items() if n]
        return ", ".join(parts) if parts else "no mutations"

    def table(self) -> str:
        lines = []
        if self.baseline_error:
            lines.append(f"BASELINE ERROR: {self.baseline_error}")
            return "\n".join(lines)
        if self.baseline_failed:
            lines.append("BASELINE RED — nothing mutated. Failing before any mutation:")
            lines.extend(f"    {t}" for t in self.baseline_failed)
            return "\n".join(lines)
        w = max((len(v.mutation.name) for v in self.verdicts), default=8)
        lines.append(f"{'mutation':<{w}}  {'verdict':<11}  fired  expected")
        for v in self.verdicts:
            exp = "nothing" if v.mutation.invisible else ", ".join(v.mutation.fires)
            lines.append(f"{v.mutation.name:<{w}}  {v.status:<11}  {len(v.fired):>5}  {exp}")
            if v.status == "DECORATION":
                lines.extend(f"{'':<{w}}    did not fire: {m}" for m in v.missing)
            if v.status in ("OVERREACH", "DECORATION"):
                lines.extend(f"{'':<{w}}    unexpected:   {u}" for u in v.unexpected)
            if v.status == "VISIBLE":
                lines.extend(f"{'':<{w}}    fired:        {f}" for f in v.fired)
            if v.status in ("NOT_APPLIED", "ERROR"):
                lines.append(f"{'':<{w}}    {v.detail}")
        lines.append(f"\n{self.summary()}")
        return "\n".join(lines)

    def markdown(self) -> str:
        """A table for a design note's build record: what each mutation fires."""
        rows = ["| mutation | must fire | fired | verdict |", "|---|---|---|---|"]
        for v in self.verdicts:
            exp = "*nothing (invariance)*" if v.mutation.invisible else ", ".join(f"`{f}`" for f in v.mutation.fires)
            fired = _collapse(v.fired)
            rows.append(f"| {v.mutation.name} | {exp} | {fired} | {v.status} |")
        return "\n".join(rows)


def _collapse(ids: Sequence[str]) -> str:
    """Failing node ids collapsed to their class or module level, for a readable cell."""
    seen = []
    for nid in ids:
        parts = nid.split("::")
        key = "::".join(parts[:2]) if len(parts) >= 3 else nid
        if key not in seen:
            seen.append(key)
    return ", ".join(f"`{k}`" for k in seen) if seen else "—"


# ---------------------------------------------------------------------------------------
# the sandbox: a copy of the project the mutations are applied to
# ---------------------------------------------------------------------------------------

def project_files(root: Path) -> list[Path]:
    """Files to copy: `git ls-files` (tracked plus untracked-but-not-ignored, so uncommitted
    work is included and the venv is not) when `root` is in a git repo; otherwise a walk
    that skips the usual build and cache directories."""
    root = Path(root)
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
                              "--exclude-standard"], capture_output=True, check=True)
        rels = [r for r in out.stdout.decode("utf-8", "surrogateescape").split("\0") if r]
        files = [root / r for r in rels]
        return [f for f in files if f.is_file()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS and not d.endswith(".egg-info")]
        files.extend(Path(dirpath) / f for f in filenames)
    return files


class Sandbox:
    """A temporary copy of the project. Mutations are applied and restored here, one at a
    time; the working tree is never written."""

    def __init__(self, root: Path, keep: bool = False):
        self.root = Path(root).resolve()
        self.keep = keep
        # resolved: on a symlinked TMPDIR (macOS /var -> /private/var) an unresolved dir
        # fails its own containment check in `path` (review 2026-09-07, item 1)
        self.dir = Path(tempfile.mkdtemp(prefix="mutgate-")).resolve()
        for src in project_files(self.root):
            rel = src.relative_to(self.root)
            dst = self.dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    def path(self, rel: str) -> Path:
        p = (self.dir / rel).resolve()
        if self.dir not in p.parents and p != self.dir:
            raise ValueError(f"{rel} escapes the sandbox")
        return p

    def apply(self, m: Mutation) -> tuple[bool, str, str]:
        """(applied, original_text, detail). Applied only if `old` occurs exactly `count`
        times; otherwise nothing is written and `detail` says what was found."""
        p = self.path(m.file)
        if not p.is_file():
            return False, "", f"{m.file}: no such file in the project"
        text = p.read_text(encoding="utf-8")
        found = text.count(m.old)
        if found != m.count:
            return False, text, f"{m.file}: `old` found {found} time(s), contract says {m.count}"
        p.write_text(text.replace(m.old, m.new), encoding="utf-8")
        return True, text, ""

    def restore(self, m: Mutation, original: str) -> None:
        self.path(m.file).write_text(original, encoding="utf-8")

    def close(self) -> None:
        if not self.keep:
            shutil.rmtree(self.dir, ignore_errors=True)


# ---------------------------------------------------------------------------------------
# running pytest and reading which tests failed
# ---------------------------------------------------------------------------------------

def _node_id(rest: str) -> str:
    """The node id at the start of a summary line's remainder: everything up to the first
    " - " that is not inside a parametrisation bracket (ids like `test_x[a - b]` keep it)."""
    depth = 0
    i = 0
    while i < len(rest):
        ch = rest[i]
        if ch == "[":
            depth += 1
        elif ch == "]" and depth:
            depth -= 1
        elif depth == 0 and rest.startswith(" - ", i):
            return rest[:i].strip()
        i += 1
    return rest.strip()


_CUT_SHORT_LINE = re.compile(r"^!{3,} stopping after \d+ failures? !{3,}\s*$", re.MULTILINE)
TIMEOUT = -9999     # return code standing for "pytest did not finish in time"
CUT_SHORT = -9998   # pytest stopped early (maxfail), so the fired set is incomplete


def run_pytest(cwd: Path, tests: Sequence[str], python: str = sys.executable,
               paths: Sequence[str] = ("src", "."), extra_args: Sequence[str] = (),
               env: Optional[dict] = None, timeout: Optional[float] = None) -> tuple[int, list[str], str]:
    """Run pytest in `cwd`; return (returncode, failing node ids, tail of the output).

    Failures are read from pytest's own short summary (`-rfE`), so node ids are exactly the
    ones a contract names. `paths` are prepended to PYTHONPATH relative to `cwd`, so an
    editable install elsewhere cannot shadow the sandbox copy. A run that exceeds `timeout`
    seconds returns `TIMEOUT` as the code."""
    e = dict(os.environ if env is None else env)
    pp = [str(Path(cwd) / p) for p in paths]
    if e.get("PYTHONPATH"):
        pp.append(e["PYTHONPATH"])
    e["PYTHONPATH"] = os.pathsep.join(pp)
    e.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    # mutgate OWNS three flags: -rfE (the summary it reads), no:cacheprovider (a clean
    # sandbox) and --maxfail=0 AFTER every user argument, because a contract needs the whole
    # failure set and a project's addopts "-x" / "--maxfail=N" would truncate it to a
    # consistent-looking single failure (review 2026-09-07, second round)
    cmd = [python, "-m", "pytest", "-q", "-rfE", "-p", "no:cacheprovider", "--no-header",
           *extra_args, "--maxfail=0", *tests]
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), env=e, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"")
        out = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
        return TIMEOUT, [], f"pytest exceeded {timeout} s\n" + "\n".join(out.strip().splitlines()[-25:])
    failed = []
    for line in proc.stdout.splitlines():
        if line.startswith("FAILED ") or line.startswith("ERROR "):
            nid = _node_id(line.split(" ", 1)[1])
            # "ERROR tests/x.py" with no "::" is a COLLECTION error (the file did not
            # import), not a red test; it is reported through the return code instead
            if line.startswith("ERROR ") and "::" not in nid:
                continue
            if nid and nid not in failed:
                failed.append(nid)
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-25:]
    if _CUT_SHORT_LINE.search(proc.stdout):
        # the belt: pytest announces a truncated run ("!!! stopping after N failures !!!");
        # a conftest setting config.option.maxfail can get past the flag above. Anchored to
        # a whole line at column 0: a target's own captured output can quote the phrase
        # (mutgate's suite does), and that must not read as a truncated run
        return CUT_SHORT, failed, "the run was cut short (maxfail); the fired set is incomplete\n" + "\n".join(tail)
    return proc.returncode, failed, "\n".join(tail)


# ---------------------------------------------------------------------------------------
# the contract check
# ---------------------------------------------------------------------------------------

_NO_SUMMARY = ("pytest reported failures but none could be read from its short summary; is "
               "the summary suppressed (addopts --no-summary / -p no:terminal)? mutgate needs -rfE")


def _classify(m: Mutation, rc: int, fired: list[str], tail: str) -> Verdict:
    fired_t = tuple(fired)
    if rc in (TIMEOUT, CUT_SHORT):
        return Verdict(m, "ERROR", fired_t, detail=tail)
    if rc == 1 and not fired:
        # the gate that cannot fail, in the classifier itself: an invisible mutation that
        # broke the suite would read OK, a firing one DECORATION (review 2026-09-07, item 2)
        return Verdict(m, "ERROR", fired_t, detail=f"{_NO_SUMMARY}\n{tail}")
    if rc not in (0, 1):
        # only 0 and 1 mean the test loop ran to completion. An interrupted run (exit 2)
        # can carry a PARTIAL fired set -- a conftest setting session.shouldstop after the
        # first failure gives one failure in the summary and "!!! Interrupted !!!", not the
        # maxfail line -- and a partial set is never a verdict (review, third round)
        why = {2: "interrupted, or collection failed (does the mutated file still compile?); "
                  "any fired set is partial",
               3: "pytest internal error", 4: "pytest usage error", 5: "no tests collected"}.get(rc, f"pytest exit {rc}")
        return Verdict(m, "ERROR", fired_t, detail=f"{why}\n{tail}")
    if m.invisible:
        return Verdict(m, "VISIBLE" if fired else "OK", fired_t)
    missing = tuple(e for e in m.fires if not any(e in f for f in fired))
    allowed = m.fires + m.may_fire
    unexpected = tuple(f for f in fired if not any(e in f for e in allowed))
    if missing:
        return Verdict(m, "DECORATION", fired_t, missing, unexpected)
    if unexpected:
        return Verdict(m, "OVERREACH", fired_t, missing, unexpected)
    return Verdict(m, "OK", fired_t)


def run(mutations: Iterable[Mutation], root: Path, tests: Sequence[str],
        python: str = sys.executable, paths: Sequence[str] = ("src", "."),
        only: Optional[Sequence[str]] = None, keep: bool = False, stop_early: bool = False,
        extra_pytest_args: Sequence[str] = (), log=None, timeout: Optional[float] = None) -> Report:
    """Apply each mutation in a sandbox copy of `root`, run `tests`, and judge the contract.

    The baseline (no mutation) runs first; if it is red the report says so and nothing is
    mutated. Each mutation is applied, run, and restored before the next."""
    root = Path(root).resolve()
    tests = tuple(tests)
    report = Report(root=root, tests=tests)
    mutations = list(mutations)
    if only is not None:
        known = {m.name for m in mutations}
        unknown = [n for n in only if n not in known]
        if unknown:
            raise ValueError(f"--only names no declared mutation: {unknown}")
        mutations = [m for m in mutations if m.name in only]
    if not mutations:
        raise ValueError("no mutations to run: an emptied declaration must not pass green")
    log = log or (lambda s: None)
    sb = Sandbox(root, keep=keep)
    try:
        log(f"sandbox {sb.dir}")
        rc, failed, tail = run_pytest(sb.dir, tests, python, paths, extra_pytest_args, timeout=timeout)
        if rc not in (0, 1) or (rc == 1 and not failed):
            note = _NO_SUMMARY if rc == 1 else ""
            report.baseline_error = f"baseline could not run (pytest exit {rc}) {note}\n{tail}"
            return report
        if failed:
            report.baseline_failed = tuple(failed)
            return report
        log("baseline green")
        for m in mutations:
            applied, original, detail = sb.apply(m)
            if not applied:
                v = Verdict(m, "NOT_APPLIED", detail=detail)
            else:
                try:
                    rc, failed, tail = run_pytest(sb.dir, tests, python, paths, extra_pytest_args,
                                                  timeout=timeout)
                finally:
                    sb.restore(m, original)
                v = _classify(m, rc, failed, tail)
            report.verdicts.append(v)
            log(f"{m.name}: {v.status} ({len(v.fired)} fired)")
            if stop_early and not v.ok:
                break
    finally:
        sb.close()
    return report


# ---------------------------------------------------------------------------------------
# the declaration file
# ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Declaration:
    mutations: tuple[Mutation, ...]
    root: Path
    tests: tuple[str, ...]
    paths: tuple[str, ...]
    python: Optional[str] = None


def _find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").is_file() or (p / ".git").exists():
            return p
    return start


def load(path: Path) -> Declaration:
    """Import a mutations file. It must define `MUTATIONS` (a sequence of `Mutation`);
    optionally `TESTS` (pytest targets, default the file's own directory), `PATHS`
    (PYTHONPATH entries relative to the root, default ("src", ".")), `ROOT` (relative to the
    declaration file; default: the nearest ancestor holding pyproject.toml or .git) and
    `PYTHON` (interpreter)."""
    path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location(f"_mutgate_decl_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "MUTATIONS"):
        raise ValueError(f"{path} defines no MUTATIONS")
    muts = tuple(mod.MUTATIONS)
    for m in muts:
        if not isinstance(m, Mutation):
            raise ValueError(f"{path}: MUTATIONS holds a {type(m).__name__}, not a Mutation")
    names = [m.name for m in muts]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"{path}: duplicate mutation names {dupes}")
    root_decl = getattr(mod, "ROOT", None)
    root = (_find_root(path.parent) if root_decl is None else (path.parent / root_decl)).resolve()
    tests_default = str(path.parent.relative_to(root)) if root in path.parent.parents or root == path.parent else "tests"
    tests = tuple(getattr(mod, "TESTS", (tests_default,)))
    paths = tuple(getattr(mod, "PATHS", ("src", ".")))
    return Declaration(muts, root, tests, paths, getattr(mod, "PYTHON", None))
