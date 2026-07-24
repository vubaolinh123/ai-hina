# Packages

Shared packages are introduced only with an owning module and explicit language manifest.

- Python packages use `pyproject.toml` and `src/<package>/`.
- TypeScript packages use `package.json`.
- Generated Python/TypeScript contract packages are published separately.
- Generic unowned `utils` packages are not allowed.

Owned packages:

- `contracts`: M01 wire contracts and generated projections.
- `testkit`: deterministic M01 test providers.
- `safety-policy`: M02 capability policy, operator state and audit authority.
