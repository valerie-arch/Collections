"""FastAPI main application — Wahu Collections Reconciliation Platform."""

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.config import settings
from api.database import init_db, get_db
from api.routers import activities, agencies, dashboard, drives, exceptions, health, payments, quickbooks, reports, runs, suspense, trends
from api.scheduler import init_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # Startup
    init_db()
    init_scheduler()
    print("✓ Collections platform started")
    yield
    # Shutdown
    print("✓ Collections platform stopped")


app = FastAPI(
    title="Wahu Collections Reconciliation Platform",
    version="0.1.0",
    description="Daily/weekly collections reconciliation across Wahu Fleet & TSA",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router, tags=["Health"])
app.include_router(runs.router, prefix="/api/runs", tags=["Runs"])
app.include_router(exceptions.router, prefix="/api/exceptions", tags=["Exceptions"])
app.include_router(reports.router, prefix="/api/reports", tags=["Reports"])
app.include_router(drives.router, prefix="/api/drives", tags=["Drives"])
app.include_router(agencies.router, prefix="/api/agencies", tags=["Agencies"])
app.include_router(trends.router, prefix="/api/trends", tags=["Trends"])
app.include_router(suspense.router, prefix="/api/suspense", tags=["Suspense"])
app.include_router(quickbooks.router, prefix="/api/quickbooks", tags=["QuickBooks"])
app.include_router(activities.router, prefix="/api/activities", tags=["Activities"])
app.include_router(payments.router, prefix="/api/payments", tags=["Payments"])
# collections_v3 Agency Console — read API.
app.include_router(dashboard.router)


@app.get("/")
def root():
    """Root endpoint."""
    return {
        "service": "Wahu Collections Reconciliation Platform",
        "version": "0.1.0",
        "status": "running",
    }
