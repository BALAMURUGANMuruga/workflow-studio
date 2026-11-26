# Create the FastAPI application and register backend routers and service settings.
"""Workflow Studio — FastAPI application entrypoint."""
# Postpone evaluation of type annotations.
from __future__ import annotations

# Use an async context manager to pair server startup with shutdown.
from contextlib import asynccontextmanager
# Resolve the configuration file relative to the source file.
from pathlib import Path

# Use python-dotenv to read local environment configuration.
from dotenv import load_dotenv
# FastAPI hosts the application and serves its HTTP routes.
from fastapi import FastAPI
# Use CORS middleware to control requests made by browsers on other origins.
from fastapi.middleware.cors import CORSMiddleware

# Load backend environment defaults while preserving variables set by the process.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

# Read the integration mode flag reported on the health endpoint.
from .workflow_actions import MOCK_MODE
from .api.assistant_ai_routes import router as local_ai_router
from .api.studio_api_router import router
from .auth.authentication_routes import router as auth_router
from .core.config import get_settings
from .assistant_ai.workflow_intent_service import (
    health as local_ai_health,
    initialize_local_ai,
    shutdown_local_ai,
)

# Load the application name, version, integration settings, and allowed origins.
settings = get_settings()


# Initialize local AI when FastAPI starts and release its state at shutdown.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Set up the local intent service before FastAPI starts serving requests.
    initialize_local_ai()
    try:
        # Hand control to FastAPI while the server is active.
        yield
    finally:
        # Release local AI state when FastAPI exits the lifespan context.
        shutdown_local_ai()


# Create the ASGI application with the configured metadata, lifespan, and documentation URLs.
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Apply the configured origins and allow browser requests with credentials, methods, and headers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register authentication endpoints.
app.include_router(auth_router)
# Register workflow chat, runtime, studio, and automation endpoints.
app.include_router(router)
# Register local assistant service endpoints.
app.include_router(local_ai_router)


# Return service health information for callers such as the Angular workspace.
@app.get("/api/health")
def health():
    # Return a JSON object. Integration settings are exposed as status flags.
    return {
        "status": "ok",
        "mockMode": MOCK_MODE,
        # Report whether the local workflow model is loaded.
        "localIntentEngineReady": local_ai_health()["model_loaded"],
        "version": settings.app_version,
    }


# Return configuration status through the API.
@app.get("/api/config/status")
def config_status():
    # Return a JSON object. Integration settings are exposed as status flags.
    return {
        "interopUrlConfigured": bool(settings.interop_url),
        "interopUserConfigured": bool(settings.interop_user),
        "interopPasswordConfigured": bool(settings.interop_password),
        # Report whether the local workflow model is loaded.
        "localIntentEngineReady": local_ai_health()["model_loaded"],
        "mockMode": settings.workflow_mock_mode,
    }
