import re
import os
from functools import partial
import luigi
import grequests

CFG = luigi.configuration.get_config()
conf = partial(CFG.get, 'lastfm')
conf_int = partial(CFG.getint, 'lastfm')

API_KEY = conf('api_key')
API_URL = conf('api_url', 'http://ws.audioscrobbler.com/2.0/')
FORMAT = 'json'
RAW_DATA_DIR = conf('raw_data_dir', 'data.raw')
CHUNK_SIZE = conf_int('stream_chunk_bytes', pow(2, 13))

SESH = grequests.Session()
SESH.params.update({'api_key': API_KEY, 'format': FORMAT})


def api_get(**kwargs):
    return grequests.get(API_URL, session=SESH, stream=True, params=kwargs)


class LoadTopArtists(luigi.Task):
    """Loads top artists using Last.fm API"""
    api_method = 'chart.getTopArtists'
    limit = conf_int('top_artist_limit', 1000)

    def output(self):
        filename = 'top_artists.{ext}'.format(ext=FORMAT)
        return luigi.LocalTarget(os.path.join(RAW_DATA_DIR, filename))

    def run(self):
        # send the request
        req = api_get(method=self.api_method, limit=self.limit)
        r = grequests.send(req).get()
        r.raise_for_status()
        # stream the response content into a file
        with self.output().open('w') as output:
            for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                output.write(chunk)


class LoadTopTags(luigi.Task):
    """Loads top tags for the top artists using Last.fm API"""
    api_method = 'artist.getTopTags'
    mbid_re = re.compile("{h}{{8}}-{h}{{4}}-{h}{{4}}-{h}{{4}}-{h}{{12}}".format(
        h="[a-f0-9]"), re.IGNORECASE)

    def requires(self):
        LoadTopArtists()

    def output(self):
        filename = 'top_tags.{ext}'.format(ext=FORMAT)
        return luigi.LocalTarget(os.path.join(RAW_DATA_DIR, filename))

    def run(self):
        # parse mbid(s) from artists file
        with self.input().open('r') as artists:
            mbids = self.mbid_re.findall(f.read())
        # send the request
        r = api_get(method=self.api_method)
        r.raise_for_status()
        # stream the response content into a file
        with self.output().open('w') as output:
            for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                output.write(chunk)


if __name__ == '__main__':
    luigi.run()
