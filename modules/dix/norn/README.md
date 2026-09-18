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

`dix/norn/knot` loads one owner-local ordered Knot model. A Knot model binds known input fields to
flat local Strand and handler names. During staged graph construction, each Strand name resolves
to the same-named composition dependency of the immediate owner and its exposed synchronous
`execute`; each handler name resolves to an exposed synchronous function of that owner.
`knot.execute(value)` therefore needs no second callable table. It ignores unknown input fields and
invokes only present declared fields in model order. Root use, missing bindings, private methods
and asynchronous targets fail before the graph becomes visible. This is an immediate-owner
capability, not a global registry or graph lookup.
