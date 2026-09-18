# DIX Norn

`dix/norn` contains optional, composition-local value boundaries. It does not participate in the
core call path and does not make existing compositions into strands.

The first strand boundary loads one owner-local `strand.toml` and, for model boundaries, a small
flat model specification. Specifications are resolved relative to the creating composition's
configuration base and cannot escape it.

`dix/norn/strand` exposes exactly `process_input(value)` and `process_output(value)`. Atomic
boundaries use DIX elements; flat model boundaries use DIX datamodels and return detached native
dictionaries. Norn owns structural compatibility only. A composing domain strand owns its
`execute` operation and every domain error.
