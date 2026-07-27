from ytmusicapi import YTMusic
from app.staticMusic.models import Song, ArtistResult,AlbumDetails,PlaylistTracks, SongLyrics
from typing import List, Any, Optional

class StaticMusicAPI():
    def __init__(self):
        self.ytmusic = YTMusic(language="en")

    def _search(self,item:str, filter:str)->Optional[Any]:
        if not item:
            return
        return self.ytmusic.search(item, filter=filter)

    def getSong(self,title:str)->Optional[List[Song]]:
        res= self._search(title,"songs")
        return list(map(lambda song: Song(**song),res))

    def getArtist(self,artist:str)->Optional[List[ArtistResult]]:
        res= self._search(artist,"artists")
        return list(map(lambda artist: ArtistResult(**artist),res))

    def getAlbum(self, albumId:str)->Optional[AlbumDetails]:
        # Album.id
        if not albumId:
            return 
        album = self.ytmusic.get_album(albumId)
        return AlbumDetails(**album)

    def getNextSongs(self, currentVideoId:str)->Optional[PlaylistTracks]:
        # Song.videoId
        if not currentVideoId:
            return
        watch_playlist =  self.ytmusic.get_watch_playlist(currentVideoId)
        return PlaylistTracks(**watch_playlist)

    def getLyrics(self, songId: str)->Optional[SongLyrics]:
        """Fetch song lyrics using a lyrics browse ID.

        :param lyrics_id: Must be the `lyrics` browse ID string obtained from a
                          `PlaylistResult` or `TrackResult` object (e.g., 'MPLYt_...'),
                          NOT a standard YouTube videoId or track ID.
        :returns: A populated `SongLyrics` object if available, otherwise `None`.
        """
        if not songId:
            return 
        raw_lyrics = self.ytmusic.get_lyrics(songId, True)
        if not raw_lyrics:
            return None 
        return SongLyrics(**raw_lyrics)

    def getSearchSuggestions(self,search:str)->Optional[List[str]]:
        if not search:
            return 
        return self.ytmusic.get_search_suggestions(search)
        
