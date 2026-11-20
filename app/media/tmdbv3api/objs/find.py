from typing import ClassVar
from app.media.tmdbv3api.tmdb import TMDb


class Find(TMDb):
    _urls: ClassVar[dict] = {
        "find": "/find/%s"
    }

    def find_by_imdbid(self, imdbid):
        return self._call(
                self._urls["find"] % imdbid,
                "external_source=imdb_id")
