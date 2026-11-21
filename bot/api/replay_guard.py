"""Fail closed while replay is unavailable in the Mini App.

The vision flag controls only one pipeline stage; it is not a release flag.
Do not enable replay until evidence access is bound to the requesting owner.
"""

from starlette.responses import JSONResponse


REPLAY_ANALYSIS_AVAILABLE = False


class ReplayAvailabilityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and not REPLAY_ANALYSIS_AVAILABLE and (
            path.rstrip("/") == "/api/ai/replay/analyze"
            or path.startswith("/api/ai/replay/evidence/")
        ):
            # Reject before multipart body parsing or authentication/DB access.
            response = JSONResponse(status_code=404, content={"detail": "Not Found"})
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
