from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from bot.api.errors import register_exception_handlers
from bot.api.routes import battles, decks, misc, profile

WEBAPP_DIST = Path(__file__).resolve().parents[2] / "webapp" / "dist"
STATIC_CARDS = Path(__file__).resolve().parents[1] / "static" / "cards"


def create_app() -> FastAPI:
    app = FastAPI(title="Ghosteek CR Assistant API", version="1.0.0")
    register_exception_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(profile.router)
    app.include_router(battles.router)
    app.include_router(decks.router)
    app.include_router(misc.router)

    if STATIC_CARDS.exists():
        app.mount("/cards", StaticFiles(directory=STATIC_CARDS), name="cards")

    if WEBAPP_DIST.exists():
        assets_dir = WEBAPP_DIST / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                return {"detail": "Not Found"}
            index = WEBAPP_DIST / "index.html"
            if index.exists():
                return FileResponse(index)
            return {"detail": "Webapp not built. Run: cd webapp && npm run build"}

    return app
