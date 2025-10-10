# New Hampshire Boundaries

Who knew no one knew?

This project looks into the boundaries of New Hampshire towns.

Query for <https://overpass-turbo.eu/> to extract all town boundaries in New Hampshire.

```overpass
[out:json][timeout:180];

// Get the NH area to scope queries
area["boundary"="administrative"]["admin_level"="4"]["name"="New Hampshire"]->.nh;

/*
  Fetch all municipality boundaries (admin_level=8) in NH.
  In New England, towns/cities are usually admin_level=8.
  We request full geometry; Overpass will include coordinates.
*/
rel(area.nh)["boundary"="administrative"]["admin_level"="8"];
out ids tags geom;   // relation centroids + full polygon geometry

// Also dump member ways/nodes so you have raw ring coordinates if needed
>;
out geom;
```

## Usage

Parse the GeoJSON data:

```bash
uv run python parse_boundaries.py
```

This extracts 234 NH municipalities (admin_level=8 relations) from the raw Overpass data and outputs to `nh_municipalities.json`.

## Note to AI

Using uv for environment management, polars for dataframes, shapely for geometry. Python 3.14.
