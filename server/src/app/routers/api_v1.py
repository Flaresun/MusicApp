from fastapi import APIRouter
from app.staticMusic.router import router as staticMusicRouter

# Main aggregator router
v1_router = APIRouter()

# Sub routes 
v1_router.include_router(staticMusicRouter, prefix="/songs", tags=["Songs"])
