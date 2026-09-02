from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from dix.config import load_effective_config
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

    def load_runtime(interface_id: str):
        try:
            spec = find_interface(_interface_dirs(cfg), interface_id)
        except InterfaceNotFound as e:
            raise HTTPException(status_code=404, detail=f"interface not found: {interface_id}") from e
        except RegistryError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return store.get_or_create(spec)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/interfaces/{interface_id}", response_class=HTMLResponse)
    def get_interface(interface_id: str):
        runtime = load_runtime(interface_id)
        return HTMLResponse(renderer.render_interface(runtime))

    @app.get("/api/interfaces/{interface_id}/model")
    def get_interface_model(interface_id: str):
        runtime = load_runtime(interface_id)
        return runtime.model().model_dump()

    @app.post("/api/interfaces/{interface_id}/components/{component_id}/update")
    async def update_component(interface_id: str, component_id: str, request: Request):
        runtime = load_runtime(interface_id)
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
