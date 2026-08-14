from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, status
from app.streamingMusic.models import ClientTrackMetadata, StreamResponseModel, TrackStatusResponse, DeleteTrackResponse
from app.streamingMusic.service import StreamingMusicAPI
from app.core.database import execute_query

router = APIRouter()

# Initialize service with shared global DB execution handlers
streaming_api = StreamingMusicAPI(
    db_execute_fn=execute_query,
)


@router.post("/resolve/{youtube_id}", response_model=StreamResponseModel)
async def resolve_stream(
    youtube_id: str,
    background_tasks: BackgroundTasks,
    client_metadata: ClientTrackMetadata = Body(...)  # Body(...) makes it mandatory
):
    """
    Resolves audio stream for AVQueuePlayer using strictly typed client metadata.
    Returns S3 presigned URL if READY, or direct YouTube CDN URL + launches background worker.
    """
    try:
        # Convert the Pydantic model to a standard dictionary to pass to our service layer
        meta_dict = client_metadata.model_dump()
        return await streaming_api.resolve_track_stream(youtube_id, meta_dict, background_tasks)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resolve stream for video {youtube_id}"
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