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

Next we want to make a tabular data structure with one row per town that includes the town's ids, name, area, and list of coordinates.

## Note to AI

Let's use uv for the environment, polars for dataframes unless we need to use something else for geojson. Python 3.14.
