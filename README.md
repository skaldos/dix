# dix

Declarative Interface eXecutor.

`dix` provides declarative interfaces over narrow core capabilities and trusted, in-process Python
compositions. The current foundation proves two end-to-end paths:

```text
UI element state/functions -> UI component -> interface -> API -> optional renderer
trusted module root -> composition spec -> isolated runtime graph -> interface function -> API
```

The project intentionally does **not** include business-specific provisioning logic, AD/LDAP/OIDC,
PDF generation, a workflow engine, package management, remote plugin admission, or process isolation.

## Concepts

- **Interface**: the only externally exposed declarative control surface. It explicitly binds selected
  composition functions or renderer-oriented UI components.
- **Core component**: a narrow internal capability. `element` handles atomic native Python values;
  `datamodel` handles schemas; `composition` owns the authoritative module and runtime graph.
- **Module**: a trusted delivery and dependency bundle below a configured root. Its relative path is its
  current ID; there is no `module.toml`.
- **Composition definition**: a static `composition.toml` plus the fixed `runtime.py:Runtime` entrypoint.
- **Composition instance**: one isolated runtime graph. Each node receives local composition-scoped
  components; runtime-scoped control components are explicitly shared.
- **Composition API**: only functions declared by the spec and implemented as local runtime methods.
  Adopted dependency functions remain real local wrappers with inspectable origins and signatures.
- **Renderer**: a presentation adapter. The included HTML/Jinja/HTMX renderer is optional and consumes
  the same interface model under `/render`.

Python code loaded from a trusted module runs in-process and is not sandboxed. Registry publication is
atomic, but arbitrary Python import side effects cannot be rolled back.

## Module layout

```text
<trusted-root>/
  <module-id>/
    compositions/
      <local-composition-id>/
        composition.toml
        runtime.py
```

The included example is:

```text
examples/modules/dix/examples/files/
  compositions/datamodel_files/{composition.toml,runtime.py}
```

Its effective composition ID is `dix/examples/files/datamodel_files`.

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
```

Scaffolding and generation never overwrite existing files. The generator obtains dependency signatures
from the live runtime code of the explicitly referenced compositions below configured trusted roots;
signatures are not copied into TOML specs. Build-time dependency resolution is composition-granular, so
a runtime can be generated while its target module bundle is still incomplete. Normal runtime loading
remains atomic at module level. Generation imports the referenced dependency runtimes and therefore
executes trusted Python module code; configure trusted module roots accordingly.

## Direct Python smoke

```python
from pathlib import Path
from dix.core import CompositionComponent, create_core_component_registry
from dix.core.composition import CompositionInstanceSpec

root = Path.cwd()
registry = create_core_component_registry()
compositions = registry.require("composition", CompositionComponent)
compositions.load_module(
    root / "examples/modules/dix/examples/files",
    module_id="dix/examples/files",
)
instance = compositions.create_instance(
    CompositionInstanceSpec(
        id="demo",
        use="dix/examples/files/datamodel_files",
        config={},
        config_base_dir=root,
    ),
    owner_scope_id="shell",
)
instance.api.register_model(root / "examples/models/demo_user.toml")
result = instance.api.load_data((root / "examples/data/demo_user.json").read_text())
assert result.values["age"] == 42
```

## Included demos

`examples/interfaces/demo_request.toml` exercises the renderer-oriented `input` and `select` UI
components. `examples/interfaces/demo_datamodel.toml` binds the trusted `datamodel_files` composition.
Its local integer wrapper turns the JSON string `"42"` into an integer without changing any other
composition-local datamodel instance. The interface exposes only the explicit, side-effect-free `run`
adapter and reuses one stable root graph across repeated GET requests.
