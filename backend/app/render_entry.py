"""Serve the Angular workspace and its API from one Render service."""

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from .main import app


class WorkspaceFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            # Angular owns navigation under these routes. Missing API and asset
            # paths should still produce their original 404.
            requested = Path(path)
            client_route = requested.parts[:1] in {("home",), ("login",), ("register",), ("forgot-password",)}
            if exc.status_code != 404 or not client_route or requested.suffix:
                raise
            return await super().get_response("index.html", scope)


web_root = Path(__file__).resolve().parents[1] / "web"
app.mount("/", WorkspaceFiles(directory=web_root, html=True), name="workspace")
