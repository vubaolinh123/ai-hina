# Packages

Shared packages are introduced only with an owning module and explicit language manifest.

- Python packages use `pyproject.toml` and `src/<package>/`.
- TypeScript packages use `package.json`.
- Generated Python/TypeScript contract packages are published separately.
- Generic unowned `utils` packages are not allowed.
