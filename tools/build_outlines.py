#!/usr/bin/env python3
"""Rebuild openaddresses_downloader/outlines.json: simplified outlines of the
countries and states that have OpenAddresses sources, keyed the way source
names start (pt for pt/countrywide, us/ny for us/ny/statewide).

The plugin uses them to drop sources whose bounding box touches an area
outside their country or state, such as es/countrywide for Porto. Outlines
come from Natural Earth (public domain), 1:10m, grown by about 1 km so
the coast still counts as inside after simplifying. The growth is cut back
where it reaches a neighbouring state or country, so a Kansas City, Kansas
box does not list Missouri sources. It stays small so it does not reach
across a river or harbour: Manhattan is about 1.3 km from New Jersey. Needs GDAL's Python bindings, for example QGIS's own Python:

    /Applications/QGIS.app/Contents/MacOS/python tools/build_outlines.py"""

import json
import os
import urllib.request

from osgeo import ogr

NE = (
    'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master'
    '/geojson/ne_10m_%s.geojson'
)
HERE = os.path.join(os.path.dirname(__file__), '..', 'openaddresses_downloader')
GROW = 0.01
SIMPLIFY = 0.005
NEIGHBOUR_SIMPLIFY = 0.002


def features(layer):
    req = urllib.request.Request(
        NE % layer, headers={'User-Agent': 'qgis-openaddresses'}
    )
    with urllib.request.urlopen(req, timeout=120) as r:  # nosec B310
        return json.load(r)['features']


def geom(feature):
    g = ogr.CreateGeometryFromJson(json.dumps(feature['geometry']))
    return g.SimplifyPreserveTopology(NEIGHBOUR_SIMPLIFY).Buffer(0)


def outline(own, neighbours):
    g = own.Buffer(GROW, 4).SimplifyPreserveTopology(SIMPLIFY)
    for other in neighbours:
        if other.Intersects(g):
            g = g.Difference(other)
    # Rounding can collapse a tiny ring; a zero buffer repairs it.
    g = ogr.CreateGeometryFromJson(g.ExportToJson(['COORDINATE_PRECISION=3']))
    if not g.IsValid():
        g = g.Buffer(0)
    return json.loads(g.ExportToJson(['COORDINATE_PRECISION=3']))


def main():
    with open(os.path.join(HERE, 'sources.json')) as f:
        names = [k.split('|')[0].split('/') for k in json.load(f)['sources']]
    wanted = {n[0] for n in names} | {'/'.join(n[:2]) for n in names}
    out = {}
    countries = [
        (f['properties']['ISO_A2_EH'].lower(), geom(f))
        for f in features('admin_0_countries')
    ]
    for code, g in countries:
        if code in wanted:
            out[code] = outline(g, [o for c, o in countries if c != code])
    states = [
        (f['properties']['iso_3166_2'].lower().replace('-', '/'), geom(f))
        for f in features('admin_1_states_provinces')
    ]
    for code, g in states:
        if code in wanted:
            out[code] = outline(g, [o for c, o in states if c != code])
    countries = {n[0] for n in names}
    missing = sorted(countries - set(out))
    path = os.path.normpath(os.path.join(HERE, 'outlines.json'))
    with open(path, 'w') as f:
        json.dump(dict(sorted(out.items())), f, separators=(',', ':'))
    print(
        '%d countries, %d states -> %s; countries missing: %s'
        % (
            len(countries) - len(missing),
            len(out) - len(countries) + len(missing),
            path,
            missing or 'none',
        )
    )


if __name__ == '__main__':
    main()
