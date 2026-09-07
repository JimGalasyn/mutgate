# Changelog

## Unreleased

Planned: a `control=` field naming an invariance's firing sibling, with a warning on an
unpaired invariance, once a real declaration carries more than a handful of them.

## 0.1.0 — 2026-09-07

First release. `Mutation` with `fires` / `may_fire` / `invisible` / `count`; the sandbox
copy via `git ls-files`; verdicts OK, DECORATION, OVERREACH, VISIBLE, NOT_APPLIED, ERROR;
a red baseline aborts; `mutgate run` and `mutgate list`, with `--markdown` for build
records. Extracted from three hand-rolled mutation harnesses written in one week across
the Morphospace and abiogenesis repositories, after the third one found a duplicated
convention by firing on the wrong kind of assertion.

### Fixed before release, on a second session's review of the first commit

- **A symlinked TMPDIR crashed every mutation** ("escapes the sandbox"): the sandbox
  directory is now resolved before the containment check. macOS keeps `/var` behind a
  symlink, so this was every macOS user.
- **A suppressed pytest summary was a silent false pass.** `pytest` exit 1 with no
  failure readable is now `ERROR`, never `OK`; the same at baseline.
- **`fires="Name"` (a bare string) was a silent false pass**: it became one-letter
  fragments matching every node id. Strings and empty fragments are refused.
- **A typo in `--only`, or an emptied `MUTATIONS`, exited 0.** Both are usage errors (2).
- **A project whose config stops at the first failure (`-x`, `--maxfail=N`) truncated the
  fired set with a consistent-looking exit**, so an OVERREACH read OK. mutgate now owns
  `--maxfail=0` after every user argument, and pytest's own "stopping after N failures"
  line (a conftest can still force it) makes the run `ERROR`. Second review round.
- **An interrupted run with a partial fired set read as a verdict** (a conftest setting
  `session.shouldstop` after the first failure: exit 2, one failure parsed). Only exit codes
  0 and 1 now count as a completed run; anything else is `ERROR` whatever parsed. Third
  review round.
- Node ids containing " - " inside a parametrisation are no longer truncated; `--timeout`
  makes a hanging suite an `ERROR`; a missing `--python` is a usage error; `ROOT` is
  relative to the declaration file; the `git ls-files` sandbox and real PYTHONPATH
  shadowing are now tested; the `Framework :: Pytest` classifier (for plugins) is dropped.
