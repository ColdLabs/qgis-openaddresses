"""Where the addresses are, and which sources' licences apply to an area.

OpenAddresses publishes every address in one global PMTiles file, which does
not say which source each address came from. The plugin ships an index of
every source's bounding box and licence (sources.json, rebuilt by
tools/build_index.py), so it can list the sources that may cover an area."""

import functools
import json
import os
from dataclasses import dataclass

from osgeo import ogr

FABRIC_URL = 'https://v2.openaddresses.io/fabric/addresses.pmtiles'
INDEX = os.path.join(os.path.dirname(__file__), 'sources.json')
OUTLINES = os.path.join(os.path.dirname(__file__), 'outlines.json')


@dataclass
class Source:
    name: str  # e.g. us/ny/city_of_new_york
    layer: str  # e.g. city
    bbox: tuple  # xmin, ymin, xmax, ymax in EPSG:4326
    licence: str = ''
    url: str = ''
    attribution: str = ''
    share_alike: object = None  # True, False or None when not stated
    website: str = ''
    estimated: bool = False  # box from the area the source names, not its data

    def coverage_note(self, estimated_note, stretched_note):
        if self.estimated:
            return estimated_note
        return stretched_note if self.stretched else ''

    @property
    def stretched(self):
        """Whether the box is far larger than this kind of source can be.

        Stray points (at 0,0, at the South Pole, or with a flipped sign)
        stretch some boxes across oceans. Such a source is still listed, since
        it may apply, but flagged."""
        if self.layer == 'country':
            return False
        limit = 30 if self.layer.startswith('state') else 20
        x0, y0, x1, y1 = self.bbox
        return max(x1 - x0, y1 - y0) > limit


@functools.lru_cache(maxsize=1)
def _index():
    with open(INDEX) as f:
        return json.load(f)


@functools.lru_cache(maxsize=1)
def _outlines():
    with open(OUTLINES) as f:
        return json.load(f)


@functools.lru_cache(maxsize=None)
def _outline(code):
    geo = _outlines().get(code)
    return geo and ogr.CreateGeometryFromJson(json.dumps(geo))


def in_its_region(source, area_wkt):
    """Whether the area touches the state, or else the country, the source
    belongs to.

    A bounding box alone lists es/countrywide for Porto, and boxes stretched
    by stray points list sources oceans away. A source with no outline for
    its state or country is kept."""
    parts = source.name.split('/')
    outline = _outline('/'.join(parts[:2])) or _outline(parts[0])
    area = ogr.CreateGeometryFromWkt(area_wkt)
    return not outline or outline.Intersects(area)


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
                info.get('website', ''),
                info.get('estimated', False),
            )
        )
    return found
