"""Which OpenAddresses sources cover an area, and where their tiles are.

The plugin ships an index of every address source's bounding box and licence
(sources.json, rebuilt by tools/build_index.py). Each run asks the
OpenAddresses API for the current job of every source, since tiles are
published per job. Sources newer than the index get their bounds from the API
once and are cached in the QGIS profile."""

import json
import os
from dataclasses import dataclass

from qgis.core import QgsBlockingNetworkRequest
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

API = 'https://batch.openaddresses.io/api'
TILES_URL = 'https://v2.openaddresses.io/batch-prod/job/%d/source.pmtiles'
INDEX = os.path.join(os.path.dirname(__file__), 'sources.json')


class CatalogError(Exception):
    pass


@dataclass
class Source:
    name: str  # e.g. us/ny/city_of_new_york
    layer: str  # e.g. city
    job: int
    bbox: tuple  # xmin, ymin, xmax, ymax in EPSG:4326
    licence: str = ''
    url: str = ''
    attribution: str = ''
    share_alike: object = None  # True, False or None when not stated

    @property
    def tiles_url(self):
        return TILES_URL % self.job


def _get_json(path):
    blocking = QgsBlockingNetworkRequest()
    error = blocking.get(QNetworkRequest(QUrl(API + path)))
    if error != QgsBlockingNetworkRequest.ErrorCode.NoError:
        raise CatalogError('%s%s: %s' % (API, path, blocking.errorMessage()))
    return json.loads(bytes(blocking.reply().content()))


def _current_jobs():
    """{(source, layer): job} for address layers that have map tiles."""
    return {
        (d['source'], d['name']): d['job']
        for d in _get_json('/data?layer=addresses')
        if d['output'].get('pmtiles')
    }


def _job_bbox(job):
    ring = _get_json('/job/%d' % job)['bounds']['coordinates'][0]
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return [min(xs), min(ys), max(xs), max(ys)]


def _load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def sources_in(xmin, ymin, xmax, ymax, cache_dir):
    """Current sources whose bounding box touches the lat/lng box."""
    index = _load(INDEX)['sources']
    extra_path = os.path.join(cache_dir, 'extra_bounds.json')
    extra = _load(extra_path)
    found = []
    for (name, layer), job in sorted(_current_jobs().items()):
        k = '%s|%s' % (name, layer)
        info = index.get(k)
        if info is None:
            if k not in extra:
                extra[k] = _job_bbox(job)
                os.makedirs(cache_dir, exist_ok=True)
                with open(extra_path, 'w') as f:
                    json.dump(extra, f)
            info = {'bbox': extra[k]}
        x0, y0, x1, y1 = info['bbox']
        if x0 > xmax or x1 < xmin or y0 > ymax or y1 < ymin:
            continue
        found.append(
            Source(
                name,
                layer,
                job,
                (x0, y0, x1, y1),
                info.get('licence', ''),
                info.get('url', ''),
                info.get('attribution', ''),
                info.get('share_alike'),
            )
        )
    return found
