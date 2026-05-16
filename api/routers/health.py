"""Health check endpoint."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check():
    """Health check."""
    return {"status": "healthy"}
