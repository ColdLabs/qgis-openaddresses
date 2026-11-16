#!/usr/bin/env python3
"""Rebuild openaddresses_downloader/sources.json, the source index shipped
with the plugin.

For every OpenAddresses address layer that has map tiles: its bounding box
(from its latest job) and its licence (from the source file in the
openaddresses/openaddresses repository). Run before each release:

    python3 tools/build_index.py

Standard library only. Makes one request per source to the OpenAddresses
API, eight at a time. With --keep-boxes it only refreshes the licence fields
and websites from the repository, keeps the current sources and boxes, and
makes no API calls."""

import datetime
import io
import json
import os
import sys
import tarfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = 'https://batch.openaddresses.io/api'
REPO_TARBALL = (
    'https://codeload.github.com/openaddresses/openaddresses'
    '/tar.gz/refs/heads/master'
)
OUT = os.path.join(
    os.path.dirname(__file__), '..', 'openaddresses_downloader', 'sources.json'
)


def get(url):
    req = urllib.request.Request(
        url, headers={'User-Agent': 'qgis-openaddresses index builder'}
    )
    with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310
        return r.read()


def key(source, name):
    return '%s|%s' % (source, name)


def licences():
    """{key: licence fields and website} from the source files."""
    found = {}
    tar = tarfile.open(fileobj=io.BytesIO(get(REPO_TARBALL)))
    for member in tar:
        # <repo>-master/sources/<source>.json
        path = member.name.split('/', 1)[-1]
        if not (path.startswith('sources/') and path.endswith('.json')):
            continue
        source = path[len('sources/') : -len('.json')]
        doc = json.load(tar.extractfile(member))
        for layer in doc.get('layers', {}).get('addresses', []):
            entry = {}
            if layer.get('website'):
                entry['website'] = layer['website']
            lic = layer.get('license') or {}
            if isinstance(lic, str):
                lic = {'url': lic}
            if lic.get('text'):
                entry['licence'] = lic['text']
            if lic.get('url'):
                entry['url'] = lic['url']
            if lic.get('attribution'):
                entry['attribution'] = (
                    lic.get('attribution name') or 'required'
                )
            share_alike = lic.get('share-alike', lic.get('share alike'))
            if share_alike is not None:
                entry['share_alike'] = bool(share_alike)
            if entry:
                found[key(source, layer.get('name'))] = entry
    return found


def bbox(job):
    ring = json.loads(get('%s/job/%d' % (API, job)))['bounds']['coordinates']
    xs = [p[0] for p in ring[0]]
    ys = [p[1] for p in ring[0]]
    return [round(v, 5) for v in (min(xs), min(ys), max(xs), max(ys))]


def keep_boxes():
    with open(OUT) as f:
        index = json.load(f)
    lic = licences()
    index['sources'] = {
        k: dict(bbox=v['bbox'], **lic.get(k, {}))
        for k, v in index['sources'].items()
    }
    return index


def main():
    if '--keep-boxes' in sys.argv[1:]:
        write(keep_boxes())
        return
    layers = [
        d
        for d in json.loads(get(API + '/data?layer=addresses'))
        if d['output'].get('pmtiles')
    ]
    lic = licences()
    with ThreadPoolExecutor(8) as pool:
        boxes = list(pool.map(lambda d: bbox(d['job']), layers))
    sources = {}
    for d, box in zip(layers, boxes):
        k = key(d['source'], d['name'])
        sources[k] = dict(bbox=box, **lic.get(k, {}))
    write(
        {
            'built': datetime.date.today().isoformat(),
            'sources': dict(sorted(sources.items())),
        }
    )


def write(index):
    sources = index['sources']
    with open(OUT, 'w') as f:
        json.dump(index, f, separators=(',', ':'), ensure_ascii=False)
    with_licence = sum(
        1 for s in sources.values() if 'licence' in s or 'url' in s
    )
    print(
        '%d sources, %d with licence information -> %s'
        % (len(sources), with_licence, os.path.normpath(OUT))
    )


if __name__ == '__main__':
    main()
