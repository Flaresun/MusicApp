from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class Album(BaseModel):
    name: str
    id: str


class Artist(BaseModel):
    name: str
    id: Optional[str] = None


class Thumbnail(BaseModel):
    url: str
    width: int
    height: int


class Song(BaseModel):
    category: str
    resultType: str
    title: str
    album: Album
    inLibrary: bool
    pinnedToListenAgain: bool
    videoId: str
    videoType: str
    duration: str
    artists: List[Artist]
    duration_seconds: int
    views: str
    isExplicit: bool
    thumbnails: List[Thumbnail]
    year: Optional[int] = None


class ArtistResult(BaseModel):
    category: str
    resultType: str
    artist: str
    browseId: str
    thumbnails: List[Thumbnail]
    shuffleId: Optional[str] = None
    radioId: Optional[str] = None


# Albums
class DescriptionRun(BaseModel):
    text: str
    url: Optional[str] = None


class FeedbackTokens(BaseModel):
    add: Optional[str] = None
    remove: Optional[str] = None


class Track(BaseModel):
    videoId: str
    title: str
    artists: List[Artist]
    album: str
    likeStatus: str
    inLibrary: bool
    pinnedToListenAgain: bool
    feedbackTokens: FeedbackTokens
    isAvailable: bool
    isExplicit: bool
    videoType: str
    views: str
    trackNumber: int
    duration: str
    duration_seconds: int
    creditsBrowseId: str
    thumbnails: Optional[List[Thumbnail]] = None
    communityVoteStatus: Optional[str] = None


class AlbumVersion(BaseModel):
    title: str
    artists: List[Artist]
    browseId: str
    audioPlaylistId: str
    thumbnails: List[Thumbnail]
    isExplicit: bool
    type: str


class AlbumDetails(BaseModel):
    title: str
    type: str
    thumbnails: List[Thumbnail]
    isExplicit: bool
    description: str
    descriptionRuns: List[DescriptionRun]
    year: str
    artists: List[Artist]
    trackCount: int
    duration: str
    audioPlaylistId: str
    likeStatus: str
    tracks: List[Track]
    duration_seconds: int
    other_versions: Optional[List[AlbumVersion]] = None


# Up Next Queue
class AlbumRef(BaseModel):
    name: str
    id: str


class TrackResult(BaseModel):
    videoId: str
    title: str
    length: str
    thumbnail: List[Thumbnail]
    videoType: str
    inLibrary: bool
    pinnedToListenAgain: bool
    artists: List[Artist]
    album: Optional[AlbumRef] = None
    year: Optional[str] = None
    likeStatus: Optional[str] = None
    feedbackTokens: Optional[Dict[str, Any]] = None
    listenAgainFeedbackTokens: Optional[Dict[str, Any]] = None


class PlaylistTracks(BaseModel):
    tracks: List[TrackResult]
    playlistId: str
    lyrics: Optional[str] = None
    related: Optional[str] = None


# Lyrics
class LyricLine(BaseModel):
    text: str
    start_time: int
    end_time: int
    id: int


class SongLyrics(BaseModel):
    lyrics: List[LyricLine]
    source: str
    hasTimestamps: bool = True