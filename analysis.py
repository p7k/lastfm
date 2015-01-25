import json
import codecs
import math
import string
from collections import OrderedDict


def normalize_tag_term(tag, exclude_punctuation=False):
    """a little naive in stripping all punctuation.
    stemming would deal with sementically identical syntax variations:
    electronic, electronica, electro"""
    tag = tag.strip().lower()
    if exclude_punctuation:
        tag = tag.translate(dict.fromkeys(map(ord, string.punctuation)))
    return tag


def load_tags_data(tags_file, encoding='utf-8'):
    artist_artist_id = OrderedDict()  # artists -> artist_id
    tag_tag_id = OrderedDict()        # tags -> artist_id
    artist_tags = dict()       # artist_id -> {tag}
    tag_artists = dict()       # tag -> {artist_id}
    tag_artist_count = dict()  # tag -> artist_id -> count

    # load data
    with codecs.open(tags_file, 'r') as f:
        for line in f:
            # decode json
            top_tags = json.loads(line)['toptags']
            # artists (documents) store only unique artists
            artist = top_tags['@attr']['artist']
            artist_id = artist_artist_id.setdefault(artist,
                                                    len(artist_artist_id))
            # tag name and count (terms and frequency)
            for raw_tag in top_tags['tag']:
                tag = normalize_tag_term(raw_tag['name'])
                # skip empty tags
                if not tag:
                    print 'warning: skipping empty tag [raw: "{}"]'.format(
                        raw_tag['name'])
                    continue
                # store only unique tags
                tag_id = tag_tag_id.setdefault(tag, len(tag_tag_id))
                # store tag counts for each artist
                count = int(raw_tag['count'])
                tag_artist_count.setdefault(tag_id, dict())[artist_id] = count
                # store artist tag sets
                artist_tags.setdefault(artist_id, set()).add(tag_id)
                # store tag artist sets
                tag_artists.setdefault(tag_id, set()).add(artist_id)

    return (artist_artist_id, tag_tag_id,
            artist_tags, tag_artists, tag_artist_count)


artist_artist_id, tag_tag_id, artist_tags, tag_artists, tag_artist_count = \
    load_tags_data('data.raw/top_tags.json')

artist_names = tuple(artist_artist_id.iterkeys())
tag_names = tuple(tag_tag_id.iterkeys())


# ##### local tag (term) weight [ normalized term frequency ]


# looks like they've already normalized local weights 'count' is always between
# 0-100 zero-based nature of that normalization may cause issues with rest of
# the analysis might be worth experinenting and normalizing it further with log
def build_local_tag_weights(tag_artist_count):
    ret = dict()
    for tag, artist_count in tag_artist_count.iteritems():
        for artist, count in artist_count.iteritems():
            ret.setdefault(tag, dict())[artist] = (math.lgamma(count + 1) + .1)
#             ret.setdefault(tag, dict())[artist] = count + 1
    return ret


local_tag_weights = build_local_tag_weights(tag_artist_count)


# ##### global tag (term) weight (inverse document frequency)

# penalize generic tags

def idf(n_docs, n_docs_with_term):
    return math.log(float(n_docs) / n_docs_with_term)


def build_global_tag_weights(n_artists, tag_artists):
    """returns dict tag -> weight"""
    ret = dict()
    for tag, artists in tag_artists.iteritems():
        ret[tag] = idf(n_artists, len(artists))
    return ret


global_tag_weights = build_global_tag_weights(len(artist_names), tag_artists)


# ##### compensate for document length (artist tag count) differences using
# ##### cosine normalization

# used to correct discrepancies in document lengths.
# E.g. In case of tagging systems, a resource that has been given more tags,
# will be favoured if weights are not normalized.
# Since it is not always true that a resource that has been given more tags
# is more relevant than a resource with lesser number of tags.
# Hence, it is useful to normalize the document vectors so that documents are
# not favoured based on their lengths.

def cos_norm(global_local_tag_weights):
    return 1. / math.sqrt(sum((gtw * ltw)**2 for gtw, ltw in
                              global_local_tag_weights))


def build_normalized_artist_weights(artist_tags, local_tag_weights,
                                    global_tag_weights):
    """returns dict artist_id -> combined_weight"""
    ret = dict()
    for artist_id, tags in artist_tags.iteritems():
        gtw_ltw = ((global_tag_weights[tag], local_tag_weights[tag][artist_id])
                   for tag in tags)
        ret[artist_id] = cos_norm(gtw_ltw)
    return ret

normalized_artist_weights = build_normalized_artist_weights(artist_tags,
                                                            local_tag_weights,
                                                            global_tag_weights)


# ##### combined weights (artists and tags)

def combined_weight(local_tag_weight, global_tag_weight,
                    normalized_artist_weight):
    return local_tag_weight * global_tag_weight * normalized_artist_weight


def build_combined_weights(tag_artists, local_tag_weights, global_tag_weights,
                           normalized_artist_weights):
    """return dict tag -> artist -> weight"""
    ret = dict()
    for tag, artists in tag_artists.iteritems():
        for artist in artists:
            weight = combined_weight(local_tag_weights[tag][artist],
                                     global_tag_weights[tag],
                                     normalized_artist_weights[artist])
            weight = int(weight * 1e3)
            if weight:
                ret.setdefault(tag, dict())[artist] = weight
    return ret


combined_weights = build_combined_weights(tag_artists, local_tag_weights,
                                          global_tag_weights,
                                          normalized_artist_weights)


# ##### dice similarities

def build_weighted_dice_similarities(tag_artists, combined_weights):
    n_tags = len(tag_names)
    tag_artists = tuple(artists for _, artists in
                        sorted(tag_artists.iteritems()))
    empty = {}
    ret = dict()

    # weighted dice similarity calc
    for tag_i in xrange(n_tags):
        artists_i = tag_artists[tag_i]
        for tag_j in xrange(tag_i + 1, n_tags):
            artists_j = tag_artists[tag_j]
            # common artists; if none, will be zero, hence skip
            common_artists = artists_i & artists_j
            if not common_artists:
                continue
            # sum of element-wise multiplication of weights for tag_i & tag_j
            # for common artists; skip zeros
            sum_common = 0
            for common_artist in common_artists:
                cwi = combined_weights.get(tag_i, empty).get(common_artist, 0)
                cwj = combined_weights.get(tag_j, empty).get(common_artist, 0)
                sum_common += cwi * cwj
            if sum_common == 0:
                continue
            # calc weight sums for tag_i and tag_j across all artists
            sum_i = sum(combined_weights[tag_i].itervalues())
            sum_j = sum(combined_weights[tag_j].itervalues())
            similarity = sum_common // (sum_i + sum_j)
            if similarity == 0:
                continue
            ret.setdefault(tag_i, dict())[tag_j] = similarity
    return ret


weighted_dice_similarities = build_weighted_dice_similarities(tag_artists,
                                                              combined_weights)


# #### persist to disk

with open('data.proc/tag_similarities.csv', 'w') as f:
    for tag_i, tag_j_similarity in weighted_dice_similarities.iteritems():
        for tag_j, similarity in tag_j_similarity.iteritems():
            f.write(",".join(map(str, (tag_i, tag_j, similarity))))
            f.write('\n')


with codecs.open('data.proc/artists', 'w', encoding='utf-8') as f:
    for artist_name in artist_names:
        f.write(artist_name)
        f.write('\n')


with codecs.open('data.proc/tags', 'w', encoding='utf-8') as f:
    for tag_name in tag_names:
        f.write(tag_name)
        f.write('\n')
