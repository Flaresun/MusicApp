from app.routers.api_v1 import v1_router
from pathlib import Path    
from fastapi.staticfiles import StaticFiles
import os 
from dotenv import load_dotenv
from app.core.database import init_db, close_db, check_db_health
from contextlib import asynccontextmanager
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

load_dotenv() 

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Open pool and run schema if missing
    await init_db()
    yield
    # Shutdown: Close pool
    await close_db()

# Docs : http://localhost:8000/docs#/
app = FastAPI(
    title="MusicAPI",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(v1_router, prefix="/api/v1")



@app.get("/health")
async def health_check():
    db_healthy = await check_db_health()

    if db_healthy:
        return {
            "status": "healthy",
            "database": "connected"
        }

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "unhealthy",
            "database": "disconnected"
        }
    )
@app.get("/")
def read_root():
    return {"message": "Welcome to the MusicAPI app"}