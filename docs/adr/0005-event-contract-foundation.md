# ADR-0005: Event contract foundation

- Status: accepted
- Date: 2026-07-24
- Owners: primary orchestrator, architecture owner
- Scope: M01-S1

## Context

Every event that crosses a Hina AI process boundary needs one strict,
versioned, language-neutral contract. Python and TypeScript consumers must
reject the same malformed inputs, preserve Vietnamese and mixed Unicode
exactly, and detect generated-code drift. Binary media must not inflate or
weaken the JSON control channel.

The master plan defines the EventEnvelope v1 field names and semantics.
Wave A compared Ajv, Python jsonschema, JSON Schema 2020-12, CloudEvents,
json-schema-to-typescript and datamodel-code-generator. The two generation
libraries add unnecessary surface for this narrow slice, while CloudEvents is
useful as design research but is not the Hina wire contract.

## Decision

### Source of truth and catalog

- JSON Schema draft 2020-12 under `packages/contracts/schemas/v1/` is the sole
  wire-contract source of truth.
- Schema identifiers use the stable namespace
  `https://ai-hina.local/contracts/v1/`.
- `packages/contracts/catalog.v1.json` is the only event registry. An event
  schema that is not registered there is unknown and must fail closed.
- M01-S1 registers only `hina.contract.echo.v1`, a compatibility-test event
  with no product behavior or side effect.
- Registered v1 schemas are immutable. A breaking payload change creates a new
  event major version; a breaking envelope change creates EventEnvelope v2.

### EventEnvelope v1

Wire field names follow the master plan exactly:

| Field | Contract |
| --- | --- |
| `schemaVersion` | literal `"1.0"` |
| `eventId` | canonical lowercase RFC 4122 UUID |
| `type` | registered name matching `^hina\.[a-z0-9_.]+\.v[1-9][0-9]*$` |
| `scope` | `global`, `session`, or `turn` |
| `sessionId` | UUID or null; required for session and turn scopes |
| `turnId` | UUID or null; required only for turn scope |
| `correlationId` | canonical lowercase RFC 4122 UUID |
| `causationId` | canonical lowercase RFC 4122 UUID or null |
| `source` | 1-128 printable non-control Unicode code points |
| `trustLevel` | `owner`, `trusted_local`, `authenticated`, `public`, or `untrusted` |
| `occurredAt` | UTC RFC3339 ending in `Z`, with zero to six fractional digits |
| `expiresAt` | the same timestamp form or null |
| `deadline` | the same timestamp form or null |
| `idempotencyKey` | 1-128 characters or null |
| `streamId` | 1-128 characters or null |
| `sequence` | integer from 0 through JavaScript's safe maximum, or null |
| `media` | zero to 32 strict `MediaReference` metadata objects |
| `payload` | strict object selected by the registered event type |

All envelope, media and payload objects are closed. Unknown properties,
unknown event types, wrong types, invalid scope identifiers and malformed
identifiers are rejected.

`MediaReference` contains only `mediaId`, `kind`, `mimeType`, `byteLength`,
`sha256`, and `transportCorrelationId`. Hashes are lowercase SHA-256 hex,
lengths are bounded by JavaScript's safe integer maximum, and MIME values use a
conservative bounded token pattern. URI, filesystem path, data URI, raw byte,
and base64 fields are not allowed.

### Boundary validation

- Reject raw UTF-8 input larger than 1,048,576 bytes before JSON parsing.
- Parse JSON with no coercion, defaults, unknown-field removal, or mutation.
- Validate the parsed value against the catalog-selected draft 2020-12 schema.
- Re-serialize as compact UTF-8 JSON with non-ASCII characters preserved and
  reject the canonical result if it exceeds the same byte limit.
- Return one stable machine-readable failure code from the M01-S1 test matrix.
  Human-readable validator wording is diagnostic only and is not an API.
- Python uses `jsonschema` 4.x. TypeScript uses Ajv 8's 2020 validator with
  strict mode and without coercion, defaults, or unknown-property removal.
  UUID and timestamp rules use explicit schema patterns so both runtimes agree
  without optional format plugins.

### Deterministic projections

A project-owned Python generator reads the reviewed catalog and emits:

- Python typed model projections and catalog constants; and
- TypeScript interfaces, literal unions and catalog constants.

It traverses sorted inputs, writes UTF-8 with LF endings, emits no timestamps
or machine paths, and includes a digest of its schema inputs. `--check` renders
in memory and fails if a tracked output differs. Generated projections improve
developer ergonomics; runtime trust still comes only from JSON Schema
validation.

### Compatibility policy

`packages/contracts/compatibility-policy.v1.json` records the current catalog
major/minor, supported previous versions, disposition and migration
requirement. For the initial `1.0` catalog, no previous version exists.
Starting with the next catalog release, current and n-1 golden fixtures must
remain in both runtime suites. A rejected previous version must be an explicit
machine-readable policy decision, never an accidental validator outcome.

## Consequences

The first slice has one small, test-only event but exercises the complete
schema-to-generated-model-to-runtime-validation path. Later M01 slices can add
new registered event schemas without changing the envelope. Pydantic or Zod
may be added later as ergonomic projections, but they may not replace the JSON
Schema boundary validator or become a second wire source of truth.

Hina does not claim CloudEvents conformance. No upstream production source is
copied in M01-S1; the reviewed projects inform API and validation choices only.

## Verification

- Both runtimes execute the golden, negative, size, identifier, Unicode and
  inline-media cases listed in `docs/modules/M01-S1-test-matrix.json`.
- Python-to-TypeScript-to-Python and the reverse preserve the canonical
  envelope with zero data loss.
- Generation drift is detected.
- The deterministic suite passes 20 consecutive runs on one frozen commit.
- Local validation p95 is no greater than 5 ms for the benchmark fixture.
