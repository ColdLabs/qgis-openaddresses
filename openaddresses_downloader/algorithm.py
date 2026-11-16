import math
import os

from osgeo import gdal
from qgis.core import (
    Qgis,
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
LICENCE_FIELDS = [
    'source',
    'source_layer',
    'licence',
    'licence_url',
    'attribution',
]


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
    LICENCES = 'LICENCES'

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
            'United States. Addresses come from the single global file '
            'OpenAddresses publishes.\n\n'
            'Only the map tiles over the area are read, each about 2.4 km '
            'across at the equator and smaller towards the poles. The run '
            'stops before reading if the area needs more tiles than the '
            'limit.\n\n'
            'Licences: each source has its own, and the global file does not '
            'say which source each address came from. The Source licences '
            'output lists every source whose coverage (a bounding box) '
            'touches the area, with its licence, licence URL, who to credit '
            'and whether the licence is share-alike. A source may be listed '
            'without having addresses in the area. Where sources overlap, '
            'you cannot tell which licence applies to which address. An '
            'empty licence means the source does not state one; check with '
            'the publisher before reusing the data. Sources added after the '
            'plugin\'s source index was built are not listed.\n\n'
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
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.LICENCES,
                tr('Source licences'),
                QgsProcessing.SourceType.TypeVector,
                optional=True,
                createByDefault=True,
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

        fields = QgsFields()
        for name in ADDRESS_FIELDS:
            fields.append(QgsField(name, QMetaType.Type.QString))
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
        results = {self.OUTPUT: dest}

        sources = catalog.sources_in(
            bbox.xMinimum(), bbox.yMinimum(), bbox.xMaximum(), bbox.yMaximum()
        )
        if not is_rect:
            sources = [
                s
                for s in sources
                if area.intersects(QgsGeometry.fromRect(QgsRectangle(*s.bbox)))
            ]
        licence_fields = QgsFields()
        for name in LICENCE_FIELDS:
            licence_fields.append(QgsField(name, QMetaType.Type.QString))
        licence_fields.append(QgsField('share_alike', QMetaType.Type.Bool))
        licence_sink, licence_dest = self.parameterAsSink(
            parameters,
            self.LICENCES,
            context,
            licence_fields,
            Qgis.WkbType.NoGeometry,
            QgsCoordinateReferenceSystem(),
        )
        if licence_sink is None:
            feedback.pushInfo(
                tr('{} source(s) may cover this area.').format(len(sources))
            )
        else:
            for src in sources:
                row = QgsFeature(licence_fields)
                row.setAttributes(
                    [
                        src.name,
                        src.layer,
                        src.licence,
                        src.url,
                        src.attribution,
                        src.share_alike,
                    ]
                )
                licence_sink.addFeature(row, QgsFeatureSink.Flag.FastInsert)
            results[self.LICENCES] = licence_dest
            feedback.pushInfo(
                tr(
                    '{} source(s) may cover this area; their licences are '
                    'in the Source licences output.'
                ).format(len(sources))
            )
        feedback.pushInfo(
            tr(
                'The source index was built on {}; sources added since then '
                'are not listed.'
            ).format(catalog.built())
        )

        engine = None
        if not is_rect:
            engine = QgsGeometry.createGeometryEngine(area.constGet())
            engine.prepareGeometry()
        fast = QgsFeatureSink.Flag.FastInsert
        x0, y0 = to_mercator(bbox.xMinimum(), bbox.yMinimum())
        x1, y1 = to_mercator(bbox.xMaximum(), bbox.yMaximum())
        seen = set()
        feedback.setProgressText(tr('Reading addresses'))
        with gdal.ExceptionMgr(useExceptions=True):
            try:
                ds = gdal.OpenEx(
                    '/vsicurl/' + catalog.FABRIC_URL,
                    gdal.OF_VECTOR,
                    allowed_drivers=['PMTiles'],
                    open_options=['ZOOM_LEVEL=%d' % ZOOM],
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
                    out.setAttributes(values)
                    sink.addFeature(out, fast)
                    if len(seen) % 20000 == 0:
                        feedback.setProgressText(
                            tr('Reading addresses ({} so far)').format(
                                len(seen)
                            )
                        )
            except RuntimeError as e:
                raise QgsProcessingException(
                    tr('Reading {} failed: {}').format(catalog.FABRIC_URL, e)
                )
            ds = None

        total = len(seen)
        feedback.pushInfo(tr('{} address(es) in total').format(total))
        if not total:
            feedback.pushWarning(
                tr('OpenAddresses has no addresses inside this area.')
            )
        results['COUNT'] = total
        return results
