# DIX

**Declarative Interface eXecutor** — explicit, local composition for small Python runtime graphs.

[Deutsch](README.de.md) · [Documentation](https://dix.skaldos.dev) ·
[Source](https://github.com/skaldos/dix) · [ROBA](https://github.com/skaldos/roba) ·
[External modules](https://github.com/skaldos/dix-modules)

> **Public Alpha:** DIX is usable and tested, but its API and module formats may still change before
> a stable release. Pin the exact source revision when building on it.

DIX loads explicitly selected source modules, assembles their compositions and applications, and
exposes only declared local Python functions:

```text
explicit module source
        ↓
composition graph
        ↓
application graph
        ↓
explicitly exposed Python functions
```

It is deliberately not a framework that discovers everything, owns every lifecycle, or moves all
semantics into one central contract. A module keeps its domain logic; DIX supplies a small,
inspectable assembly boundary.

## Why DIX exists

Small tools often begin as useful isolated functions and then become trapped in one CLI, daemon,
HTTP service, or application. DIX separates the reusable application graph from those adapters.
The same explicitly exposed function can therefore be wrapped by a CLI today and by another
locally owned adapter later without turning transport policy into core behavior.

The important boundary is responsibility:

- **DIX core** owns deterministic graph inspection, construction, exposure, and teardown.
- **Modules** own behavior, configuration meaning, validation, and side effects.
- **Applications** own adaptation and policy at their callable boundary.
- **Launchers and adapters** own process, CLI, transport, or UI concerns.

## Core concepts

| Concept | Responsibility |
| --- | --- |
| **Element** | Processes one native Python value through an explicitly registered technical handler chain. |
| **Datamodel** | Processes mappings against locally registered field schemas and reports structured results. It does not instantiate domain objects for the caller. |
| **Composition** | Builds a local graph from components and other compositions and exposes only declared functions. |
| **Application** | Combines compositions and applications into a callable local boundary. An application may wrap, rename, or deliberately withhold dependency functions. |
| **Module** | A source-owned bundle of composition and application definitions that is explicitly inspected, loaded, and unloaded. |

Composition and application specifications describe **graph assembly and function exposure**. They
are not wire contracts. Runtime Python methods remain authoritative for argument and result
signatures; DIX does not silently validate, normalize, serialize, retry, time out, or audit calls.

## Quick start from source

DIX currently targets Python 3.12 or newer. The repository uses
[`uv`](https://docs.astral.sh/uv/) for its reproducible development environment.

```sh
git clone https://github.com/skaldos/dix.git
cd dix
uv sync --extra dev
```

The following complete example explicitly loads the bundled source example, creates one
application graph, calls an exposed function, and tears everything down:

```sh
uv run python - <<'PY'
from pathlib import Path

from dix.core import (
    ApplicationComponent,
    ModuleComponent,
    create_core_component_registry,
)
from dix.core.application import ApplicationInstanceSpec

registry = create_core_component_registry()
modules = registry.require("module", ModuleComponent)
applications = registry.require("application", ApplicationComponent)

modules.load_module(Path("examples/modules/acme/demo"), module_id="acme/demo")
instance = applications.create_instance(
    ApplicationInstanceSpec(
        id="demo",
        use="acme/demo/child",
        config={},
        config_base_dir=Path.cwd(),
    ),
    owner_scope_id="readme",
)

print(instance.api.require("describe")("Skaldos"))

applications.destroy_instance("readme", "demo")
modules.unload_module("acme/demo")
PY
```

Expected output:

```text
child[formatted<value:Skaldos>]
```

Nothing in this example was discovered or started implicitly.

## Module structure

A directly loadable source module has one module root and at least one composition or application:

```text
acme/example/
├── compositions/
│   └── formatter/
│       ├── composition.toml
│       └── runtime.py
└── apps/
    └── report/
        ├── app.toml
        └── runtime.py
```

The effective IDs are formed from the explicit module ID and the local definition ID, for example
`acme/example/formatter` and `acme/example/report`. There is no required `module.toml`, global
module registry, or automatic module loading.

A minimal composition declares only functions that callers may see:

```toml
[composition]
id = "formatter"

[functions.format]
description = "Format one value."
```

```python
class Runtime:
    def __init__(self, *, context, config):
        self.context = context
        self.config = config

    def format(self, value: str) -> str:
        return f"formatted<{value}>"
```

### Immediate-owner bindings

A specialized child composition may explicitly request the `composition_owner` component when it
must bind a callable contract against its immediate owner:

```toml
[components]
owner = "composition_owner"
```

The injected capability offers `bind_dependency(alias, function_id)` for one of the owner's local
composition dependencies and `bind_function(function_id)` for one of the owner's exposed
functions. Both return deferred callables. DIX validates and finalizes all requests atomically
after the owner API exists and before the graph becomes visible. Root use, missing or private
functions, and asynchronous targets fail graph construction. This is deliberately not a global
composition lookup, runtime registry, or child-rebinding mechanism.

Applications use the same explicit pattern and can combine compositions or other applications.
Dependency functions are not exported automatically: the application must declare or implement
the boundary it intends to expose.

## Bootstrap launchers

`dix.bootstrap` turns one explicit launcher specification into an ordinary Python script:

```sh
uv run python -m dix.bootstrap build \
  examples/launchers/my_cli.toml \
  --output /tmp/my-cli
```

The generated script contains fixed module source paths, creates its own registry, loads only the
listed modules, creates one application, calls one declared entry function, and tears the graph
down. The current `python_cli` adapter expects that entry function to implement
`list[str] -> int`; that is an adapter contract, not a universal DIX function contract.

See [`examples/launchers/README.md`](examples/launchers/README.md) for the multi-application CLI
example.

## First-party modules

The wheel includes three explicitly loadable modules as package data:

| Module | Purpose | Extra |
| --- | --- | --- |
| `dix/cli` | Projects explicitly supplied application APIs into a Typer command tree. | `cli` |
| `dix/state` | Builds local Pydantic-backed state models with explicit `get` and `set` boundaries. | `state` |
| `dix/roba` | Composes DIX applications with the independently owned ROBA ephemeral-state service. | `roba` |

Install only the optional dependencies you need:

```sh
uv sync --extra cli
uv sync --extra state
uv sync --extra roba
```

Bundling does not imply discovery or startup. Resolve a bundled module explicitly and then load it
like any other source module:

```python
from dix.modules import first_party_module_path

state_source = first_party_module_path("dix/state")
```

[ROBA](https://github.com/skaldos/roba) remains an independent project. It is an ephemeral runtime
state and exchange service, not a persistence or credential store.

## External source modules

External modules keep their own repository, dependencies, tests, release decisions, and optional
integration artifacts. DIX only needs an explicit source path and module ID. It does not require a
package manager or Git submodule relationship.

The [`skaldos/dix-modules`](https://github.com/skaldos/dix-modules) repository demonstrates this
boundary. Its `skaldos/sway` module is a real Sway/ROBA integration and is intentionally not part
of the DIX wheel or DIX dependency graph. Clone and integration instructions belong to that source
repository; DIX does not auto-discover it.

## Public Python API

The public alpha API is intentionally narrow and module-scoped:

- `dix.core` and its declared `__all__`;
- `dix.core.application` and its declared `__all__`;
- `dix.core.composition` and its declared `__all__`;
- `dix.core.module` and its declared `__all__`;
- `dix.bootstrap` and its declared `__all__`;
- `dix.modules` and its declared `__all__`;
- `dix.__version__`.

Other implementation modules, package-data paths, runtime class-loading details, and repository
layout internals are not public API merely because Python can import or inspect them. DIX adds no
convenience re-exports at the package root.

## Explicit limits and security boundary

DIX core does **not** provide:

- module auto-discovery or auto-start;
- a daemon, scheduler, event loop, HTTP server, IPC transport, or UI;
- authorization, retry, timeout, audit, persistence, or deployment policy;
- process, filesystem, network, or code isolation;
- a universal runtime argument or serialization contract.

Module runtime Python is imported and executed **in the current process**. Transactional registry
publication can prevent a partially loaded graph from becoming visible, but it cannot undo import
side effects and is not a security sandbox. Only load code you trust, or establish a real process
or operating-system isolation boundary outside DIX.

## Development

Run the complete repository checks from a source checkout:

```sh
uv sync --extra dev --extra cli --extra state --extra roba
uv run --extra dev --extra cli --extra state --extra roba pytest -q
uv run python -W error -m compileall -f -q src modules tests examples
uv build --wheel
```

Stable source never imports from `unstable/`, and `unstable/` is excluded from wheels. Synthetic
fixtures under `tests/fixtures/` are test inputs, not shipped modules.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
