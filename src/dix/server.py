from __future__ import annotations

from .config import load_effective_config


def serve() -> int:
    cfg = load_effective_config()
    import uvicorn

    uvicorn.run("dix.server:create_app", host=cfg.values["host"], port=cfg.values["port"], factory=True)
    return 0


def create_app():
    from fastapi import FastAPI

    app = FastAPI(title="dix")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
