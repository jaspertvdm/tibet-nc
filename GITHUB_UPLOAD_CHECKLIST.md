# GitHub Upload Checklist

This package is close to GitHub-ready, but a few items should be handled before
tagging a fresh PyPI release.

## Ready

- README refreshed for current positioning.
- MIT license file added.
- Security policy added.
- Changelog added.
- Contributing guide added.
- GitHub Actions CI added.
- Version/status metadata aligned to `0.1.0a1` / alpha.
- Package lives under `/srv/jtel-stack/packages/tibet-nc`.
- Existing package metadata points at `https://github.com/humotica/tibet-nc`.

## Must Fix Before PyPI Re-Publish

1. Sync deployed daemon improvements back into package source.

   The live daemon at `/srv/jtel-stack/tibet-nc/tibet_nc_daemon.py` differs from
   `packages/tibet-nc/src/tibet_nc/daemon.py`:

   - restricted PATH includes `/usr/local/tibet-nc-bin`
   - slow commands get a longer output window
   - progress output is collapsed before Matrix response

2. Verify or add the CLI entrypoint.

   `pyproject.toml` exposes:

   ```toml
   tibet-nc = "tibet_nc.cli:main"
   ```

   but this checkout does not currently contain `src/tibet_nc/cli.py`.

3. Run tests in an installed environment.

   Direct `python3 -m pytest -q` from the package directory failed because
   `tibet_nc` was not importable without installing the package/editable source.
   With `PYTHONPATH=src`, the import advances to the expected missing local
   dependency `matrix-nio`; CI installs dependencies before running tests.

4. Rebuild in an environment with build dependencies available.

   `python3 -m build --sdist --wheel` could not fetch `hatchling` from inside
   the restricted sandbox.

## Suggested GitHub Commit Shape

```text
feat(tibet-nc): refresh maintained alpha package docs

- document Matrix E2EE remote shell model
- document human override vs cmail/capsule execution boundary
- add license, security policy, changelog, and upload checklist
- capture package/deployed daemon drift before republish
```
