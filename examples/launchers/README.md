# Compose applications into a CLI

The `my_cli` example combines two independent application modules without changing either target:

```text
acme/cli_base/base
acme/cli_test/test
```

The assembly application lives in `examples/modules/acme/my_cli`. Its `app.toml` declares both
applications and the first-party `dix/cli/typer` composition as ordinary dependencies. Its runtime
contains only the local aliases and one `main(argv) -> int` wrapper.

Install DIX with the optional Typer adapter and build the launcher:

```bash
uv sync --extra cli
uv run --extra cli python -m dix.bootstrap build \
  examples/launchers/my_cli.toml \
  --output /tmp/my_cli
```

Use every exposed target function beneath its explicit application alias:

```bash
uv run --extra cli python /tmp/my_cli --help
uv run --extra cli python /tmp/my_cli base render --value test --count 2 --upper true
uv run --extra cli python /tmp/my_cli test hello --name Skaldos
uv run --extra cli python /tmp/my_cli test hello_world
```

Names are preserved exactly. All function parameters are named options. The help output shows the
deterministic environment variable for every option, for example:

```bash
MY_CLI_TEST_HELLO_NAME=Environment uv run --extra cli python /tmp/my_cli test hello
```

## Select or rename functions

Adding an application to `targets` intentionally exposes all functions declared by that
application. To select functions, rename them, change their signature, or add CLI-specific policy,
compose a small wrapper application and expose only its desired local methods. Do not add an
independent CLI allowlist.

That wrapper is a normal DIX application and remains reusable by other applications and adapters.
