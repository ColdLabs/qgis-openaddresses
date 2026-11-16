"""Where the addresses are, and which sources' licences apply to an area.

OpenAddresses publishes every address in one global PMTiles file, which does
not say which source each address came from. The plugin ships an index of
every source's bounding box and licence (sources.json, rebuilt by
tools/build_index.py), so it can list the sources that may cover an area."""

import functools
import json
import os
from dataclasses import dataclass

FABRIC_URL = 'https://v2.openaddresses.io/fabric/addresses.pmtiles'
INDEX = os.path.join(os.path.dirname(__file__), 'sources.json')


@dataclass
class Source:
    name: str  # e.g. us/ny/city_of_new_york
    layer: str  # e.g. city
    bbox: tuple  # xmin, ymin, xmax, ymax in EPSG:4326
    licence: str = ''
    url: str = ''
    attribution: str = ''
    share_alike: object = None  # True, False or None when not stated


@functools.lru_cache(maxsize=1)
def _index():
    with open(INDEX) as f:
        return json.load(f)


def built():
    """The date the index was built, as YYYY-MM-DD."""
    return _index()['built']


def clean_bbox(b):
    """The bbox as xmin, ymin, xmax, ymax, or None when it cannot be placed.

    A few OpenAddresses jobs report bounds in projected units, or ordered
    xmin, xmax, ymin, ymax. Boxes stretched by outlier points are kept: an
    extra licence row is safer than a missing one. Boxes crossing the
    antimeridian have xmax above 180."""
    x0, y0, x1, y1 = b
    if x1 - x0 > 20 and y1 - y0 > 20 and 0 <= y0 - x0 < 2 and 0 <= y1 - x1 < 2:
        x0, y0, x1, y1 = x0, x1, y0, y1
    if not (-180 <= x0 <= x1 <= 360 and -90 <= y0 <= y1 <= 90):
        return None
    return x0, y0, x1, y1


def sources_in(xmin, ymin, xmax, ymax):
    """Indexed sources whose bounding box touches the lat/lng box."""
    found = []
    for key, info in sorted(_index()['sources'].items()):
        box = clean_bbox(info['bbox'])
        if box is None:
            continue
        x0, y0, x1, y1 = box
        if y0 > ymax or y1 < ymin:
            continue
        if (x0 > xmax or x1 < xmin) and (x0 > xmax + 360 or x1 < xmin + 360):
            continue
        name, layer = key.split('|')
        found.append(
            Source(
                name,
                layer,
                (x0, y0, x1, y1),
                info.get('licence', ''),
                info.get('url', ''),
                info.get('attribution', ''),
                info.get('share_alike'),
            )
        )
    return found
