from fastapi import APIRouter
from app.staticMusic.service import StaticMusicAPI

router = APIRouter()
staticMusicAPI = StaticMusicAPI()


@router.get("/songs/{title}")
def getSong(title:str):
    return staticMusicAPI.getSong(title)

@router.get("/metadata/{videoId}")
def getSongMetadata(videoId:str):
    return staticMusicAPI.getSongMetadata(videoId)

@router.get("/artist/{artist}")
def getArtist(artist:str):
    return staticMusicAPI.getArtist(artist)

@router.get("/album/{albumId}")
def getAlbum(albumId:str):
    return staticMusicAPI.getAlbum(albumId)

@router.get("/nextSongs/{currentVideoId}")
def getNextSongs(currentVideoId:str):
    return staticMusicAPI.getNextSongs(currentVideoId)

@router.get("/lyrics/{songId}")
def getLyrics(songId:str):
    return staticMusicAPI.getLyrics(songId)

@router.get("/suggestions/{search}")
def getSearchSuggestions(search:str):
    return staticMusicAPI.getSearchSuggestions(search)