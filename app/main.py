"""FastAPI application entry point for DevOpsLens AI.

Sets up lifespan events, CORS middleware, global exception handlers,
and registers REST API routes.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router as api_router
from app.config import get_settings
from app.database.connection import init_db
from app.utils.logger import get_logger, setup_logging

# Initialize application logging formatters
setup_logging()
logger = get_logger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler executed before server start and after server shutdown."""
    settings = get_settings()
    logger.info(f"Starting {settings.app_name} v{settings.app_version} in {settings.environment} mode.")
    # Initialize SQLite database schema
    init_db()
    yield
    logger.info("DevOpsLens AI shutting down cleanly.")


def create_app() -> FastAPI:
    """Application factory for DevOpsLens AI."""
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Intelligent Log Analysis and Bug Triage Platform. "
            "Parses application logs, aggregates recurring errors, assigns transparent "
            "rule-based priority rankings, and provides grounded AI-assisted root-cause diagnosis."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan
    )

    # Cross-Origin Resource Sharing (CORS) Middleware
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routes under /api/v1 and root
    application.include_router(api_router, prefix="/api/v1")
    application.include_router(api_router)  # Also allow direct /health, /analyze, /analyses

    # Global Exception Handler for Unhandled Server Exceptions (Prevents leaking stack traces)
    @application.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception during {request.method} {request.url.path}: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "InternalServerError",
                "detail": "An unexpected server error occurred while processing the request.",
                "status_code": 500
            }
        )

    # Standardized HTTPException Handler
    @application.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "RequestError",
                "detail": exc.detail,
                "status_code": exc.status_code
            }
        )

    return application


app = create_app()
