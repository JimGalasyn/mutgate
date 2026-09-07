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

## Before the first publish (one-time, web console)

- pypi.org → Publishing → add a **pending** trusted publisher: project `mutgate`, owner
  `JimGalasyn`, repository `mutgate`, workflow `publish-pypi.yml`, environment `pypi`.
- GitHub → Settings → Environments → create `pypi`.
- Zenodo → GitHub integration → enable `JimGalasyn/mutgate` before the first release, so
  the first release mints the concept DOI; then record it in `CITATION.cff`.

The `publish-release` skill in the Claude Code setup walks these steps for the sibling
repositories (rafkit, run-farm, jax-morpho, jax-solitons, proc-warden); this one is the same.
