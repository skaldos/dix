# dix

Declarative Interface eXecutor.

`dix` provides spec-driven interfaces for controlled actions. The current foundation proves two
small end-to-end paths:

```text
UI element state/functions -> UI component -> interface -> API -> optional renderer
core element capability -> datamodel capability -> trusted composition -> interface function -> API
```

The project intentionally does **not** include business-specific provisioning logic, AD/LDAP/OIDC,
PDF generation, a workflow engine, or a React/Vue/Svelte SPA in this foundation slice.

## Concepts

- **Interface**: the only externally exposed declarative control surface. It may expose UI state or
  explicitly bound functions.
- **Core component**: a narrow internal capability. `element` handles atomic native Python values;
  `datamodel` registers schemas and instantiates mappings through element handlers.
- **Composition**: trusted in-process Python code that combines core capabilities. Specs can only
  select explicitly registered factories and operations; arbitrary import paths are not accepted.
- **UI component**: the existing renderer-oriented authoring unit used by the visual demo.
- **UI element**: a headless UI state/function primitive such as `value`, `list`, or `selection`.
- **Interaction contract**: component-owned logical control contract consumed by renderers.
- **Core API**: headless JSON surface under `/api/...`; it never returns renderer fragments.
- **Renderer**: presentation adapter. The included reference renderer is HTML/Jinja/HTMX and lives under `/render/...` by default.
- **Runtime state**: server-side state for component state/output during an interface session.

## Development quickstart

```bash
uv run --extra dev pytest
uv run dix --help
uv run dix config effective
uv run dix config explain port
uv run dix component list
uv run dix interface list
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
dix config init
dix config validate
dix config effective
dix config explain <key>
dix config edit

# renderer-related config
# reference_renderer_enabled = true
# reference_renderer_path = "/render"

dix interface list
dix interface new <id>
dix interface edit <id>
dix interface delete <id> --force

dix component list

dix serve
```

## Demo interface

The included demo interface is stored at:

```text
examples/interfaces/demo_request.toml
```

It uses two core components:

- `input`, backed by the headless `value` element
- `select`, backed by the headless `list` and `selection` elements

Updating either component changes the interface runtime model. API update endpoints always return JSON. The reference renderer has separate render endpoints and returns HTML fragments for HTMX updates.

## Headless capability demo

`examples/interfaces/demo_datamodel.toml` binds the included trusted `datamodel_files` composition.
The composition translates `examples/models/demo_user.toml` into native core objects and parses
`examples/data/demo_user.json` outside the core capabilities. Its model-local integer wrapper turns
the JSON string `"42"` into an integer before delegating to the strict core integer handler.

The interface exposes exactly one side-effect-free function for this example:

```bash
curl http://127.0.0.1:8000/api/interfaces/demo_datamodel/functions/run
```

The model is registered when the interface composition is first bound and is reused by later GET
requests. TOML and JSON parsing remain composition concerns; `dix.core.element` and
`dix.core.datamodel` only process native Python objects.
