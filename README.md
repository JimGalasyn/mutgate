# mutgate

**Named mutations as contracts on a test suite.** Each mutation is a deliberate, named
change to the code under test, together with the list of tests it must turn red — or the
statement that it must turn nothing red. `mutgate` applies each one in a sandbox copy, runs
the suite, and judges the contract.

```python
# tests/mutations.py
from mutgate import Mutation

MUTATIONS = [
    Mutation("keep-larger", file="pkg/engine.py",
             old="if (birth[a], -a) >= (birth[b], -b):",
             new="if size[a] >= size[b]:",
             fires=("TestElderRule",)),
    Mutation("skip-absolute-floor", file="pkg/engine.py",
             old="if u.birth < abs_floor:", new="if False:",
             fires=("TestAbsoluteFloor",)),
    Mutation("tie-to-higher-index", file="pkg/engine.py",
             old="(birth[a], -a) >= (birth[b], -b)",
             new="(birth[a], a) >= (birth[b], b)",
             invisible=True),   # an invariance: the measurement must not depend on it
]
```

```
$ mutgate run tests/mutations.py
mutation             verdict      fired  expected
keep-larger          OK               3  TestElderRule
skip-absolute-floor  DECORATION       0  TestAbsoluteFloor
                       did not fire: TestAbsoluteFloor
tie-to-higher-index  OK               0  nothing

2 OK, 1 DECORATION
```

## Why

A green test suite guards only the defects that shaped it. The usual way to find out
whether a test is load-bearing is to break the code on purpose and see whether the test
notices — and in practice that is done by hand, in a scratch copy, with `sed`, once, and then
the result is written into a design note as prose. `mutgate` makes that a checked artefact:

- **the mutation is named and exact.** `old` must occur exactly `count` times in the file,
  or the verdict is `NOT_APPLIED`. A mutation that silently does not land looks identical
  to a working guard; this is the trap that motivated the tool.
- **the contract says which tests must fire.** A named test that does not fire is a
  `DECORATION` — a guard that would not go red.
- **a test outside the contract firing is a finding, not noise.** `OVERREACH` means the
  mutation reaches further than its author believed. When a convention (a tie-breaking rule,
  a sign, an ordering) is changed and tests that should only *relabel* things fail on
  *values*, the convention exists in two places that have drifted apart.
- **an invariance is a mutation that must fire nothing.** `invisible=True` pins that the
  suite passes unchanged under the alternative convention; if it does not, the verdict is
  `VISIBLE`.
- **the working tree is never touched.** Each mutation is applied and restored in a
  temporary copy (`git ls-files`, so uncommitted work is included and the venv is not), and
  the copy is put first on `PYTHONPATH` so an editable install elsewhere cannot shadow it.
- **a red baseline aborts.** Mutations mean nothing on a suite that already fails.

## What it is not

It is not automatic mutation testing. Tools like `mutmut` and `cosmic-ray` generate operator
mutations at random and report a kill rate; that answers "how thorough is this suite?".
`mutgate` answers a narrower question that random mutation cannot: *does this specific guard
fire under the specific defect it was written for, and only that?* The two are complementary.

## Declaration file

A Python file (conventionally `tests/mutations.py`) defining:

| name | required | meaning |
|---|---|---|
| `MUTATIONS` | yes | a sequence of `Mutation` |
| `TESTS` | no | pytest targets; default: the declaration file's own directory |
| `PATHS` | no | `PYTHONPATH` entries relative to the root; default `("src", ".")` |
| `ROOT` | no | project root; default: the nearest ancestor with `pyproject.toml` or `.git` |
| `PYTHON` | no | interpreter to run pytest with; default: the one running `mutgate` |

`Mutation(name, file, old, new, fires=(), may_fire=(), invisible=False, count=1, note="")`.
Entries in `fires` and `may_fire` are substrings of pytest node ids, so `"TestElderRule"`,
`"test_engine.py::TestElderRule"` and `"test_tie_goes_to_lower_index"` all work.

## CLI

```
mutgate run tests/mutations.py [--tests T ...] [--only NAME ...] [--python PY]
                               [--pytest-arg ARG] [--markdown] [--keep] [-x] [-v]
mutgate list tests/mutations.py
```

`--markdown` prints a table meant to be pasted into a design note's build record. Exit code
0 when every contract holds, 1 when a verdict is not `OK`, 2 when the baseline is red or the
file cannot be loaded.

## In CI

```yaml
- run: pip install mutgate
- run: mutgate run tests/mutations.py
```

Each mutation runs the named tests once, so the cost is the suite's cost times the number of
mutations; point `TESTS` at the module the mutations concern.

## Install

```
pip install mutgate
```

No runtime dependencies. Python 3.10+. MIT.
