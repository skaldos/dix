# Local state composition pressure application

This example composes the optional `dix/state` module without extending the DIX core:

- `base_config` transparently exports `get` and `set` from one `dix/state/local` instance,
- `reactive_config` wraps `set` and owns its reaction policy,
- `combined` uses only the explicitly exposed functions of both direct dependencies,
- the `state` application drives the graph without accessing model or runtime internals.

Each owner keeps one `state_model.toml`. Multiple states are ordinary composition instances, not a
second registry inside `dix/state/local`.

Run the source pressure path from the repository root:

```bash
uv run --extra state python examples/run_state_demo.py
```
