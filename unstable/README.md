# DIX unstable area

This directory contains real development candidates whose architecture, contracts, packaging, or
lifecycle are not part of the supported DIX surface yet.

Rules:

- `src/dix` must never import from `unstable`.
- promoted modules must not depend on `unstable`.
- unstable modules are loaded only through explicit development roots.
- unstable content is excluded from release artifacts.
- permanent examples belong under `examples`.
- synthetic test fixtures belong under `tests/fixtures`.
- promotion is an explicit review decision, not an automatic release action.
