# `dix/sway`

`dix/sway` is an optional first-party module for small, explicit Sway integrations. Its IPC
composition exposes detached container primitives while keeping `i3ipc` objects private:

```text
focused_con_id() -> int
focus_direction(left | right | up | down)
focus_con_id(con_id)
live_con_ids() -> list[int]
```

The concrete `i3ipc` dependency is isolated inside the IPC composition. DIX consumers do not
receive connection, tree, container, or other library objects. Group management is a separate
composition and persists only the explicitly managed, ephemeral IDs in its selected state
backend.

The generated `dix-sway` launcher provides three explicit command groups:

```text
dix-sway runtime start|status|stop
dix-sway group create|add|remove|show|list|select|current
dix-sway navigation select|current|left|right|up|down
```

Navigation defaults to one native Sway focus step. Selecting `group` repeats native steps until a
live member of the active group is reached:

```sh
dix-sway group create --group work
dix-sway group add --group work
DIX_SWAY_GROUP_SELECT_GROUP=work dix-sway group select
DIX_SWAY_NAVIGATION_SELECT_NODE_SELECTOR=group dix-sway navigation select
dix-sway navigation right
```

The state is intentionally ephemeral and belongs to the running Sway ROBA context. Stale window
IDs are reported and ignored for one navigation call, but never deleted implicitly. Group
navigation may visibly focus intermediate windows because Sway itself remains the navigation
authority. There is no event daemon, cache, keybinding management, layout restoration, or
`next`/`prev` abstraction in this slice.

Install the optional dependency with the `sway` extra. A real Sway probe requires a visible,
reachable `SWAYSOCK`; deterministic tests replace the connection only at this adapter boundary.
