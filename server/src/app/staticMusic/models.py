from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

@dataclass
class Album:
    name: str
    id: str

@dataclass
class Artist:
    name: str
    id: Optional[str] = None

@dataclass
class Thumbnail:
    url: str
    width: int
    height: int

@dataclass
class Song:
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
    year: Optional[int] = None  # Handled as Optional since it's None in your dictionary


@dataclass
class ArtistResult:
    category: str
    resultType: str
    artist: str
    browseId: str
    thumbnails: List[Thumbnail]
    shuffleId: Optional[str] = None
    radioId: Optional[str] = None

# Albums
@dataclass
class DescriptionRun:
    text: str
    url: Optional[str] = None

@dataclass
class FeedbackTokens:
    add: Optional[str] = None
    remove: Optional[str] = None

@dataclass
class Track:
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

@dataclass
class AlbumVersion:
    title: str
    artists: List[Artist]
    browseId: str
    audioPlaylistId: str
    thumbnails: List[Thumbnail]
    isExplicit: bool
    type: str

@dataclass
class AlbumDetails:
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


# Up next Queue 
@dataclass
class AlbumRef:
    name: str
    id: str

@dataclass
class TrackResult:
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

@dataclass
class PlaylistTracks:
    tracks: List[TrackResult]
    playlistId: str
    lyrics: Optional[str] = None
    related: Optional[str] = None


# Lyrics

@dataclass
class LyricLine:
    text: str
    start_time: int
    end_time: int
    id: int

@dataclass
class SongLyrics:
    lyrics: List[LyricLine]
    source: str
    hasTimestamps: bool = True