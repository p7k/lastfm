import re
import os
from functools import partial
import luigi
from requests_futures.sessions import FuturesSession

CFG = luigi.configuration.get_config()
conf = partial(CFG.get, 'lastfm')

API_KEY = conf('api_key')
API_URL = conf('api_url', 'http://ws.audioscrobbler.com/2.0/')
FORMAT = 'json'
RAW_DATA_DIR = conf('raw_data_dir', 'data.raw')
POOL_SIZE = int(conf('pool_size', 10))
ARTIST_LIMIT = int(conf('top_artist_limit', 1000))

SESH = FuturesSession(max_workers=POOL_SIZE)
SESH.params.update({'api_key': API_KEY, 'format': FORMAT})


def api_get(**kwargs):
    return SESH.get(API_URL, params=kwargs)


class LoadTopArtists(luigi.Task):
    """Loads top artists using Last.fm API"""
    api_method = 'chart.getTopArtists'

    def output(self):
        filename = 'top_artists.{ext}'.format(ext=FORMAT)
        return luigi.LocalTarget(os.path.join(RAW_DATA_DIR, filename))

    def run(self):
        # send the request
        fut = api_get(method=self.api_method, limit=ARTIST_LIMIT)
        response = fut.result()
        response.raise_for_status()
        # write response content into a file
        with self.output().open('w') as out:
            out.write(response.content)


class LoadTopTags(luigi.Task):
    """Loads top tags for the top artists using Last.fm API
    Note: some artists are missing mbids
          confirm with ` cat top_artists.json | egrep -o -e'mbid":""' | wc `
    """
    api_method = 'artist.getTopTags'
    mbid_re = re.compile(
        "{h}{{8}}-{h}{{4}}-{h}{{4}}-{h}{{4}}-{h}{{12}}".format(h="[a-f0-9]"),
        re.IGNORECASE)

    def requires(self):
        return LoadTopArtists()

    def output(self):
        filename = 'top_tags.{ext}'.format(ext=FORMAT)
        return luigi.LocalTarget(os.path.join(RAW_DATA_DIR, filename))

    def run(self):
        # parse mbid(s) from artists file
        with self.input().open('r') as artists:
            mbids = self.mbid_re.findall(artists.read())
        # prepare requests
        futs = [api_get(method=self.api_method, mbid=mbid) for mbid in mbids]
        # stream the response content into a file
        with self.output().open('w') as out:
            for fut in futs:
                response = fut.result()
                response.raise_for_status()
                out.write(response.content)


if __name__ == '__main__':
    luigi.run()
