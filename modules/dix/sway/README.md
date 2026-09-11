# `dix/sway`

`dix/sway` is an optional first-party module for small, explicit Sway integrations. Its first
composition deliberately exposes only the focused container ID:

```text
focused_con_id() -> int
```

The concrete `i3ipc` dependency is isolated inside the IPC composition. DIX consumers do not
receive connection, tree, container, or other library objects. Group management is a separate
composition and persists only the explicitly managed, ephemeral IDs in its selected state
backend.

Install the optional dependency with the `sway` extra. A real Sway probe requires a visible,
reachable `SWAYSOCK`; deterministic tests replace the connection only at this adapter boundary.
