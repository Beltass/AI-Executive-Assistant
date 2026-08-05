"""FastAPI application entry point."""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db.database import engine, Base
from app.api.routes import content, templates, network, speaking, analytics, slack

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Create tables
Base.metadata.create_all(bind=engine)

# Create FastAPI app
app = FastAPI(
    title=settings.API_TITLE,
    description="AI-powered content creation platform",
    version=settings.API_VERSION,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": settings.API_VERSION}


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Content Creation Platform API",
        "version": settings.API_VERSION,
        "docs": "/docs",
    }


# Include routers
app.include_router(content.router, prefix="/api/content", tags=["content"])
app.include_router(templates.router, prefix="/api/templates", tags=["templates"])
app.include_router(network.router, prefix="/api/network", tags=["network"])
app.include_router(speaking.router, prefix="/api/speaking", tags=["speaking"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(slack.router, prefix="/api/slack", tags=["slack"])


# Error handlers
@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    """Generic exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
