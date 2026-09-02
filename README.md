# dix

Declarative Interface eXecutor.

`dix` provides spec-driven interfaces for controlled actions. This foundation cut proves the
smallest useful end-to-end path:

```text
element state/functions -> component abstraction -> interface composition -> API -> optional renderer
```

The project intentionally does **not** include business-specific provisioning logic, AD/LDAP/OIDC,
PDF generation, a workflow engine, or a React/Vue/Svelte SPA in this foundation slice.

## Concepts

- **Interface**: a concrete declarative UI composition made from components.
- **Component**: the primary authoring unit used by interfaces. Components hide element wiring.
- **Element**: a headless state/function primitive such as `value`, `list`, or `selection`.
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
