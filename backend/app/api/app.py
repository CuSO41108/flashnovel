from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import start_worker, stop_worker
from app.api.routes.health import router as health_router
from app.api.routes.runs import router as runs_router
from app.api.routes.stories import router as stories_router
from app.api.routes.workspaces import router as workspaces_router


def create_app() -> FastAPI:
    app = FastAPI(title="flashnovel", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(stories_router)
    app.include_router(workspaces_router)
    app.include_router(runs_router)

    @app.on_event("startup")
    def _startup() -> None:
        start_worker()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        stop_worker()

    return app


app = create_app()


def main() -> int:
    uvicorn.run("app.api.app:app", host="127.0.0.1", port=8010, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
