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

Historical authoring and bootstrap tools are retained by purpose under:

```text
unstable/tools/dix_cli/
unstable/tools/application_authoring/
unstable/tools/composition_authoring/
unstable/tools/runtime_bootstrap/
```

They are reference implementations, are not installed as DIX entry points, and may rely on
development dependencies or contracts replaced by the stable core.

Historical tests that exercise unstable modules live under `unstable/tests`. They are preserved as
reference and migration evidence but are not part of the supported core regression suite.
