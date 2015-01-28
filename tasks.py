import re
import os
import codecs
from functools import partial
import luigi
from requests_futures.sessions import FuturesSession

import analysis


CFG = luigi.configuration.get_config()
conf = partial(CFG.get, 'lastfm')

API_KEY = conf('api_key')
API_URL = conf('api_url', 'http://ws.audioscrobbler.com/2.0/')
FORMAT = 'json'
RAW_DATA_DIR = conf('raw_data_dir', 'data.raw')
PROC_DATA_DIR = conf('proc_data_dir', 'data.proc')
POOL_SIZE = int(conf('pool_size', 10))
ARTIST_LIMIT = int(conf('top_artist_limit', 1000))

UTF8Reader = codecs.getreader('utf8')
UTF8Writer = codecs.getwriter('utf8')

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


class AnalyzeTagSimilarities(luigi.Task):
    # sensitivity = luigi.IntegerParameter(default=)

    def requires(self):
        return LoadTopTags()

    def output(self):
        path = partial(os.path.join, PROC_DATA_DIR)
        return [luigi.LocalTarget(path('similarities.csv')),
                luigi.LocalTarget(path('artists')),
                luigi.LocalTarget(path('tags'))]

    def run(self):
        # analyze tags
        with self.input().open() as raw_tags_stream:
            raw_tags_stream = UTF8Reader(raw_tags_stream)
            similarities, artists, tags = \
                analysis.analyze_tags(raw_tags_stream)

        # write out similarities
        with self.output()[0].open('w') as out:
            for tag_i, tag_j_similarity in similarities.iteritems():
                for tag_j, similarity in tag_j_similarity.iteritems():
                    out.write('{},{},{}'.format(tag_i, tag_j, similarity))
                    out.write('\n')

        # write out artists
        with self.output()[1].open('w') as out:
            out = UTF8Writer(out)
            for artist in artists:
                out.write(artist)
                out.write('\n')

        # write out tags
        with self.output()[2].open('w') as out:
            out = UTF8Writer(out)
            for tag in tags:
                out.write(tag)
                out.write('\n')


if __name__ == '__main__':
    luigi.run()
