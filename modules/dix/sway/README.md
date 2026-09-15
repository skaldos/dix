# `dix/sway`

`dix/sway` is an optional first-party module for explicit Sway integration. The concrete `i3ipc`
dependency remains inside the IPC composition; connection, tree and container objects do not cross
the module boundary.

## State ownership

The current group-navigation slice deliberately has three different state surfaces:

1. **Private group state** — the Group composition owns a JSON document containing complete ordered
   memberships and `active_group`. Its path is mandatory through
   `DIX_SWAY_GROUP_STATE_FILE`. Missing means an empty initial model; an existing empty, corrupt or
   semantically invalid file is an error.
2. **ROBA coordination** — the ephemeral `sway` context contains only the ordered group names and
   active group. It never contains Sway `con_id` memberships. Stopping ROBA destroys this
   coordination; restarting ROBA does not automatically load the private JSON.
3. **Active-member projection** — `DIX_SWAY_ACTIVE_MEMBERS_FILE` names a narrow text artifact read
   by hot navigation. Its canonical form is one newline-terminated line of unique positive decimal
   IDs separated by one ASCII space, for example `32 392\n`; an empty membership is exactly `\n`.

Group operations own private mutations. `create` and a changed `select` publish coordination to
ROBA. Selection always republishes the active text artifact, while changed `add/remove` republishes
only for the active group. Publication filters IDs absent from one current Sway live-tree read but
does not delete stale IDs from private JSON.

For the active text artifact, missing and canonical empty both select one native Sway navigation
step. Corrupt/noncanonical input fails before an IPC read. A nonempty artifact is checked against
current liveness again because a window may close after publication.

## Management CLI

The generated Typer launcher is the explicit management surface:

```text
dix-sway runtime start|status|stop
dix-sway group create|add|remove|show|list|select|current
dix-sway navigation select|current|left|right|up|down
```

It loads the broad DIX/ROBA management graph. Example:

```sh
export DIX_SWAY_GROUP_STATE_FILE="$XDG_RUNTIME_DIR/dix-sway/groups.json"
export DIX_SWAY_ACTIVE_MEMBERS_FILE="$XDG_RUNTIME_DIR/dix-sway/active-members"
dix-sway runtime start
dix-sway group create --group work
dix-sway group add --group work
DIX_SWAY_GROUP_SELECT_GROUP=work dix-sway group select
```

## Narrow keybinding entry

`examples/launchers/dix_sway_navigation.py` is a separate single-direction hot-path artifact. It
loads the productive projection parser, IPC adapter, native step and group loop, but not ROBA,
HTTPX, Pydantic or Typer:

```sh
DIX_SWAY_ACTIVE_MEMBERS_FILE="$XDG_RUNTIME_DIR/dix-sway/active-members" \
  python examples/launchers/dix_sway_navigation.py right
```

A manual Sway binding can call the same command with `left`, `right`, `up` or `down`. This module
does not edit Sway configuration or install keybindings. Group navigation may visibly pass through
intermediate windows because Sway remains navigation authority. There is no event daemon, cache,
layout restoration, `next/prev` abstraction or performance promise in this slice. Deterministic
checks fake only the `i3ipc` boundary; real perceived latency and human acceptance remain separate
manual work.
