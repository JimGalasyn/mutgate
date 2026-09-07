"""mutgate's own suite: a toy project built in a temp dir, each verdict reached on purpose.

The toy has two conventions that its tests pin -- an elder rule and a cut -- and a duplicated
copy of the tie rule, so the OVERREACH verdict has something real to catch.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from mutgate import Mutation, load, run
from mutgate.core import Sandbox, project_files, run_pytest

TOY_ENGINE = textwrap.dedent('''
    """A toy engine with an elder rule and a cut."""

    def elder(birth, a, b):
        # the stronger birth survives; equal births -> lower index
        if (birth[a], -a) >= (birth[b], -b):
            return a
        return b


    def cut(birth, s):
        return [i for i, x in enumerate(birth) if x >= s]


    def label(birth, i):
        # a SECOND COPY of the tie rule, so a mutation of `elder` alone disagrees with it
        others = [j for j in range(len(birth)) if (birth[j], -j) >= (birth[i], -i)]
        return min(others, key=lambda j: (-birth[j], j))
''')

TOY_TESTS = textwrap.dedent('''
    from toy.engine import cut, elder, label


    class TestElderRule:
        def test_stronger_birth_wins(self):
            assert elder([1.0, 2.0], 0, 1) == 1

        def test_tie_goes_to_lower_index(self):
            assert elder([1.0, 1.0], 0, 1) == 0


    class TestCut:
        def test_cut_keeps_at_or_above(self):
            assert cut([0.1, 0.5, 1.0], 0.5) == [1, 2]


    class TestLabelAgreesWithElder:
        def test_label_is_an_elder_under_the_elder_rule(self):
            # two views of one convention must agree: the label of i must be what the
            # elder rule picks between i and its label
            birth = [1.0, 1.0, 0.5]
            for i in range(3):
                assert elder(birth, i, label(birth, i)) == label(birth, i)
''')


def _write_toy(root: Path, engine: str = TOY_ENGINE, tests: str = TOY_TESTS) -> Path:
    (root / "toy").mkdir(parents=True)
    (root / "toy" / "__init__.py").write_text("")
    (root / "toy" / "engine.py").write_text(engine)
    (root / "tests").mkdir()
    (root / "tests" / "__init__.py").write_text("")
    (root / "tests" / "test_toy.py").write_text(tests)
    (root / "pyproject.toml").write_text('[project]\nname = "toy"\nversion = "0"\n')
    return root


@pytest.fixture
def toy(tmp_path):
    return _write_toy(tmp_path / "toy_project")


def _run(muts, root, **kw):
    return run(muts, root, ("tests",), python=sys.executable, paths=(".",), **kw)


# ---------------------------------------------------------------------------------------
# the verdicts, each reached on purpose
# ---------------------------------------------------------------------------------------

class TestVerdicts:
    def test_ok_when_exactly_the_named_tests_fire(self, toy):
        m = Mutation("stronger-loses", "toy/engine.py",
                     old="if (birth[a], -a) >= (birth[b], -b):", new="if (birth[a], -a) < (birth[b], -b):",
                     fires=("TestElderRule::test_stronger_birth_wins",), may_fire=("TestElderRule", "TestLabel"))
        r = _run([m], toy)
        assert r.ok and r.verdicts[0].status == "OK"
        assert any("test_stronger_birth_wins" in f for f in r.verdicts[0].fired)

    def test_decoration_when_a_named_guard_does_not_fire(self, toy):
        # `cut` uses >=; a >= to > mutation changes the boundary case, which TestCut pins;
        # but TestElderRule is named too and cannot fire from a change in `cut`
        m = Mutation("cut-strict", "toy/engine.py", old="if x >= s]", new="if x > s]",
                     fires=("TestCut", "TestElderRule"))
        r = _run([m], toy)
        v = r.verdicts[0]
        assert v.status == "DECORATION" and v.missing == ("TestElderRule",)
        assert not r.ok

    def test_overreach_is_the_two_copies_tell(self, toy):
        """Reversing the tie rule in `elder` ALONE should only move TestElderRule's tie test;
        it also breaks TestLabelAgreesWithElder, because `label` carries a second copy of
        the convention. The contract that names only the tie test overreaches -- that is
        the finding, not the mutation."""
        m = Mutation("tie-to-higher-index", "toy/engine.py",
                     old="if (birth[a], -a) >= (birth[b], -b):", new="if (birth[a], a) >= (birth[b], b):",
                     fires=("test_tie_goes_to_lower_index",))
        r = _run([m], toy)
        v = r.verdicts[0]
        assert v.status == "OVERREACH"
        assert any("TestLabelAgreesWithElder" in u for u in v.unexpected)

    def test_visible_when_an_invariance_breaks(self, toy):
        m = Mutation("tie-to-higher-index", "toy/engine.py",
                     old="if (birth[a], -a) >= (birth[b], -b):", new="if (birth[a], a) >= (birth[b], b):",
                     invisible=True)
        r = _run([m], toy)
        assert r.verdicts[0].status == "VISIBLE" and r.verdicts[0].fired

    def test_invisible_ok_when_nothing_fires(self, toy):
        # a comment change is the trivially invisible mutation
        m = Mutation("comment", "toy/engine.py", old="# the stronger birth survives", new="# the elder survives",
                     invisible=True)
        r = _run([m], toy)
        assert r.verdicts[0].status == "OK" and r.ok

    def test_not_applied_when_old_is_absent_or_ambiguous(self, toy):
        absent = Mutation("absent", "toy/engine.py", old="no such text", new="x", fires=("TestCut",))
        ambiguous = Mutation("ambiguous", "toy/engine.py", old="birth", new="b", fires=("TestCut",))
        r = _run([absent, ambiguous], toy)
        assert [v.status for v in r.verdicts] == ["NOT_APPLIED", "NOT_APPLIED"]
        assert "found 0 time(s)" in r.verdicts[0].detail
        assert "contract says 1" in r.verdicts[1].detail

    def test_count_lets_a_repeated_text_be_mutated_everywhere(self, toy):
        # every `>=` in the file becomes `>`: the cut's boundary case fires; the elder
        # rule's tie test does NOT (tuples of distinct indices are never equal, so >= and >
        # agree there -- a mutation that looks like it should fire a guard and cannot);
        # `label`'s comprehension now excludes i itself and may raise
        k = TOY_ENGINE.count(">=")
        m = Mutation("ge-to-gt", "toy/engine.py", old=">=", new=">", count=k,
                     fires=("TestCut",), may_fire=("TestLabel",))
        r = _run([m], toy)
        assert r.verdicts[0].status == "OK", r.table()
        assert not any("test_tie" in f for f in r.verdicts[0].fired)

    def test_error_when_the_mutation_does_not_compile(self, toy):
        m = Mutation("syntax", "toy/engine.py", old="def cut(birth, s):", new="def cut(birth, s)", fires=("TestCut",))
        r = _run([m], toy)
        assert r.verdicts[0].status == "ERROR" and "compile" in r.verdicts[0].detail

    def test_red_baseline_aborts_before_any_mutation(self, tmp_path):
        broken = TOY_TESTS + "\n\ndef test_already_red():\n    assert False\n"
        root = _write_toy(tmp_path / "red", tests=broken)
        m = Mutation("cut-strict", "toy/engine.py", old="if x >= s]", new="if x > s]", fires=("TestCut",))
        r = _run([m], root)
        assert r.baseline_failed and not r.verdicts and not r.ok
        assert "BASELINE RED" in r.table()


class TestGatesThatCannotFail:
    """Review 2026-09-07: three silent false passes in the contract check itself."""

    def test_suppressed_summary_is_an_error_not_a_verdict(self, toy):
        """A project whose pytest config hides the short summary: pytest exits 1 but no
        failure can be read. That must be ERROR -- an invisible mutation that broke the
        suite would otherwise read OK (item 2)."""
        (toy / "pyproject.toml").write_text('[project]\nname = "toy"\nversion = "0"\n'
                                            '[tool.pytest.ini_options]\naddopts = "--no-summary"\n')
        m = Mutation("tie-to-higher-index", "toy/engine.py",
                     old="if (birth[a], -a) >= (birth[b], -b):", new="if (birth[a], a) >= (birth[b], b):",
                     invisible=True)
        r = _run([m], toy)
        assert r.verdicts[0].status == "ERROR" and "summary" in r.verdicts[0].detail

    def test_a_bare_string_or_empty_fragment_is_refused(self):
        """`fires="TestElderRule"` would become thirteen one-letter fragments, each matching
        every node id, and every contract would read OK (item 3)."""
        with pytest.raises(ValueError, match="not a string"):
            Mutation("x", "f", old="a", new="b", fires="TestElderRule")
        with pytest.raises(ValueError, match="non-empty"):
            Mutation("x", "f", old="a", new="b", fires=("",))
        with pytest.raises(ValueError, match="not a string"):
            Mutation("x", "f", old="a", new="b", fires=("T",), may_fire="Other")

    def test_unknown_only_name_and_empty_list_are_errors(self, toy):
        """A typo in --only, or an emptied MUTATIONS list, must not pass green (item 4)."""
        m = Mutation("cut-strict", "toy/engine.py", old="if x >= s]", new="if x > s]", fires=("TestCut",))
        with pytest.raises(ValueError, match="names no declared mutation"):
            _run([m], toy, only=["cut-strikt"])
        with pytest.raises(ValueError, match="no mutations"):
            _run([], toy)

    def test_parametrised_ids_with_a_dash_are_kept_whole(self, toy):
        from mutgate.core import _node_id
        assert _node_id("tests/t.py::test_x[a - b] - AssertionError: 1 - 2") == "tests/t.py::test_x[a - b]"
        assert _node_id("tests/t.py::test_x - AssertionError") == "tests/t.py::test_x"
        assert _node_id("tests/t.py::test_x") == "tests/t.py::test_x"

    def test_timeout_is_an_error(self, toy):
        hang = TOY_TESTS + "\n\ndef test_hang():\n    import time; time.sleep(30)\n"
        (toy / "tests" / "test_toy.py").write_text(hang)
        m = Mutation("cut-strict", "toy/engine.py", old="if x >= s]", new="if x > s]", fires=("TestCut",))
        r = run([m], toy, ("tests",), python=sys.executable, paths=(".",), timeout=3)
        assert r.baseline_error and "exceeded" in r.baseline_error


# ---------------------------------------------------------------------------------------
# the sandbox never touches the working tree
# ---------------------------------------------------------------------------------------

class TestSandbox:
    def test_working_tree_is_untouched_and_restored_between_mutations(self, toy):
        before = hashlib.sha256((toy / "toy" / "engine.py").read_bytes()).hexdigest()
        m1 = Mutation("a", "toy/engine.py", old="if x >= s]", new="if x > s]", fires=("TestCut",))
        m2 = Mutation("b", "toy/engine.py", old="if x >= s]", new="if x > s]", fires=("TestCut",))
        r = _run([m1, m2], toy)
        assert [v.status for v in r.verdicts] == ["OK", "OK"]     # m2 applied to a RESTORED file
        assert hashlib.sha256((toy / "toy" / "engine.py").read_bytes()).hexdigest() == before

    def test_keep_leaves_the_sandbox_on_disk(self, toy):
        sb = Sandbox(toy, keep=True)
        try:
            assert (sb.dir / "toy" / "engine.py").is_file()
            with pytest.raises(ValueError, match="escapes"):
                sb.path("../outside.py")
        finally:
            sb.keep = False
            sb.close()
        assert not sb.dir.exists()

    def test_project_files_skips_caches_and_venvs(self, toy):
        (toy / ".venv").mkdir(); (toy / ".venv" / "x.py").write_text("")
        (toy / "toy" / "__pycache__").mkdir(); (toy / "toy" / "__pycache__" / "e.pyc").write_text("")
        rels = {str(f.relative_to(toy)) for f in project_files(toy)}
        assert "toy/engine.py" in rels and not any(".venv" in r or "__pycache__" in r for r in rels)

    def test_sandbox_shadows_an_installed_copy(self, toy, tmp_path):
        """PYTHONPATH puts the sandbox first, so the sandbox copy is the one imported even
        when a BROKEN copy of the same package sits on PYTHONPATH already."""
        import os
        elsewhere = tmp_path / "elsewhere"
        (elsewhere / "toy").mkdir(parents=True)
        (elsewhere / "toy" / "__init__.py").write_text("")
        (elsewhere / "toy" / "engine.py").write_text("raise RuntimeError('the wrong copy was imported')\n")
        env = {**os.environ, "PYTHONPATH": str(elsewhere)}
        sb = Sandbox(toy)
        try:
            rc, failed, tail = run_pytest(sb.dir, ("tests",), sys.executable, (".",), env=env)
        finally:
            sb.close()
        assert rc == 0 and failed == [], tail
        # and the broken copy IS what a bare interpreter would see
        out = subprocess.run([sys.executable, "-c", "import toy.engine"], env=env, capture_output=True, text=True)
        assert out.returncode != 0

    def test_sandbox_survives_a_symlinked_tmpdir(self, toy, tmp_path, monkeypatch):
        """macOS keeps TMPDIR behind a symlink (/var -> /private/var); the containment check
        must compare resolved paths (review 2026-09-07, item 1)."""
        import tempfile
        real = tmp_path / "real_tmp"; real.mkdir()
        link = tmp_path / "link_tmp"; link.symlink_to(real, target_is_directory=True)
        monkeypatch.setattr(tempfile, "tempdir", str(link))
        sb = Sandbox(toy)
        try:
            assert sb.path("toy/engine.py").is_file()
        finally:
            sb.close()

    def test_git_repo_sandbox_takes_untracked_and_skips_ignored(self, toy):
        """The `git ls-files` branch: tracked and untracked-but-not-ignored files are copied,
        ignored ones are not, and an uncommitted edit is what gets mutated."""
        subprocess.run(["git", "init", "-q", str(toy)], check=True)
        (toy / ".gitignore").write_text(".venv/\n*.log\n")
        subprocess.run(["git", "-C", str(toy), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(toy), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], check=True)
        (toy / ".venv").mkdir(); (toy / ".venv" / "x.py").write_text("")
        (toy / "run.log").write_text("")
        (toy / "toy" / "extra.py").write_text("NEW = 1\n")                       # untracked, not ignored
        (toy / "toy" / "engine.py").write_text(TOY_ENGINE + "\nEDITED = True\n")  # uncommitted edit
        rels = {str(f.relative_to(toy)) for f in project_files(toy)}
        assert "toy/extra.py" in rels and "toy/engine.py" in rels
        assert not any(r.startswith(".venv") or r.endswith(".log") for r in rels)
        sb = Sandbox(toy)
        try:
            assert "EDITED = True" in (sb.dir / "toy" / "engine.py").read_text()
            assert not (sb.dir / ".git").exists()
        finally:
            sb.close()


# ---------------------------------------------------------------------------------------
# the declaration file and the CLI
# ---------------------------------------------------------------------------------------

DECL = textwrap.dedent('''
    from mutgate import Mutation
    TESTS = ["tests"]
    PATHS = ["."]
    MUTATIONS = [
        Mutation("cut-strict", "toy/engine.py", old="if x >= s]", new="if x > s]", fires=("TestCut",)),
        Mutation("comment", "toy/engine.py", old="# the stronger birth survives", new="# x", invisible=True),
    ]
''')


class TestDeclarationAndCli:
    def test_load_reads_mutations_tests_paths_and_root(self, toy):
        (toy / "tests" / "mutations.py").write_text(DECL)
        d = load(toy / "tests" / "mutations.py")
        assert [m.name for m in d.mutations] == ["cut-strict", "comment"]
        assert d.root == toy.resolve() and d.tests == ("tests",) and d.paths == (".",)

    def test_root_is_relative_to_the_declaration_file(self, toy):
        (toy / "tests" / "m.py").write_text(DECL + 'ROOT = ".."\n')
        assert load(toy / "tests" / "m.py").root == toy.resolve()

    def test_load_refuses_duplicates_and_non_mutations(self, toy):
        (toy / "tests" / "bad.py").write_text(DECL.replace('"comment"', '"cut-strict"'))
        with pytest.raises(ValueError, match="duplicate"):
            load(toy / "tests" / "bad.py")
        (toy / "tests" / "bad2.py").write_text("MUTATIONS = [1]\n")
        with pytest.raises(ValueError, match="not a Mutation"):
            load(toy / "tests" / "bad2.py")

    def test_mutation_validation(self):
        with pytest.raises(ValueError, match="identical"):
            Mutation("x", "f", old="a", new="a", fires=("t",))
        with pytest.raises(ValueError, match="invisible"):
            Mutation("x", "f", old="a", new="b", fires=("t",), invisible=True)
        with pytest.raises(ValueError, match="name the tests"):
            Mutation("x", "f", old="a", new="b")

    def test_cli_run_and_list(self, toy):
        (toy / "tests" / "mutations.py").write_text(DECL)
        env = {"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        import os
        env = {**os.environ, **env}
        out = subprocess.run([sys.executable, "-m", "mutgate", "list", str(toy / "tests" / "mutations.py")],
                             capture_output=True, text=True, env=env)
        assert out.returncode == 0 and "cut-strict" in out.stdout and "invisible" in out.stdout
        out = subprocess.run([sys.executable, "-m", "mutgate", "run", str(toy / "tests" / "mutations.py"), "--markdown"],
                             capture_output=True, text=True, env=env)
        assert out.returncode == 0, out.stdout + out.stderr
        assert "| cut-strict |" in out.stdout and "| OK |" in out.stdout
        # a contract that fails makes the exit code say so
        bad = DECL.replace('fires=("TestCut",)', 'fires=("TestElderRule",)')
        (toy / "tests" / "mutations.py").write_text(bad)
        out = subprocess.run([sys.executable, "-m", "mutgate", "run", str(toy / "tests" / "mutations.py")],
                             capture_output=True, text=True, env=env)
        assert out.returncode == 1 and "DECORATION" in out.stdout
        # usage errors: a missing interpreter, a typo in --only
        out = subprocess.run([sys.executable, "-m", "mutgate", "run", str(toy / "tests" / "mutations.py"),
                              "--python", "/no/such/python"], capture_output=True, text=True, env=env)
        assert out.returncode == 2 and "not found" in out.stderr
        out = subprocess.run([sys.executable, "-m", "mutgate", "run", str(toy / "tests" / "mutations.py"),
                              "--only", "nope"], capture_output=True, text=True, env=env)
        assert out.returncode == 2 and "names no declared mutation" in out.stderr
