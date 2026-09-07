# Changelog

## Unreleased

Review of the first commit by a second session, everything below reproduced on the toy
project before it was fixed:

- **A symlinked TMPDIR crashed every mutation** ("escapes the sandbox"): the sandbox
  directory is now resolved before the containment check. macOS keeps `/var` behind a
  symlink, so this was every macOS user.
- **A suppressed pytest summary was a silent false pass.** `pytest` exit 1 with no
  failure readable is now `ERROR`, never `OK`; the same at baseline.
- **`fires="Name"` (a bare string) was a silent false pass**: it became one-letter
  fragments matching every node id. Strings and empty fragments are refused.
- **A typo in `--only`, or an emptied `MUTATIONS`, exited 0.** Both are usage errors (2).
- Node ids containing " - " inside a parametrisation are no longer truncated; `--timeout`
  makes a hanging suite an `ERROR`; a missing `--python` is a usage error; `ROOT` is
  relative to the declaration file; the `git ls-files` sandbox and real PYTHONPATH
  shadowing are now tested; the `Framework :: Pytest` classifier (for plugins) is dropped.

## 0.1.0 — 2026-09-07

First release. `Mutation` with `fires` / `may_fire` / `invisible` / `count`; the sandbox
copy via `git ls-files`; verdicts OK, DECORATION, OVERREACH, VISIBLE, NOT_APPLIED, ERROR;
a red baseline aborts; `mutgate run` and `mutgate list`, with `--markdown` for build
records. Extracted from three hand-rolled mutation harnesses written in one week across
the Morphospace and abiogenesis repositories, after the third one found a duplicated
convention by firing on the wrong kind of assertion.
