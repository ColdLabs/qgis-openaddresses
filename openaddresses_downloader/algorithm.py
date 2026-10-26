import math
import os

from osgeo import gdal
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsRectangle,
)
from qgis.PyQt.QtCore import QCoreApplication, QMetaType
from qgis.PyQt.QtGui import QIcon

from . import catalog

ICON = os.path.join(os.path.dirname(__file__), 'icon.svg')
WGS84 = QgsCoordinateReferenceSystem('EPSG:4326')
# OpenAddresses builds its tiles with tippecanoe up to zoom 14; only that zoom
# holds every address.
ZOOM = 14
EARTH_RADIUS = 6378137.0
ADDRESS_FIELDS = [
    'number',
    'street',
    'unit',
    'city',
    'district',
    'region',
    'postcode',
    'id',
    'accuracy',
    'hash',
]


def cache_dir():
    return os.path.join(
        QgsApplication.qgisSettingsDirPath(), 'cache', 'openaddresses'
    )


def tr(text):
    return QCoreApplication.translate('OpenAddresses', text)


def to_mercator(lng, lat):
    lat = max(-85.05112878, min(85.05112878, lat))
    return (
        math.radians(lng) * EARTH_RADIUS,
        math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * EARTH_RADIUS,
    )


def to_lnglat(x, y):
    return (
        math.degrees(x / EARTH_RADIUS),
        math.degrees(2 * math.atan(math.exp(y / EARTH_RADIUS)) - math.pi / 2),
    )


def tile_count(xmin, ymin, xmax, ymax):
    """Zoom-14 tiles covering a lat/lng box."""
    x0, y0 = to_mercator(xmin, ymin)
    x1, y1 = to_mercator(xmax, ymax)
    size = 2 * math.pi * EARTH_RADIUS / 2**ZOOM
    return (int(x1 // size) - int(x0 // size) + 1) * (
        int(y1 // size) - int(y0 // size) + 1
    )


class DownloadAddresses(QgsProcessingAlgorithm):
    EXTENT = 'EXTENT'
    AREA = 'AREA'
    MAX_TILES = 'MAX_TILES'
    OUTPUT = 'OUTPUT'

    def name(self):
        return 'download'

    def displayName(self):
        return tr('Download addresses')

    def createInstance(self):
        return DownloadAddresses()

    def icon(self):
        return QIcon(ICON)

    def shortHelpString(self):
        return tr(
            'Downloads address points from OpenAddresses for an extent or '
            'the polygons of a layer. When polygons are set they are used '
            'and the extent is ignored.\n\n'
            'Coverage varies by country and city, and is densest in the '
            'United States. Where two sources cover the same place (a city '
            'and its county), both sets of addresses are returned.\n\n'
            'Only the map tiles over the area are read, each about 2.4 km '
            'across at the equator and smaller towards the poles. The run '
            'stops before reading if the area needs more tiles than the '
            'limit.\n\n'
            'Licences: each source has its own. Every address carries its '
            'source, licence, licence URL, who to credit and whether the '
            'licence is share-alike. An empty licence means the source does '
            'not state one; check with the publisher before reusing it.\n\n'
            'This is an unofficial plugin, not made or endorsed by '
            'OpenAddresses.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterExtent(
                self.EXTENT, tr('Extent'), optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.AREA,
                tr('Area polygons (overrides the extent)'),
                [QgsProcessing.SourceType.TypeVectorPolygon],
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_TILES,
                tr('Stop if the area needs more map tiles than'),
                QgsProcessingParameterNumber.Type.Integer,
                2000,
                minValue=1,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                tr('Addresses'),
                QgsProcessing.SourceType.TypeVectorPoint,
            )
        )

    def checkParameterValues(self, parameters, context):
        if not parameters.get(self.AREA) and not parameters.get(self.EXTENT):
            return False, tr('Set an extent or a polygon layer.')
        return super().checkParameterValues(parameters, context)

    def _area(self, parameters, context):
        """The area in EPSG:4326, and whether it is a plain rectangle."""
        source = self.parameterAsSource(parameters, self.AREA, context)
        if source is None:
            geom = self.parameterAsExtentGeometry(
                parameters, self.EXTENT, context, WGS84
            )
            return geom, True
        transform = QgsCoordinateTransform(
            source.sourceCrs(), WGS84, context.transformContext()
        )
        parts = []
        for f in source.getFeatures():
            g = f.geometry()
            if g.isEmpty():
                continue
            g.transform(transform)
            parts.append(g)
        if not parts:
            raise QgsProcessingException(tr('The area layer has no polygons.'))
        return QgsGeometry.unaryUnion(parts), False

    def processAlgorithm(self, parameters, context, feedback):
        if gdal.GetDriverByName('PMTiles') is None:
            raise QgsProcessingException(
                tr(
                    'This QGIS uses GDAL {}, which cannot read PMTiles. '
                    'GDAL 3.8 or later is needed.'
                ).format(gdal.__version__)
            )
        area, is_rect = self._area(parameters, context)
        max_tiles = self.parameterAsInt(parameters, self.MAX_TILES, context)
        bbox = area.boundingBox()
        tiles = tile_count(
            bbox.xMinimum(), bbox.yMinimum(), bbox.xMaximum(), bbox.yMaximum()
        )
        if tiles > max_tiles:
            raise QgsProcessingException(
                tr(
                    'This area covers {} map tiles, over the limit of {}. '
                    'Use a smaller area or raise the limit.'
                ).format(tiles, max_tiles)
            )
        try:
            sources = catalog.sources_in(
                bbox.xMinimum(),
                bbox.yMinimum(),
                bbox.xMaximum(),
                bbox.yMaximum(),
                cache_dir(),
            )
        except catalog.CatalogError as e:
            raise QgsProcessingException(
                tr('Cannot reach OpenAddresses: {}').format(e)
            )
        # Each source is read over the part of the area it covers.
        work = []
        for src in sources:
            part = bbox.intersect(QgsRectangle(*src.bbox))
            if is_rect or area.intersects(QgsGeometry.fromRect(part)):
                work.append((src, part))
        if not work:
            raise QgsProcessingException(
                tr('OpenAddresses has no address data here.')
            )
        feedback.pushInfo(
            tr('{} source(s) may cover this area: {}').format(
                len(work),
                ', '.join('{} ({})'.format(s.name, s.layer) for s, _ in work),
            )
        )

        fields = QgsFields()
        for name in ADDRESS_FIELDS + [
            'source',
            'source_layer',
            'licence',
            'licence_url',
            'attribution',
        ]:
            fields.append(QgsField(name, QMetaType.Type.QString))
        fields.append(QgsField('share_alike', QMetaType.Type.Bool))
        sink, dest = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            Qgis.WkbType.Point,
            WGS84,
        )
        if sink is None:
            raise QgsProcessingException(tr('Set the addresses output.'))

        engine = None
        if not is_rect:
            engine = QgsGeometry.createGeometryEngine(area.constGet())
            engine.prepareGeometry()
        fast = QgsFeatureSink.Flag.FastInsert
        total = 0
        step = 100.0 / len(work)
        for n, (src, part) in enumerate(work):
            feedback.setProgressText(
                tr('Source {} of {}: {}').format(n + 1, len(work), src.name)
            )
            source_attrs = [
                src.name,
                src.layer,
                src.licence,
                src.url,
                src.attribution,
                src.share_alike,
            ]
            feedback.setProgress(step * n)
            x0, y0 = to_mercator(part.xMinimum(), part.yMinimum())
            x1, y1 = to_mercator(part.xMaximum(), part.yMaximum())
            seen = set()
            with gdal.ExceptionMgr(useExceptions=True):
                try:
                    ds = gdal.OpenEx(
                        '/vsicurl/' + src.tiles_url,
                        gdal.OF_VECTOR,
                        allowed_drivers=['PMTiles'],
                    )
                    layer = ds.GetLayer(0)
                    layer.SetSpatialFilterRect(x0, y0, x1, y1)
                    for f in layer:
                        if feedback.isCanceled():
                            return {}
                        g = f.GetGeometryRef()
                        # Tiles store each address as a one-point MultiPoint.
                        if g is not None and g.GetGeometryCount():
                            g = g.GetGeometryRef(0)
                        if g is None or g.GetGeometryType() != 1:
                            continue
                        lng, lat = to_lnglat(g.GetX(), g.GetY())
                        if not bbox.contains(lng, lat):
                            continue
                        values = [f[name] for name in ADDRESS_FIELDS]
                        # Points near a tile edge are repeated in the
                        # neighbouring tile.
                        uid = values[-1] or (lng, lat, *values[:3])
                        if uid in seen:
                            continue
                        point = QgsGeometry.fromPointXY(QgsPointXY(lng, lat))
                        if engine is not None and not engine.contains(
                            point.constGet()
                        ):
                            continue
                        seen.add(uid)
                        out = QgsFeature(fields)
                        out.setGeometry(point)
                        out.setAttributes(values + source_attrs)
                        sink.addFeature(out, fast)
                        if len(seen) % 20000 == 0:
                            feedback.setProgressText(
                                tr('Source {} of {}: {} ({} so far)').format(
                                    n + 1, len(work), src.name, len(seen)
                                )
                            )
                except RuntimeError as e:
                    raise QgsProcessingException(
                        tr('Reading {} failed: {}').format(src.tiles_url, e)
                    )
                ds = None
            feedback.pushInfo(
                tr('{} ({}): {} address(es)').format(
                    src.name, src.layer, len(seen)
                )
            )
            total += len(seen)

        feedback.pushInfo(tr('{} address(es) in total').format(total))
        if not total:
            feedback.pushWarning(
                tr('OpenAddresses has no addresses inside this area.')
            )
        return {self.OUTPUT: dest, 'COUNT': total}
