# Contributing

`tibet-nc` is a security-sensitive operator tool. Keep changes small,
reviewable, and explicit about the trust boundary they affect.

## Local Checks

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q
```

## Review Expectations

- Do not relax blocked command patterns without a security note.
- Do not add privileged execution paths to ordinary `$` commands.
- Keep high-impact actions behind signed cmail/capsule approval.
- Do not commit Matrix tokens, room secrets, or deployment `.env` files.
- Document deployment-specific behavior separately from package defaults.

## Release Notes

Before publishing a new PyPI version:

1. sync deployed daemon changes into package source
2. verify CLI entrypoint
3. run tests in a clean virtualenv
4. build sdist and wheel
5. publish from a clean tag
