from fastapi import APIRouter
from app.staticMusic.router import router as staticMusicRouter
from app.streamingMusic.router import router as streamingMusicRouter

# Main aggregator router
v1_router = APIRouter()

# Sub routes 
v1_router.include_router(staticMusicRouter, prefix="/songs", tags=["Songs"])
v1_router.include_router(streamingMusicRouter, prefix="/stream", tags=["Stream"])
