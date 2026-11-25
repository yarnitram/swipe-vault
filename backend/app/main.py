"""FastAPI application entrypoint."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.auth import ensure_bootstrap_admin
from app.db import session_scope
from app.errors import register_exception_handlers
from app.settings import get_settings

logger = logging.getLogger("swipevault.app")


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            with session_scope() as db:
                ensure_bootstrap_admin(db)
        except Exception as exc:  # noqa: BLE001 - DB might not be migrated during unit test collection
            logger.debug("Skipping bootstrap admin check on startup: %s", exc)
        yield

    docs_url = None if settings.is_production else "/api/v1/docs"
    openapi_url = None if settings.is_production else "/api/v1/openapi.json"
    app = FastAPI(
        title="SwipeVault API",
        version="0.1.0",
        docs_url=docs_url,
        redoc_url=None,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(router)
    return app


app = create_app()
