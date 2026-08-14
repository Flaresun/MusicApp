from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict


class S3Status(str, Enum):
    NOT_CACHED = "NOT_CACHED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class TrackMetadata(BaseModel):
    youtube_id: str
    title: Optional[str] = "Unknown Title"
    artist: Optional[str] = "Unknown Artist"
    duration: Optional[int] = 0
    s3_status: S3Status = S3Status.NOT_CACHED


class StreamResponseModel(BaseModel):
    source: str = Field(..., description="Stream source: 's3' or 'youtube_cdn'")
    s3_status: S3Status = Field(..., description="Current S3 status of the track")
    stream_url: str = Field(..., description="Direct URL for AVQueuePlayer")
    metadata: Optional[Dict[str, Any]] = None


class TrackStatusResponse(BaseModel):
    youtube_id: str
    s3_status: S3Status
    metadata: Optional[Dict[str, Any]] = None


class DeleteTrackResponse(BaseModel):
    youtube_id: str
    message: str
    s3_status: S3Status = S3Status.NOT_CACHED

class ClientArtist(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    browse_id: str

class ClientTrackMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str
    duration_seconds: int
    thumbnail_url: str
    artists: List[ClientArtist]