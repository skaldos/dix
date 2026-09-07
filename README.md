# dix

Declarative Interface eXecutor.

`dix` is currently an architecture-stage Python runtime core. Its stable pressure-tested path is:

```text
code-free contract
-> module-owned contract registry
-> explicit Python function binding
-> composition
-> application
-> contract-checked invocation
```

The repository is intentionally not claiming a production runner, transport, UI, authorization
model, process sandbox, package manager, or lifecycle convention yet.

## Current core

- **Element** defines extensible processors for native Python value types.
- **Datamodel** combines elements into named structured models.
- **Norn** registers directional input/output strands and binds them to local handlers.
- **Contract** is a code-free module artifact backed by one Norn strand definition.
- **Function binding** connects exactly one declared Python function to exactly one contract.
- **Composition** combines core components and other compositions in an isolated instance graph.
- **Application** combines compositions and other applications into a callable local boundary.
- **Module** inspects, stages, publishes, and unloads contracts, compositions, and applications as
  one transaction.

Python loaded from a trusted module executes in-process. Atomic registry publication does not make
arbitrary Python imports safe and cannot undo import side effects.

## Repository maturity boundary

```text
src/dix/core/            current core implementation
tests/                   stable core regression
tests/fixtures/modules/  synthetic test modules; never packaged
examples/modules/        future durable teaching examples
unstable/modules/        preserved module experiments
unstable/tools/          pressure and authoring experiments
unstable/tests/          historical regression evidence for replaced surfaces
```

`src/dix` and future stable modules must never import from `unstable`. The `unstable` tree is used
only through explicit development paths and is excluded from wheels.

## Module layout

```text
<trusted-root>/<module-id>/
  contracts/<local-id>/contract.toml
  compositions/<local-id>/{composition.toml,runtime.py}
  apps/<local-id>/{app.toml,runtime.py}
```

A module may contain any non-empty combination of these artifact families. No `module.toml` is
required.

### Contract

```toml
[contract]
id = "echo"
version = "1"

[input]
type = "string"

[output]
type = "string"
```

Contracts are authoritative. Runtime code never generates, mutates, or completes them. A missing
version means exactly `version = None`; it does not mean `latest`.

### Composition function

```toml
[composition]
id = "echo"

[functions.echo]
description = "Echo one string."

[functions.echo.contract]
use = "acme/contract_app/echo"
version = "1"
```

```python
class Runtime:
    def __init__(self, *, context, config):
        self.context = context
        self.config = config

    def echo(self, value):
        return value
```

The first binding slice accepts exactly one non-variadic function parameter. Internal runtime
methods not declared under `[functions]` remain private implementation details and need no contract.

### Application re-export

Dependencies do not implicitly export functions. The application declares its local wrapper,
origin, and contract explicitly:

```toml
[app]
id = "echo"

[compositions.worker]
use = "acme/contract_app/echo"

[functions.echo]
export = "worker.echo"

[functions.echo.contract]
use = "acme/contract_app/echo"
version = "1"
```

## Development verification

```bash
uv run --extra dev pytest
uv run python -m compileall -q src tests unstable examples
uv run python unstable/tools/pressure/run_contract_application.py
uv build --wheel
unzip -l dist/*.whl
```

The pressure script proves contract inspection, atomic module loading, composition/application
binding, checked invocation, invalid-input rejection, live-instance unload blocking, teardown, and
final unload without a CLI, HTTP service, or generic runner.

## Explicit non-goals of this slice

- generic application execution or daemon hosting;
- CLI/Typer projection;
- HTTP, RPC, IPC, renderer, or ROBA integration;
- sandbox and authorization policy;
- contract/code generation or AST inspection;
- automatic version resolution;
- multiple or optional function parameters;
- datamodel-shaped function input.

Those are higher layers over the proven boundary, not hidden behavior in the current core.
