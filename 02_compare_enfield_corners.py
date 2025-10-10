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
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import polars as pl
from pygeodesy import dms as dms_mod
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.lib import Geometry
from shapely.ops import transform as shapely_transform


def parse_dms(dms: str) -> float:
    """Parse DMS to decimal degrees using pygeodesy (expects ASCII ' and ")."""
    return float(dms_mod.parseDMS(dms.strip()))


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


"""Input: Surveyed DMS corners from README."""
ENFIELD_DMS_CORNERS: list[Corner] = [
    Corner(
        name="Enfield–Lebanon–Plainfield (SW corner)",
        lat_dms="43° 35' 6.94\" N",
        lon_dms="72° 12' 29.39\" W",
    ),
    Corner(
        name="Enfield–Grantham–Plainfield (W corner)",
        lat_dms="43° 34' 24.63\" N",
        lon_dms="72° 10' 10.94\" W",
    ),
    Corner(
        name="Enfield–Springfield–Grantham (S corner)",
        lat_dms="43° 31' 42.97\" N",
        lon_dms="72° 05' 28.03\" W",
    ),
    Corner(
        name="Enfield–Grafton–Springfield (SE corner)",
        lat_dms="43° 33' 10.60\" N",
        lon_dms="72° 04' 11.68\" W",
    ),
    Corner(
        name="Enfield–Canaan–Grafton (NE corner)",
        lat_dms="43° 36' 40.96\" N",
        lon_dms="72° 01' 11.71\" W",
    ),
    Corner(
        name="Enfield–Lebanon–Hanover–Canaan (NW corner, Moose Mountain)",
        lat_dms="43° 39' 32.72\" N",
        lon_dms="72° 09' 43.23\" W",
    ),
]


def load_enfield_geometry(geojson_path: Path) -> Geometry:
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


def iter_boundary_vertices(geom: Geometry) -> Iterable[tuple[float, float]]:
    """Yield all boundary vertex coordinates (lon, lat) from polygon/multipolygon."""

    def _iter_coords(g: Geometry) -> Iterable[tuple[float, float]]:
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


def main() -> None:
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
        shapely_transform(to_utm.transform, Point(lon, lat))
        for lon, lat in vertex_lon_lat
    ]

    # Build report rows
    rows = []
    for c in ENFIELD_DMS_CORNERS:
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
        if not vertex_points_utm:
            raise RuntimeError("No boundary vertices found for Enfield geometry")

        nearest_idx, nearest_point_utm = min(
            enumerate(vertex_points_utm),
            key=lambda item: corner_pt_utm.distance(item[1]),
        )
        nearest_vertex_lon, nearest_vertex_lat = vertex_lon_lat[nearest_idx]
        min_dist = corner_pt_utm.distance(nearest_point_utm)

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
        "corner_name",
        "lat",
        "lon",
        "nearest_boundary_lat",
        "nearest_boundary_lon",
        "distance_to_boundary_m",
        "nearest_vertex_lat",
        "nearest_vertex_lon",
        "distance_to_vertex_m",
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
    out_json.write_text(json.dumps(df.to_dicts(), indent=2) + "\n")


if __name__ == "__main__":
    main()
