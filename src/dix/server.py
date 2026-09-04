from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from dix.compositions import CompositionError, CompositionRegistry, DatamodelFilesFactory
from dix.assembly import assemble_compositions
from dix.config import (
    DEFAULT_CONFIG,
    EffectiveConfig,
    composition_settings_from_values,
    load_effective_config,
)
from dix.functional import (
    FunctionalInterfaceError,
    FunctionalRuntimeStore,
    InterfaceFunctionNotFound,
)
from dix.models import ComponentRenderModel, Session
from dix.registry import InterfaceNotFound, RegistryError, find_interface
from dix.rendering import HtmlRenderer
from dix.runtime import InterfaceRuntime, RuntimeStore


def _interface_dirs(config: dict[str, Any]) -> list[Path]:
    return [Path(item) for item in config["interface_dirs"]]


def _renderer_path(config: dict[str, Any]) -> str:
    return str(config["reference_renderer_path"]).rstrip("/")


def create_app(config: dict[str, Any] | EffectiveConfig | None = None) -> FastAPI:
    if config is None:
        effective = load_effective_config()
        cfg = {**DEFAULT_CONFIG, **effective.values}
        composition_settings = effective.composition
    elif isinstance(config, EffectiveConfig):
        cfg = {**DEFAULT_CONFIG, **config.values}
        composition_settings = config.composition
    else:
        cfg = {**DEFAULT_CONFIG, **config}
        composition_settings = composition_settings_from_values(cfg, base_dir=None)
    app = FastAPI(title="dix")
    store = RuntimeStore()
    renderer = HtmlRenderer()
    composition_assembly = assemble_compositions(composition_settings)
    capability_components = composition_assembly.components
    composition_registry = CompositionRegistry()
    composition_registry.register(DatamodelFilesFactory())
    functional_store = FunctionalRuntimeStore(
        components=capability_components,
        compositions=composition_registry,
    )
    app.state.capability_components = capability_components
    app.state.composition_component = composition_assembly.compositions
    app.state.composition_registry = composition_registry
    app.state.functional_store = functional_store

    def session_from_request(request: Request) -> Session:
        user = request.headers.get("X-DIX-User")
        groups = [
            item.strip()
            for item in request.headers.get("X-DIX-Groups", "").split(",")
            if item.strip()
        ]
        return Session(
            id=user or "anonymous",
            authenticated=bool(user),
            attributes={"groups": groups},
        )

    def value_at_path(session: Session, path: str) -> Any:
        current: Any
        if path == "id":
            return session.id
        if path == "authenticated":
            return session.authenticated
        current = session.attributes
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    def check_access(spec: Any, session: Session) -> bool:
        access = spec.interface.access
        if access.mode == "public":
            return True
        if access.mode == "disabled":
            return False
        if access.mode == "authenticated":
            return session.authenticated
        if access.mode == "session_match":
            current = value_at_path(session, access.path or "")
            if access.equals is not None:
                return current == access.equals
            if access.contains is not None:
                return isinstance(current, list) and access.contains in current
            return bool(current)
        return False

    def load_runtime(interface_id: str, request: Request) -> InterfaceRuntime:
        session = session_from_request(request)
        try:
            spec = find_interface(_interface_dirs(cfg), interface_id)
        except InterfaceNotFound as e:
            raise HTTPException(
                status_code=404, detail=f"interface not found: {interface_id}"
            ) from e
        except RegistryError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        if not check_access(spec, session):
            raise HTTPException(status_code=403, detail="interface access denied")
        return store.get_or_create(spec, session)

    async def parse_update_payload(request: Request) -> dict[str, Any]:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            raw = await request.json()
            return raw if isinstance(raw, dict) else {}
        body = (await request.body()).decode()
        parsed = parse_qs(body, keep_blank_values=True)
        return {key: values[0] if len(values) == 1 else values for key, values in parsed.items()}

    def update_runtime(
        runtime: InterfaceRuntime, component_id: str, data: dict[str, Any]
    ) -> InterfaceRuntime:
        try:
            return store.update_component(runtime, component_id, data)
        except KeyError as e:
            raise HTTPException(
                status_code=404, detail=f"component not found: {component_id}"
            ) from e
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    def component_render_model(
        runtime: InterfaceRuntime, component_id: str
    ) -> ComponentRenderModel:
        model = runtime.render_model(renderer_path=_renderer_path(cfg))
        for component in model.components:
            if component.id == component_id:
                return component
        raise HTTPException(status_code=404, detail=f"component not found: {component_id}")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/interfaces/{interface_id}/model")
    def get_interface_model(interface_id: str, request: Request) -> dict[str, Any]:
        runtime = load_runtime(interface_id, request)
        return runtime.model().model_dump()

    @app.post("/api/interfaces/{interface_id}/components/{component_id}/update")
    async def update_component_api(
        interface_id: str, component_id: str, request: Request
    ) -> dict[str, Any]:
        runtime = load_runtime(interface_id, request)
        data = await parse_update_payload(request)
        update_runtime(runtime, component_id, data)
        return runtime.model().model_dump()

    @app.get("/api/interfaces/{interface_id}/functions/{function_id}")
    def invoke_interface_function(
        interface_id: str,
        function_id: str,
        request: Request,
    ) -> Any:
        runtime = load_runtime(interface_id, request)
        try:
            return functional_store.get_or_create(runtime.spec).invoke(function_id)
        except InterfaceFunctionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (FunctionalInterfaceError, CompositionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    if cfg.get("reference_renderer_enabled", True):
        render_path = _renderer_path(cfg)

        @app.get(f"{render_path}/{{interface_id}}", response_class=HTMLResponse)
        def render_interface(interface_id: str, request: Request) -> HTMLResponse:
            runtime = load_runtime(interface_id, request)
            return HTMLResponse(
                renderer.render_interface(runtime.render_model(renderer_path=render_path))
            )

        @app.post(
            f"{render_path}/{{interface_id}}/components/{{component_id}}/update",
            response_class=HTMLResponse,
        )
        async def update_component_render(
            interface_id: str, component_id: str, request: Request
        ) -> HTMLResponse:
            runtime = load_runtime(interface_id, request)
            data = await parse_update_payload(request)
            update_runtime(runtime, component_id, data)
            render_model = runtime.render_model(renderer_path=render_path)
            component = component_render_model(runtime, component_id)
            return HTMLResponse(renderer.render_update_fragment(render_model, component))

    return app


def serve() -> int:
    cfg = load_effective_config().values
    import uvicorn

    uvicorn.run(create_app(cfg), host=cfg["host"], port=cfg["port"])
    return 0
