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

    def test_sandbox_shadows_an_installed_copy(self, toy):
        """PYTHONPATH puts the sandbox first, so the mutated copy is the one imported even
        if the same package is importable from elsewhere."""
        rc, failed, _ = run_pytest(Sandbox(toy).dir, ("tests",), sys.executable, (".",))
        assert rc == 0 and failed == []


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
