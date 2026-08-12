from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from app.streamingMusic.models import StreamResponseModel, TrackStatusResponse, DeleteTrackResponse
from app.streamingMusic.service import StreamingMusicAPI
from app.core import db_execute, db_fetch_one  # Imports global DB handler helpers

router = APIRouter(prefix="/stream", tags=["Streaming Engine"])

# Initialize service with shared global DB execution handlers
streaming_api = StreamingMusicAPI(
    db_execute_fn=db_execute,
    db_fetch_one_fn=db_fetch_one
)


@router.get("/resolve/{youtube_id}", response_model=StreamResponseModel)
async def resolve_stream(youtube_id: str, background_tasks: BackgroundTasks):
    """
    Resolves audio stream for AVQueuePlayer.
    Returns S3 presigned URL if READY, or direct YouTube CDN URL + launches background worker.
    """
    try:
        return await streaming_api.resolve_track_stream(youtube_id, background_tasks)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resolve stream for video {youtube_id}: {str(e)}"
        )


@router.get("/status/{youtube_id}", response_model=TrackStatusResponse)
async def get_stream_status(youtube_id: str):
    """
    Returns current S3 caching status ('NOT_CACHED', 'PROCESSING', 'READY', 'FAILED').
    """
    return await streaming_api.get_track_status(youtube_id)


@router.delete("/{youtube_id}", response_model=DeleteTrackResponse)
async def delete_stream_cache(youtube_id: str):
    """
    Purges HLS files from S3 bucket and updates DB status to NOT_CACHED.
    """
    try:
        return await streaming_api.delete_track_s3(youtube_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete S3 assets for video {youtube_id}: {str(e)}"
        )