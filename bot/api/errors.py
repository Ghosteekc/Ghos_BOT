"""Безопасные HTTP-ответы без утечки stack trace."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from bot.user_errors import DEFAULT_UNAVAILABLE, MESSAGES

logger = logging.getLogger(__name__)


def _normalize_detail(exc: HTTPException) -> dict[str, str]:
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        return {"message": str(detail["message"]), "code": str(detail["code"])}
    if isinstance(detail, str):
        return {"message": detail, "code": "E099"}
    return {"message": DEFAULT_UNAVAILABLE, "code": "E099"}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        body = _normalize_detail(exc)
        if body["code"] == "E099" and exc.status_code >= 500:
            body["message"] = MESSAGES.get("E099", DEFAULT_UNAVAILABLE)
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"message": DEFAULT_UNAVAILABLE, "code": "E099"},
        )
