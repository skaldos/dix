# Declarative CLI application pressure test

This trusted module keeps terminal concerns out of the business application:

- `tool` exposes only the transport-independent `render` function.
- `cli` supplies the explicit `tool.render` allowlist and delegates parsing to
  `dix/core/cli/typer_cli`.
- `cli.toml` declares command paths, named options, help, and environment sources.
- `models/render_input.toml` defines the DIX datamodel used after Typer conversion.

The module does not load itself, create global process state, or expose HTTP, IPC, or RPC. See
`examples/run_cli_demo.py` for the deliberately visible load/create/call/destroy/unload sequence.
