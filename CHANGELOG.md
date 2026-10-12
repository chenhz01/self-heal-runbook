# Changelog

Format inspired by Keep a Changelog; versions are SemVer.

## [0.1.2] - 2026-10-12

### Fixed
- `plan`: the planner emitted every ready step each round regardless of phase, so a requires-free rollback step could overtake pending diagnostics/remediation steps. It now emits only the earliest-phase candidates per round, preserving topological order within phases (plan for the canonical 5-step runbook is again d1, d2, r1, v1, b1).
- `validate`/`plan`: non-list `requires`/`verifies` values (e.g. an int) previously crashed with `TypeError` inside the closed-loop/graph pass; a `_as_list` guard now leaves them to the existing per-field validators, which report the proper "must be a list" error.

### Tests
- self_test X36 fixture corrected: it overrode `diagnostics` and dropped step `d2`, but the base remediation step still required `d2`, producing an unrelated unknown-id error; the override now replaces `remediation` too. Test-side fix only — no core behavior change for that case. Final: `SUMMARY: PASS 40/40`, rc=0.

## [0.1.1] - 2026-10-11

### Changed
- Round-2 content iteration: self-test suite expanded from 40 to 50 checks (+25% on the coverage dimension) — added a 100-step deep-chain plan case, self-require cycle, duplicate trigger patterns, `runbook_version` type checks, and deterministic plan re-computation assertions.

## [0.1.0] - 2026-10-11

### Added
- Runbook JSON schema: triggers (4 types), diagnostics / remediation / verification / rollback phases.
- Validator: unique ids, phase completeness, requires-DAG acyclicity, closed-loop rule, max_attempts/timeout_s typing.
- Deterministic topological `plan` and zero-side-effect `dry_run`.
- CLI (argparse): validate / plan; JSON plan output.
- Self-test suite: 40 checks (functional / exception / extreme edges).
- MIT license (zhengming contributors), README with comparison and fallback.
