import os

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsProcessingFeatureSourceDefinition,
    QgsVectorLayer,
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .provider import Provider

ICON = os.path.join(os.path.dirname(__file__), 'icon.svg')


class OpenAddressesPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.action = None

    def initProcessing(self):
        self.provider = Provider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()
        self.action = QAction(
            QIcon(ICON), 'Download OpenAddresses…', self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)
        self.iface.addWebToolBarIcon(self.action)
        self.iface.addPluginToWebMenu('OpenAddresses', self.action)

    def unload(self):
        self.iface.removeWebToolBarIcon(self.action)
        self.iface.removePluginWebMenu('OpenAddresses', self.action)
        QgsApplication.processingRegistry().removeProvider(self.provider)

    def run(self):
        import processing

        canvas = self.iface.mapCanvas()
        e = canvas.extent()
        crs = canvas.mapSettings().destinationCrs().authid()
        params = {
            'EXTENT': '{},{},{},{} [{}]'.format(
                e.xMinimum(), e.xMaximum(), e.yMinimum(), e.yMaximum(), crs
            )
        }
        # Selected polygons in the active layer become the area, which is what
        # the user most likely meant by selecting them.
        layer = self.iface.activeLayer()
        if (
            isinstance(layer, QgsVectorLayer)
            and layer.geometryType() == Qgis.GeometryType.Polygon
            and layer.selectedFeatureCount()
        ):
            params['AREA'] = QgsProcessingFeatureSourceDefinition(
                layer.id(), selectedFeaturesOnly=True
            )
        processing.execAlgorithmDialog('openaddresses:download', params)
