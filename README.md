# dix

Declarative Interface eXecutor.

`dix` provides narrow core capabilities plus trusted, in-process Python compositions and
applications. The current foundation proves three independent end-to-end paths:

```text
UI element state/functions -> UI component -> interface -> API -> optional renderer
trusted module root -> composition spec -> isolated composition graph -> local function API
component -> composition -> application -> child application -> local function API
```

The project intentionally does **not** include business-specific provisioning logic, AD/LDAP/OIDC,
PDF generation, a workflow engine, package management, remote plugin admission, or process isolation.

## Concepts

- **Declarative interface**: the existing HTTP/renderer-oriented control surface. It explicitly binds
  selected composition functions or UI components; loading an application does not add such a surface.
- **Core component**: a narrow internal capability. `element` handles atomic native Python values;
  `datamodel` handles schemas; `composition`, `application`, and `module` own their respective runtime
  registries and delivery transaction.
- **Module**: a trusted delivery and dependency bundle below a configured root. Its relative path is its
  current ID. It may contain compositions, applications, or both; there is no `module.toml`.
- **Composition definition**: a static `composition.toml` plus the fixed `runtime.py:Runtime` entrypoint.
- **Composition instance**: one isolated runtime graph. Each node receives local composition-scoped
  components; runtime-scoped control components are explicitly shared.
- **Composition API**: only functions declared by the spec and implemented as local runtime methods.
  Adopted dependency functions remain real local wrappers with inspectable origins and signatures.
- **Application definition**: a static `app.toml` plus `runtime.py:Runtime`. It may depend only on
  compositions and applications, never directly on core components.
- **Application instance**: one owner-scoped recursive graph with private child-application and
  composition graphs. Construction and structural destruction are explicit Core operations; behavior
  runs only through declared functions.
- **Application API**: the declared local function surface used by parent applications and direct Python
  consumers. It is not automatically exposed through HTTP, sockets, or CLI calls.
- **Renderer**: a presentation adapter. The included HTML/Jinja/HTMX renderer is optional and consumes
  the same interface model under `/render`.

Python code loaded from a trusted module runs in-process and is not sandboxed. Registry publication is
atomic, but arbitrary Python import side effects cannot be rolled back.

## Module layout

```text
<trusted-root>/
  <module-id>/
    compositions/
      <local-composition-id>/{composition.toml,runtime.py}
    apps/
      <local-application-id>/{app.toml,runtime.py}
```

The included examples are:

```text
examples/modules/dix/examples/files/
  compositions/datamodel_files/{composition.toml,runtime.py}

examples/modules/acme/demo/
  compositions/{value_source,formatter}/...
  apps/{base,child}/...
```

The files example's effective composition ID is `dix/examples/files/datamodel_files`.

## Configuration

Generate a local config and inspect its effective sources:

```bash
uv run dix config init
uv run dix config effective
uv run dix config explain composition
```

Composition configuration is anchored to the file that defines it; relative paths never use the
process working directory implicitly:

```toml
[composition]
trusted_module_roots = ["examples/modules"]

[[composition.instance]]
id = "optional_startup"
use = "acme/runtime/worker"
startup = true

[composition.instance.config]
source = "data/input.json"
```

## Development quickstart

```bash
uv run --extra dev pytest
uv run python -m compileall -q src tests
uv run dix --help
uv run dix module list --json
uv run dix composition list --json
uv run dix composition functions dix/examples/files/datamodel_files --json
uv run dix app list --json
uv run dix app show acme/demo/child --json
uv run dix app graph acme/demo/child --json
```

Start the demo server:

```bash
uv run dix serve
```

Open:

```text
http://127.0.0.1:8000/render/demo_request
http://127.0.0.1:8000/api/interfaces/demo_request/model
http://127.0.0.1:8000/api/interfaces/demo_datamodel/functions/run
```

## CLI

```bash
dix module new --id my/new_stuff --root ./modules
dix module list [--json]
dix module show <module-id> [--json]
dix module inspect <path> --id <module-id> [--json]
dix module graph <module-id> [--json]

dix composition list [--json]
dix composition show <composition-id> [--json]
dix composition functions <composition-id> [--json]
dix composition instance list [--json]

dix composition new \
  --module ./modules/my/new_stuff \
  --id processor \
  --component model=datamodel \
  --composition base=dix/examples/files/datamodel_files \
  --export base.load_data \
  --function local_value

dix composition generate \
  ./modules/my/new_stuff/compositions/processor/composition.toml

dix app list [--json]
dix app show <application-id> [--json]
dix app functions <application-id> [--json]
dix app graph <application-id> [--json]

dix app new \
  --module ./modules/my/new_stuff \
  --id child \
  --composition formatter=acme/demo/formatter \
  --app base=acme/demo/base \
  --export base.render \
  --function local_value

dix app generate \
  ./modules/my/new_stuff/apps/child/app.toml
```

Scaffolding and generation never overwrite existing files. The generators obtain dependency signatures
from live runtime code below configured trusted roots; signatures are not copied into TOML specs.
Build-time dependency resolution is artifact-granular, so a runtime can be generated while its target
module bundle is still incomplete. Normal runtime loading remains atomic across every composition and
application in a module. Generation imports referenced dependency runtimes and therefore executes
trusted Python module code; configure trusted module roots accordingly.

## Direct Python smoke

```python
from pathlib import Path
from dix.core import ApplicationComponent, ModuleComponent, create_core_component_registry
from dix.core.application import ApplicationInstanceSpec

root = Path.cwd()
registry = create_core_component_registry()
modules = registry.require("module", ModuleComponent)
applications = registry.require("application", ApplicationComponent)
modules.load_module(
    root / "examples/modules/acme/demo",
    module_id="acme/demo",
)
instance = applications.create_instance(
    ApplicationInstanceSpec(
        id="demo",
        use="acme/demo/child",
        config={},
        config_base_dir=root,
    ),
    owner_scope_id="shell",
)
assert instance.api.render("input") == "formatted<value:input>"
applications.destroy_instance("shell", "demo")
```

## Included demos

`examples/interfaces/demo_request.toml` exercises the renderer-oriented `input` and `select` UI
components. `examples/interfaces/demo_datamodel.toml` binds the trusted `datamodel_files` composition.
Its local integer wrapper turns the JSON string `"42"` into an integer without changing any other
composition-local datamodel instance. The interface exposes only the explicit, side-effect-free `run`
adapter and reuses one stable root graph across repeated GET requests.

`examples/modules/acme/demo` is a transport-free application pressure test. `child.render` is a real
local wrapper around `base.render`, which calls both example compositions. The automated E2E test
verifies structural construction rollback, root-graph isolation, generator output, and complete
teardown. Load, create, and destroy do not invoke declared functions implicitly.

`examples/modules/dix/core/cli` provides the first-party declarative Typer adapter as an ordinary
composition. `examples/modules/acme/cli_demo` combines it with a transport-independent tool
application through an explicit local target allowlist. Run the complete visible lifecycle-neutral
path with
`uv run python examples/run_cli_demo.py text render --value hello --count 2 --upper true`.

RPC, IPC, ROBA integration, process isolation, authentication, application startup management, and a
remote application call surface are deliberately not implemented. They are possible future stacks over
components, compositions, and applications—not implicit behavior of the current runtime.
