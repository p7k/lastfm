#!/usr/bin/env python

import argparse
import os
from functools import partial
from grequests import Session, get, imap, send

API_URL = 'http://ws.audioscrobbler.com/2.0/'

RESPONSE_FORMAT = 'json'
TOP_ARTISTS_LIMIT = 1000
TOP_ARTISTS_FILENAME = 'top_artists.json'
TOP_TAGS_FILENAME = 'top_tags.json'
DATA_DIR = 'data.raw'
POOL_SIZE = 10
CHUNK_BYTES = pow(2, 13)


def get_args():
    parser = argparse.ArgumentParser(description='Loads LastFM artists & tags')
    parser.add_argument('--key', dest='api_key', type=str,
                        default='54bc9960fd879790b3541d5190bd8200',
                        help='last.fm api key')
    parser.add_argument('--n', type=int, dest='limit',
                        default=TOP_ARTISTS_LIMIT,
                        help='number of top artists (default: {})'.format(
                            TOP_ARTISTS_LIMIT))
    parser.add_argument('data_dir', nargs='?',
                        default=DATA_DIR,
                        help='destination directory (default: {})'.format(
                            DATA_DIR))
    parser.add_argument('--format', dest='format', type=str,
                        default='json',
                        help='format of api responses (default: {})'.format(
                            RESPONSE_FORMAT))
    parser.add_argument('--chunk', dest='chunk_size', type=int,
                        default=CHUNK_BYTES,
                        help='chunks of size [bytes] (default: {})'.format(
                            CHUNK_BYTES))
    parser.add_argument('--s', dest='concurrency', type=int,
                        default=CHUNK_BYTES,
                        help='max concurrent requests (default: {})'.format(
                            POOL_SIZE))
    return parser.parse_args()


def mkdir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def load_top_artists(req, limit, data_dir, filename, chunk_size):
    # send the request
    r = send(req(params={'method': 'chart.gettopartists',
                         'limit':  limit})).get()
    r.raise_for_status()
    # stream the response content into a file
    filepath = os.path.join(data_dir, filename)
    with open(filepath, 'wb') as f:
        for chunk in r.iter_content(chunk_size=chunk_size):
            f.write(chunk)
    # load mbids
    artists = r.json()['artists']['artist']
    return [a['mbid'] for a in artists]


def load_top_tags(req, mbids, data_dir, filename, concurrency, chunk_size):
    # prepare requests
    reqs = (api_get(params={'method': 'artist.gettoptags',
                            'mbid':   mbid}) for mbid in mbids)
    # stream response contents into a file
    filepath = os.path.join(data_dir, filename)
    with open(filepath, 'wb') as f:
        for r in imap(reqs, size=concurrency):
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=chunk_size):
                f.write(chunk)


if __name__ == '__main__':
    # parse args
    args = get_args()
    # make data dir
    mkdir(args.data_dir)
    # make session
    sesh = Session()
    sesh.params.update({'api_key': args.api_key,
                        'format':  args.format})
    api_get = partial(get, API_URL, session=sesh, stream=True)
    # load data
    print 'loading top artists...'
    mbids = load_top_artists(api_get, args.limit, args.data_dir,
                             TOP_ARTISTS_FILENAME,
                             args.chunk_size)
    print 'loading top tags for top artists ...'
    load_top_tags(api_get, mbids, args.data_dir,
                  TOP_TAGS_FILENAME,
                  args.concurrency, args.chunk_size)
