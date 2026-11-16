#!/usr/bin/env python3
"""Rebuild openaddresses_downloader/sources.json, the source index shipped
with the plugin.

For every OpenAddresses address layer that has map tiles: its bounding box
(from its latest job) and its licence (from the source file in the
openaddresses/openaddresses repository). Run before each release:

    python3 tools/build_index.py

Active sources that have run output but no map tiles (often ones whose
latest good run predates tiles) have no job box. They are added with
"estimated": true and a box taken from the area their source file names: its
coverage geometry, its US county (Natural Earth counties), or its state or
country (Natural Earth). Cities and counties that name no area finer than
their state are left out and printed.

Standard library only. Makes one request per source to the OpenAddresses
API, eight at a time. With --keep-boxes it only refreshes the licence fields
and websites from the repository, keeps the current boxes, re-estimates the
sources without tiles, and makes one API call (the list of layers)."""

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
NE = (
    'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master'
    '/geojson/ne_%s.geojson'
)
POINT_PAD = 0.25
LOCAL_LAYERS = {'city', 'county', 'town'}
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
    """{key: licence fields and website} from the source files, and
    {key: stated coverage} for every active address layer."""
    found = {}
    areas = {}
    tar = tarfile.open(fileobj=io.BytesIO(get(REPO_TARBALL)))
    for member in tar:
        # <repo>-master/sources/<source>.json
        path = member.name.split('/', 1)[-1]
        if not (path.startswith('sources/') and path.endswith('.json')):
            continue
        source = path[len('sources/') : -len('.json')]
        doc = json.load(tar.extractfile(member))
        for layer in doc.get('layers', {}).get('addresses', []):
            if not layer.get('skip'):
                areas[key(source, layer.get('name'))] = doc.get('coverage', {})
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
    return found, areas


def box_of(geometry):
    coords = geometry['coordinates']
    while isinstance(coords[0][0], list):
        coords = [p for part in coords for p in part]
    if not isinstance(coords[0], list):
        coords = [coords]
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return [round(v, 5) for v in (min(xs), min(ys), max(xs), max(ys))]


def regions():
    """{code: box} for countries (pt), states (us/ny) and US counties by
    FIPS code (36047), from Natural Earth."""
    found = {}
    layers = [
        ('50m_admin_0_countries', lambda p: p['ISO_A2_EH'].lower()),
        (
            '10m_admin_1_states_provinces',
            lambda p: (p['iso_3166_2'] or '').lower().replace('-', '/'),
        ),
        ('10m_admin_2_counties', lambda p: p['CODE_LOCAL']),
    ]
    for layer, code in layers:
        for feat in json.loads(get(NE % layer))['features']:
            if feat['geometry']:
                found[code(feat['properties'])] = box_of(feat['geometry'])
    return found


def estimate(k, coverage, boxes):
    """A box for a source from the area its source file names, finest
    first, or None when a city or county names nothing finer than its state."""
    geometry = coverage.get('geometry')
    if geometry and geometry['type'] == 'Point':
        x, y = geometry['coordinates'][:2]
        return [round(v, 5) for v in (
            x - POINT_PAD, y - POINT_PAD, x + POINT_PAD, y + POINT_PAD)]
    if geometry:
        return box_of(geometry)
    geoid = str(coverage.get('US Census', {}).get('geoid', ''))
    if len(geoid) == 5 and geoid in boxes:
        return boxes[geoid]
    name, layer = k.split('|')
    if layer in LOCAL_LAYERS:
        # A state-wide box would list a town for the whole state.
        return None
    iso = coverage.get('ISO 3166', {}).get('alpha2', '').lower()
    if '-' in iso and iso.replace('-', '/') in boxes:
        return boxes[iso.replace('-', '/')]
    parts = name.split('/')
    return boxes.get('/'.join(parts[:2])) or boxes.get(parts[0])


def layers():
    """Every address layer the OpenAddresses API knows, with its outputs."""
    return json.loads(get(API + '/data?layer=addresses'))


def add_estimated(sources, areas, lic, known):
    """Add the active layers that have run output but no box. A layer with
    no output has never run, so its addresses are not in the global file."""
    ran = {key(d['source'], d['name']) for d in known if d['output'].get('output')}
    boxes = regions()
    for k, coverage in areas.items():
        if k in sources or k not in ran:
            continue
        box = estimate(k, coverage, boxes)
        if box is None:
            print('not listed, no area finer than its state:', k)
            continue
        sources[k] = dict(bbox=box, estimated=True, **lic.get(k, {}))


def bbox(job):
    ring = json.loads(get('%s/job/%d' % (API, job)))['bounds']['coordinates']
    xs = [p[0] for p in ring[0]]
    ys = [p[1] for p in ring[0]]
    return [round(v, 5) for v in (min(xs), min(ys), max(xs), max(ys))]


def keep_boxes():
    with open(OUT) as f:
        index = json.load(f)
    lic, areas = licences()
    sources = {
        k: dict(bbox=v['bbox'], **lic.get(k, {}))
        for k, v in index['sources'].items()
        if not v.get('estimated')
    }
    add_estimated(sources, areas, lic, layers())
    index['sources'] = dict(sorted(sources.items()))
    return index


def main():
    if '--keep-boxes' in sys.argv[1:]:
        write(keep_boxes())
        return
    known = layers()
    tiled = [d for d in known if d['output'].get('pmtiles')]
    lic, areas = licences()
    with ThreadPoolExecutor(8) as pool:
        boxes = list(pool.map(lambda d: bbox(d['job']), tiled))
    sources = {}
    for d, box in zip(tiled, boxes):
        k = key(d['source'], d['name'])
        sources[k] = dict(bbox=box, **lic.get(k, {}))
    add_estimated(sources, areas, lic, known)
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
    estimated = sum(1 for s in sources.values() if s.get('estimated'))
    print(
        '%d sources (%d estimated), %d with licence information -> %s'
        % (len(sources), estimated, with_licence, os.path.normpath(OUT))
    )


if __name__ == '__main__':
    main()
