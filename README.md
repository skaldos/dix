# dix

Declarative Interface eXecutor.

`dix` is currently an architecture-stage Python toolkit for building isolated runtime graphs:

```text
explicit module load
-> composition graph
-> application graph
-> explicitly exposed local functions
-> direct Python calls
```

The core does not define a daemon, transport, wire contract, validation policy, user interface, or
authorization model.

## Current core

- **Element** processes one native Python value through an explicit technical handler chain.
- **Datamodel** processes mappings against locally registered field schemas and reports results.
- **Composition** combines components and other compositions in an isolated instance graph.
- **Application** combines compositions and applications into a callable local boundary.
- **Module** explicitly inspects, stages, publishes, and unloads composition/application bundles.

Composition and application specifications are authoritative only for graph assembly and function
exposure. Real runtime methods remain authoritative for their Python signatures. DIX does not
implicitly validate, normalize, project, or serialize function arguments and results.

Python loaded from a module executes in-process. Atomic registry publication cannot undo import
side effects and is not a security sandbox.

## Repository maturity boundary

```text
src/dix/core/            current core implementation
src/dix/bootstrap/       minimal build-time launcher seed
tests/                   stable core regression
tests/fixtures/modules/  synthetic test modules; never packaged
unstable/modules/        preserved module experiments
unstable/tools/          pressure and authoring experiments
unstable/tests/          historical evidence for replaced surfaces
```

Stable source must never import from `unstable`. The unstable tree is excluded from wheels.

## Module layout

```text
<module>/
  compositions/<local-id>/{composition.toml,runtime.py}
  apps/<local-id>/{app.toml,runtime.py}
```

A module contains at least one composition or application. There is no `module.toml`, automatic
startup, trusted-root policy, model registry, or contract registry in the core.

### Composition function

```toml
[composition]
id = "echo"

[functions.echo]
description = "Echo one local value."
```

```python
class Runtime:
    def __init__(self, *, context, config):
        self.context = context
        self.config = config

    def echo(self, value):
        return value
```

Only methods declared under `[functions]` are exposed. The function receives and returns native
Python values without automatic contract processing.

### Explicit application wrapper

```toml
[app]
id = "echo"

[compositions.worker]
use = "acme/example/echo"

[functions.echo]
description = "Expose the worker locally."
export = "worker.echo"
```

Dependency functions are never exported implicitly. The application implements an explicit local
wrapper, so it owns adaptation and policy.

## Seed launcher

`python -m dix.bootstrap build` renders a normal Python program for one fixed application function.
The generated launcher creates its own registry, loads only declared modules, creates one app,
calls its function, and tears the graph down. Its `python_cli` adapter locally expects a
`list[str] -> int` entry point; this is not a core-wide contract.

```bash
uv run python -m dix.bootstrap build launcher.toml --output ./launcher.py
```

## Development verification

```bash
uv run pytest -q
uv run python -m compileall -q src tests
zsh unstable/pressure/bootstrap_seed/run.zsh
zsh unstable/pressure/bootstrap_seed/verify_wheel.zsh
git diff --check
```

CLI, Typer, HTTP, generic runners, Norn/strand experiments, code generation, remote execution, ROBA,
sandboxing, package management, and lifecycle policy remain higher-layer work rather than hidden
core behavior.
