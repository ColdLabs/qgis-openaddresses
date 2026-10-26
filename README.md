# OpenAddresses Downloader (QGIS plugin)

> **Unofficial.** This plugin is not made, endorsed or supported by OpenAddresses. It reads the files OpenAddresses publishes. Report problems with the plugin [here](https://github.com/ColdLabs/qgis-openaddresses/issues), not to OpenAddresses.

Downloads [OpenAddresses](https://openaddresses.io/) address points for the map view or the polygons of a layer. Attributes: `number`, `street`, `unit`, `city`, `district`, `region`, `postcode`, `id`, `accuracy`, `hash`, plus the source and its licence (`source`, `source_layer`, `licence`, `licence_url`, `attribution`, `share_alike`). Output CRS is EPSG:4326.

Coverage is about 2,300 sources in 70+ countries, densest in the United States. Where two sources cover the same place (a city and its county), both sets of addresses are returned.

## Install

In QGIS: **Plugins → Manage and Install Plugins → All**, search for "OpenAddresses Downloader", then **Install**. Requires QGIS 3.38 or later (Qt5 or Qt6) with GDAL 3.8 or later, which current QGIS installers include. No extra Python packages are needed.

To install from this repository instead, run `./build_zip.sh` and use **Plugins → Manage and Install Plugins → Install from ZIP**.

## Use

- Toolbar button (Web toolbar) or **Web → OpenAddresses**: opens the dialog with the current map extent filled in. If the active layer is a polygon layer with selected features, those become the area.
- **Processing Toolbox → OpenAddresses → Download addresses**: same algorithm; works in models and batch mode.
- Command line:

```
qgis_process run openaddresses:download -- EXTENT="-9.16,-9.12,38.70,38.74 [EPSG:4326]" OUTPUT=addresses.gpkg
```

The run stops before reading anything if the area covers more zoom-14 map tiles than "Stop if the area needs more map tiles than" (2000 by default). A tile is about 2.4 km across at the equator and smaller towards the poles.

## How it fetches data

OpenAddresses publishes each source's latest run as a PMTiles file at `v2.openaddresses.io/batch-prod/job/<job>/source.pmtiles`. The zoom-14 tiles hold every address. The plugin:

1. Asks the OpenAddresses API for the current job of every address source (one request).
2. Picks the sources whose bounding box touches the area, using `sources.json`, an index of every source's bounding box and licence that ships with the plugin. Sources newer than the index get their bounds from the API once; these are cached in `<QGIS profile>/cache/openaddresses/`.
3. Reads only the tiles over the area through GDAL, keeps the addresses inside it, and drops the copies that tippecanoe repeats along tile edges.

GDAL reads the tiles over HTTP itself; QGIS passes its proxy settings on to GDAL.

Some sources have bounding boxes far larger than their data (one Taiwanese source spans most of the northern hemisphere), because OpenAddresses computes them from the published points. Those sources are opened but return no addresses, which costs a second or two each.

Rebuild the index before a release:

```
python3 tools/build_index.py
```

## Data licence

Every OpenAddresses source has its own licence, and many do not state one. Each address carries the licence, licence URL, the name to credit and whether the licence is share-alike, as recorded in the [openaddresses/openaddresses](https://github.com/openaddresses/openaddresses) source files. An empty licence means the source does not state one: check with the publisher before reusing the data. This is an unofficial plugin, not made or endorsed by OpenAddresses.

## Development

Link the plugin folder into your QGIS profile instead of installing the zip (macOS, QGIS 4):

```
ln -s "$PWD/openaddresses_downloader" ~/Library/Application\ Support/QGIS/QGIS4/profiles/default/python/plugins/
```

`./build_zip.sh` writes `dist/openaddresses_downloader-<version>.zip` for upload to plugins.qgis.org.
`./check.sh` runs the scanners the plugin site runs: Bandit and detect-secrets block an upload, flake8 is advisory.

## Licence

GPL-2.0-or-later. See [LICENSE](LICENSE).
