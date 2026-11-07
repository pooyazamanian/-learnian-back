"""Response schemas for the health and root endpoints."""

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Schema representing service health status."""

    status: str
    app_name: str
    environment: str
    version: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ok",
                "app_name": "Lurnian Backend",
                "environment": "development",
                "version": "0.1.0",
            }
        }
    )


class RootResponse(BaseModel):
    """Schema representing root endpoint response."""

    message: str
    version: str
    docs_url: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Welcome to Lurnian API",
                "version": "0.1.0",
                "docs_url": "/docs",
            }
        }
    )
