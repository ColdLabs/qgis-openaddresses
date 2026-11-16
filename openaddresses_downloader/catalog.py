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


def sources_in(xmin, ymin, xmax, ymax):
    """Indexed sources whose bounding box touches the lat/lng box."""
    found = []
    for key, info in sorted(_index()['sources'].items()):
        x0, y0, x1, y1 = info['bbox']
        if x0 > xmax or x1 < xmin or y0 > ymax or y1 < ymin:
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
