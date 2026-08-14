from ytmusicapi import YTMusic
from app.staticMusic.models import Song, ArtistResult,AlbumDetails,PlaylistTracks, SongLyrics
from typing import List, Any, Optional, Dict

class StaticMusicAPI:
    def __init__(self):
        self.ytmusic = YTMusic(language="en")

    def _search(self, item: str, filter: str) -> Optional[List[Dict[str, Any]]]:
        if not item:
            return None
        return self.ytmusic.search(item, filter=filter)

    def getSong(self, title: str) -> Optional[List[Song]]:
        res = self._search(title, "songs")
        if not res:
            return None
        return [Song.model_validate(song) for song in res]

    def getSongMetadata(self, videoId: str) -> Optional[List[Song]]:
            return self.ytmusic.get_song(videoId).get("videoDetails")

    def getArtist(self, artist: str) -> Optional[List[ArtistResult]]:
        res = self._search(artist, "artists")
        if not res:
            return None
        return [ArtistResult.model_validate(a) for a in res]

    def getAlbum(self, albumId: str) -> Optional[AlbumDetails]:
        if not albumId:
            return None
        album = self.ytmusic.get_album(albumId)
        return AlbumDetails.model_validate(album) if album else None

    def getNextSongs(self, currentVideoId: str) -> Optional[PlaylistTracks]:
        if not currentVideoId:
            return None
        watch_playlist = self.ytmusic.get_watch_playlist(currentVideoId)
        return PlaylistTracks.model_validate(watch_playlist) if watch_playlist else None

    def getLyrics(self, songId: str) -> Optional[SongLyrics]:
        """Fetch song lyrics using a lyrics browse ID.

        :param songId: Must be the `lyrics` browse ID string obtained from a
                          `PlaylistResult` or `TrackResult` object (e.g., 'MPLYt_...'),
                          NOT a standard YouTube videoId or track ID.
        :returns: A populated `SongLyrics` object if available, otherwise `None`.
        """
        if not songId:
            return None
        raw_lyrics = self.ytmusic.get_lyrics(songId, True)
        if not raw_lyrics:
            return None
        return SongLyrics.model_validate(raw_lyrics)

    def getSearchSuggestions(self, search: str) -> Optional[List[str]]:
        if not search:
            return None
        return self.ytmusic.get_search_suggestions(search)
        

