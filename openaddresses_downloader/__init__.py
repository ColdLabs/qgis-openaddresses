def classFactory(iface):
    from .plugin import OpenAddressesPlugin

    return OpenAddressesPlugin(iface)
