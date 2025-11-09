# New Hampshire Boundaries

Who knew no one knew?

When all the maps of Enfield New Hampshire were wrong

This project looks into the boundaries of New Hampshire towns.

Query for <https://overpass-turbo.eu/> to extract all town boundaries in New Hampshire.

```overpass
[out:json][timeout:180];

// Get the NH area to scope queries
area["boundary"="administrative"]["admin_level"="4"]["name"="New Hampshire"]->.nh;

/*
  Fetch ALL municipality relations (admin_level=8) in NH and include
  their member ways and nodes so the exporter can assemble true polygons.
  Note: Export → GeoJSON in Overpass Turbo to get full MultiPolygon geometry.
*/
rel(area.nh)["boundary"="administrative"]["admin_level"="8"]->.rels;
(.rels; >;);
out body;
```

## Setup

```shell
uv sync
pre-commit install
```

## Usage

```shell
marimo edit
```

Parse the GeoJSON data:

```shell
uv run python 01_parse_boundaries.py
uv run python 02_compare_enfield_corners.py
```

This extracts 234 NH municipalities (admin_level=8 relations) from the raw Overpass data and outputs to `nh_municipalities.json`.

## Note to AI

Using uv for environment management, polars for dataframes, shapely for geometry. Python 3.14.

## References

- https://www.openstreetmap.org/relation/2027182
- [A History of Enfield Town Lines: From 1761 To 2007](https://www.enfieldnh.gov/media/7556) by Kurt Gotthardt from 2010

GPT-5 extracts the **current Enfield corners exactly as reported (NAD 83, degrees-minutes-seconds)** in the perambulation/GPS tables from the PDF:

* **Enfield–Lebanon–Plainfield (SW corner):** 43° 35′ 6.94″ N, 72° 12′ 29.39″ W.
* **Enfield–Grantham–Plainfield (W corner):** 43° 34′ 24.63″ N, 72° 10′ 10.94″ W.
* **Enfield–Springfield–Grantham (S corner):** 43° 31′ 42.97″ N, 72° 05′ 28.03″ W.
* **Enfield–Grafton–Springfield (SE corner):** 43° 33′ 10.60″ N, 72° 04′ 11.68″ W.
* **Enfield–Canaan–Grafton (NE corner):** 43° 36′ 40.96″ N, 72° 01′ 11.71″ W.
* **Enfield–Lebanon–Hanover–Canaan (NW corner, Moose Mountain):** 43° 39′ 32.72″ N, 72° 09′ 43.23″ W.
