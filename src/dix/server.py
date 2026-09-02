from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from dix.config import load_effective_config
from dix.models import Session
from dix.registry import InterfaceNotFound, RegistryError, find_interface
from dix.rendering import HtmlRenderer
from dix.runtime import RuntimeStore


def _interface_dirs(config: dict[str, Any]) -> list[Path]:
    return [Path(item) for item in config["interface_dirs"]]


def create_app(config: dict[str, Any] | None = None) -> FastAPI:
    cfg = config or load_effective_config().values
    app = FastAPI(title="dix")
    store = RuntimeStore()
    renderer = HtmlRenderer()

    def session_from_request(request: Request) -> Session:
        user = request.headers.get("X-DIX-User")
        groups = [item.strip() for item in request.headers.get("X-DIX-Groups", "").split(",") if item.strip()]
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

    def check_access(spec, session: Session) -> bool:
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

    def load_runtime(interface_id: str, request: Request):
        session = session_from_request(request)
        try:
            spec = find_interface(_interface_dirs(cfg), interface_id)
        except InterfaceNotFound as e:
            raise HTTPException(status_code=404, detail=f"interface not found: {interface_id}") from e
        except RegistryError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        if not check_access(spec, session):
            raise HTTPException(status_code=403, detail="interface access denied")
        return store.get_or_create(spec, session)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/interfaces/{interface_id}", response_class=HTMLResponse)
    def get_interface(interface_id: str, request: Request):
        runtime = load_runtime(interface_id, request)
        return HTMLResponse(renderer.render_interface(runtime))

    @app.get("/api/interfaces/{interface_id}/model")
    def get_interface_model(interface_id: str, request: Request):
        runtime = load_runtime(interface_id, request)
        return runtime.model().model_dump()

    @app.post("/api/interfaces/{interface_id}/components/{component_id}/update")
    async def update_component(interface_id: str, component_id: str, request: Request):
        runtime = load_runtime(interface_id, request)
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            raw = await request.json()
            data = raw if isinstance(raw, dict) else {}
        else:
            body = (await request.body()).decode()
            parsed = parse_qs(body, keep_blank_values=True)
            data = {key: values[0] if len(values) == 1 else values for key, values in parsed.items()}
        try:
            store.update_component(runtime, component_id, data)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=f"component not found: {component_id}") from e
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        if request.headers.get("HX-Request"):
            return HTMLResponse(renderer.render_component(runtime, component_id))
        return runtime.model().model_dump()

    return app


def serve() -> int:
    cfg = load_effective_config().values
    import uvicorn

    uvicorn.run(create_app(cfg), host=cfg["host"], port=cfg["port"])
    return 0
