# Releasing

The version is static in three files and they must agree:

- `pyproject.toml` → `[project] version`
- `src/mutgate/__init__.py` → `__version__`
- `CITATION.cff` → `version` (and `date-released`)

## Cutting a release

1. Bump those three, and move the `CHANGELOG.md` `Unreleased` section under the new
   version heading.
2. Commit, then tag and push:

   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```

3. Publish a GitHub Release for the tag. That triggers `.github/workflows/publish-pypi.yml`,
   which refuses to build unless the tag matches the `pyproject.toml` version, runs
   `twine check`, and uploads to PyPI by trusted publishing.

```bash
gh release create vX.Y.Z --title "vX.Y.Z" --notes-file <(sed -n '/^## X.Y.Z/,/^## /p' CHANGELOG.md)
```

## Before the first publish (one-time, web console) — DONE 2026-09-07

All four are in place (the first attempt failed with `invalid-publisher` because the PyPI
form's Add button had not been pressed; `workflow_dispatch --ref v0.1.0` re-ran the publish
against the existing tag). Kept for the record:

- pypi.org → Publishing → add a **pending** trusted publisher: project `mutgate`, owner
  `JimGalasyn`, repository `mutgate`, workflow `publish-pypi.yml`, environment `pypi`.
- GitHub → Settings → Environments → create `pypi`.
- Zenodo → GitHub integration → enable `JimGalasyn/mutgate` before the first release, so
  the first release mints the concept DOI; then record it in `CITATION.cff`.

The `publish-release` skill in the Claude Code setup walks these steps for the sibling
repositories (rafkit, run-farm, jax-morpho, jax-solitons, proc-warden); this one is the same.

## After the first release: the DOIs

Zenodo minted the concept DOI 10.5281/zenodo.22649033 (always the latest version) and the
version DOI 10.5281/zenodo.22649034 for v0.1.0; both are in `CITATION.cff`, the concept DOI
is the README badge. After every release, add the new version DOI to `CITATION.cff` and write
its CHANGELOG line in the same commit — that commit is the first of the next release.

## Verifying a release

```bash
python -m venv /tmp/relcheck && /tmp/relcheck/bin/pip install --no-cache-dir "mutgate==X.Y.Z"
/tmp/relcheck/bin/mutgate run tests/mutations.py     # from any project with a declaration
```

The install proves the name resolves; running a declaration proves the package works. A
green publish workflow is not evidence of either.
