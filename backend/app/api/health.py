"""Liveness plus a real local database query, executed in FastAPI's worker pool."""

import logging
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app import __version__


router = APIRouter(prefix="/api/v1")
logger = logging.getLogger("echo.health")


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str = __version__
    database: Literal["ok"] = "ok"


@router.get("/health", response_model=HealthResponse)
def health(request: Request):
    try:
        with request.app.state.engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1").scalar_one()
    except SQLAlchemyError:
        logger.exception("database_unavailable")
        return JSONResponse({"status": "unavailable", "database": "unavailable"}, status_code=503)
    return HealthResponse()
