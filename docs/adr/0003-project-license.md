# ADR-0003: Project source license

- Status: accepted
- Date: 2026-07-23
- Owners: project owner

## Decision

New Hina AI source code uses the MIT License.

Third-party code, model weights, datasets, voices, motions and avatar assets retain separate licenses and provenance. MIT at the repository root does not relicense those artifacts.

## Consequences

- Permissive use and redistribution for new project code.
- Required MIT notice must ship.
- Dependency, weight, data and asset compatibility remains a release gate.
