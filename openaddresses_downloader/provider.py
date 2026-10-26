import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithm import DownloadAddresses


class Provider(QgsProcessingProvider):
    def id(self):
        return 'openaddresses'

    def name(self):
        return 'OpenAddresses'

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), 'icon.svg'))

    def loadAlgorithms(self):
        self.addAlgorithm(DownloadAddresses())
