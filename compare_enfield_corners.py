"""Compare surveyed Enfield corners (NAD83 DMS) to OSM boundary.

Outputs a per-corner inaccuracy report including:
- nearest boundary point distance (meters)
- nearest boundary vertex distance (meters)
- nearest boundary point coordinates (lon/lat)
- nearest vertex coordinates (lon/lat)

Usage:
  uv run python compare_enfield_corners.py
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Tuple

import polars as pl
from shapely.geometry import Point, shape
from shapely.ops import transform as shapely_transform
from pyproj import Transformer


# --- Input: Surveyed DMS corners from README ---
ENFIELD_DMS_CORNERS = [
    (
        "Enfield–Lebanon–Plainfield (SW corner)",
        "43° 35′ 6.94″ N",
        "72° 12′ 29.39″ W",
    ),
    (
        "Enfield–Grantham–Plainfield (W corner)",
        "43° 34′ 24.63″ N",
        "72° 10′ 10.94″ W",
    ),
    (
        "Enfield–Springfield–Grantham (S corner)",
        "43° 31′ 42.97″ N",
        "72° 05′ 28.03″ W",
    ),
    (
        "Enfield–Grafton–Springfield (SE corner)",
        "43° 33′ 10.60″ N",
        "72° 04′ 11.68″ W",
    ),
    (
        "Enfield–Canaan–Grafton (NE corner)",
        "43° 36′ 40.96″ N",
        "72° 01′ 11.71″ W",
    ),
    (
        "Enfield–Lebanon–Hanover–Canaan (NW corner, Moose Mountain)",
        "43° 39′ 32.72″ N",
        "72° 09′ 43.23″ W",
    ),
]


def parse_dms(dms: str) -> float:
    """Parse a DMS coordinate string to decimal degrees.

    Accepts variants using ASCII or Unicode symbols for degree, minute, second.
    Examples: "43° 35′ 6.94″ N", "72° 12' 29.39\" W"
    """
    s = (
        dms.strip()
        .replace("\u00b0", "°")  # ensure degree
        .replace("\u2032", "'")  # prime to apostrophe
        .replace("\u2033", '"')  # double prime to quote
        .replace("’", "'")  # curly apostrophe
        .replace("＂", '"')  # fullwidth quote
    )
    s = re.sub(r"[\s\u00A0]+", " ", s)  # collapse spaces incl. non-breaking
    s = s.rstrip(".,;")

    # Extract components
    m = re.search(
        r'(?P<deg>\d+)\s*[°]?\s*(?P<min>\d+)\s*[\'′]?\s*(?P<sec>\d+(?:\.\d+)?)\s*[\"]?\s*(?P<hem>[NSEW])',
        s,
        re.IGNORECASE,
    )
    if not m:
        raise ValueError(f"Cannot parse DMS: {dms}")
    deg = float(m.group("deg"))
    minutes = float(m.group("min"))
    seconds = float(m.group("sec"))
    hem = m.group("hem").upper()

    decimal = deg + minutes / 60.0 + seconds / 3600.0
    if hem in ("S", "W"):
        decimal *= -1.0
    return decimal


@dataclass(frozen=True)
class Corner:
    name: str
    lat_dms: str
    lon_dms: str

    @property
    def lat(self) -> float:
        return parse_dms(self.lat_dms)

    @property
    def lon(self) -> float:
        return parse_dms(self.lon_dms)

    @property
    def point_wgs84(self) -> Point:
        return Point(self.lon, self.lat)


def load_enfield_geometry(geojson_path: Path):
    """Load Enfield boundary geometry (admin_level=8) from Overpass GeoJSON."""
    with open(geojson_path) as f:
        data = json.load(f)

    enfield_feature = None
    for feature in data["features"]:
        props = feature.get("properties", {})
        if (
            props.get("name") == "Enfield"
            and props.get("admin_level") == "8"
            and feature.get("geometry")
        ):
            enfield_feature = feature
            break

    if enfield_feature is None:
        raise RuntimeError("Enfield admin_level=8 feature not found in GeoJSON")

    geom = shape(enfield_feature["geometry"])  # lon/lat EPSG:4326
    return geom


def iter_boundary_vertices(geom) -> Iterable[Tuple[float, float]]:
    """Yield all boundary vertex coordinates (lon, lat) from polygon/multipolygon."""
    def _iter_coords(g):
        if g.geom_type == "Polygon":
            for ring in [g.exterior, *g.interiors]:
                for x, y in ring.coords:
                    yield (x, y)
        elif g.geom_type == "MultiPolygon":
            for poly in g.geoms:
                yield from _iter_coords(poly)
        else:
            for x, y in g.coords:
                yield (x, y)

    yield from _iter_coords(geom)


def main():
    repo_root = Path(__file__).resolve().parent
    geojson_path = repo_root / "2025-10-09_nh-boundaries.geojson"

    # Load OSM Enfield geometry
    enfield_geom_wgs84 = load_enfield_geometry(geojson_path)
    boundary_wgs84 = enfield_geom_wgs84.boundary

    # Transformers:
    # Use UTM Zone 19N (EPSG:26919) for accurate local distances in meters.
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:26919", always_xy=True)
    to_wgs84 = Transformer.from_crs("EPSG:26919", "EPSG:4326", always_xy=True)

    boundary_utm = shapely_transform(to_utm.transform, boundary_wgs84)

    # Precompute boundary vertices (WGS84) and project to UTM
    vertex_lon_lat = list(iter_boundary_vertices(enfield_geom_wgs84))
    vertex_points_utm = [
        shapely_transform(to_utm.transform, Point(lon, lat)) for lon, lat in vertex_lon_lat
    ]

    # Build report rows
    rows = []
    for name, lat_dms, lon_dms in ENFIELD_DMS_CORNERS:
        c = Corner(name=name, lat_dms=lat_dms, lon_dms=lon_dms)
        corner_pt_wgs84 = c.point_wgs84
        corner_pt_utm = shapely_transform(to_utm.transform, corner_pt_wgs84)

        # Nearest point on boundary (could be along a segment)
        # We compute by densifying using shapely's projection-safe distance ops in UTM
        # Nearest point: use linear referencing trick via project/interpolate on boundary
        # If boundary is MultiLineString, unary_union ensures a single linear geometry
        boundary_line = boundary_utm
        # project distance along the line and then interpolate back to get nearest point
        d_along = boundary_line.project(corner_pt_utm)
        nearest_point_on_line_utm = boundary_line.interpolate(d_along)
        dist_to_line_m = corner_pt_utm.distance(nearest_point_on_line_utm)

        x_lon, y_lat = to_wgs84.transform(
            nearest_point_on_line_utm.x, nearest_point_on_line_utm.y
        )

        # Nearest vertex
        # Compute minimal distance to the set of vertex points in UTM
        min_idx = None
        min_dist = math.inf
        for idx, vp_utm in enumerate(vertex_points_utm):
            d = corner_pt_utm.distance(vp_utm)
            if d < min_dist:
                min_dist = d
                min_idx = idx
        nearest_vertex_lon, nearest_vertex_lat = vertex_lon_lat[min_idx]

        rows.append(
            {
                "corner_name": c.name,
                "lat_dms": c.lat_dms,
                "lon_dms": c.lon_dms,
                "lat": c.lat,
                "lon": c.lon,
                "nearest_boundary_lon": x_lon,
                "nearest_boundary_lat": y_lat,
                "distance_to_boundary_m": dist_to_line_m,
                "nearest_vertex_lon": nearest_vertex_lon,
                "nearest_vertex_lat": nearest_vertex_lat,
                "distance_to_vertex_m": min_dist,
            }
        )

    df = pl.DataFrame(rows)
    df = df.select(
        [
            "corner_name",
            "lat",
            "lon",
            "nearest_boundary_lat",
            "nearest_boundary_lon",
            "distance_to_boundary_m",
            "nearest_vertex_lat",
            "nearest_vertex_lon",
            "distance_to_vertex_m",
        ]
    )

    # Display concise table
    print("Enfield corner inaccuracy report (meters):")
    print(
        df.select(
            [
                "corner_name",
                pl.col("distance_to_boundary_m").round(2),
                pl.col("distance_to_vertex_m").round(2),
            ]
        )
    )

    # Write files
    out_json = repo_root / "enfield_corner_inaccuracy.json"
    out_json.write_text(json.dumps(df.to_dicts(), indent=2))


if __name__ == "__main__":
    main()


