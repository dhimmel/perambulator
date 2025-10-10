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

import plotnine as pn
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
    page: int | None = None

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
        page=140,
    ),
    Corner(
        name="Enfield–Grantham–Plainfield (W corner)",
        lat_dms="43° 34' 24.63\" N",
        lon_dms="72° 10' 10.94\" W",
        page=143,
    ),
    Corner(
        name="Enfield–Grantham",
        lat_dms="43° 33' 12.19\" N",
        lon_dms="72° 06' 23.68\" W",
        page=129,
    ),
    Corner(
        name="Enfield–Grantham",
        lat_dms="43° 32' 18.26\" N",
        lon_dms="72° 07' 13.04\" W",
        page=128,
    ),
    Corner(
        name="Enfield–Springfield–Grantham (S corner)",
        lat_dms="43° 31' 42.97\" N",
        lon_dms="72° 05' 28.03\" W",
        page=127,
    ),
    Corner(
        name="Enfield–Grafton–Springfield (SE corner)",
        lat_dms="43° 33' 10.60\" N",
        lon_dms="72° 04' 11.68\" W",
        page=113,
    ),
    Corner(
        name="Enfield–Canaan–Grafton (NE corner)",
        lat_dms="43° 36' 40.96\" N",
        lon_dms="72° 01' 11.71\" W",
        page=76,
    ),
    Corner(
        name="Enfield–Lebanon–Hanover–Canaan (NW corner, Moose Mountain)",
        lat_dms="43° 39' 32.72\" N",
        lon_dms="72° 09' 43.23\" W",
        page=92,
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


def get_boundary_vertices(geom: Geometry) -> list[tuple[float, float]]:
    """Return all boundary vertex coordinates (lon, lat) as a list."""

    vertices: list[tuple[float, float]] = []

    def _collect_coords(g: Geometry) -> None:
        if g.geom_type == "Polygon":
            for ring in [g.exterior, *g.interiors]:
                for x, y in ring.coords:
                    vertices.append((x, y))
        elif g.geom_type == "MultiPolygon":
            for poly in g.geoms:
                _collect_coords(poly)
        else:
            for x, y in g.coords:
                vertices.append((x, y))

    _collect_coords(geom)
    return vertices


def iter_boundary_lines(geom: Geometry) -> Iterable[Iterable[tuple[float, float]]]:
    """Yield each boundary line as a sequence of (lon, lat) coordinates."""
    boundary = geom.boundary
    if boundary.geom_type == "LineString":
        yield list(boundary.coords)
        return
    if boundary.geom_type == "MultiLineString":
        for line in boundary.geoms:
            yield list(line.coords)
        return
    # Fallback: treat geometry as coordinate sequence if possible
    try:
        yield list(boundary.coords)
    except Exception:  # pragma: no cover - defensive
        return


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
    vertex_lon_lat = get_boundary_vertices(enfield_geom_wgs84)
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

    # ---- Plot OSM boundary vs. surveyed polygon ----
    # Build OSM boundary dataframe
    osm_rows: list[dict[str, float | int]] = []
    for path_id, coords in enumerate(iter_boundary_lines(enfield_geom_wgs84)):
        for order, (x, y) in enumerate(coords):
            osm_rows.append({"lon": x, "lat": y, "path_id": path_id, "order": order})

    osm_df_pl = pl.DataFrame(osm_rows).sort(["path_id", "order"])

    # Build surveyed polygon path (ordered by angle and closed)
    survey_loop = ENFIELD_DMS_CORNERS.copy()
    # close the ring
    if survey_loop[0] != survey_loop[-1]:
        survey_loop = [*survey_loop, survey_loop[0]]

    survey_rows = [
        {"lon": corner.lon, "lat": corner.lat, "order": i}
        for i, corner in enumerate(survey_loop)
    ]
    survey_df_pl = pl.DataFrame(survey_rows).sort(["order"])

    # Points for labels
    survey_pts_rows = [
        {"lon": c.lon, "lat": c.lat, "label": str(i + 1)}
        for i, c in enumerate(ENFIELD_DMS_CORNERS)
    ]
    survey_pts_pl = pl.DataFrame(survey_pts_rows)

    p = (
        pn.ggplot()
        + pn.geom_path(
            osm_df_pl,
            pn.aes(x="lon", y="lat", group="path_id"),
            color="#2563eb",
            size=0.7,
            alpha=0.9,
        )
        + pn.geom_path(
            survey_df_pl, pn.aes(x="lon", y="lat"), color="#ef4444", size=1.1, alpha=0.9
        )
        + pn.geom_point(
            survey_pts_pl, pn.aes(x="lon", y="lat"), color="#111827", size=1.8
        )
        + pn.geom_text(
            survey_pts_pl,
            pn.aes(x="lon", y="lat", label="label"),
            nudge_y=0.0025,
            size=7,
            color="#111827",
        )
        + pn.coord_equal()
        + pn.theme_void()
        + pn.labs(title="Enfield boundary: OSM vs. surveyed corners")
    )

    out_png = repo_root / "enfield_osm_vs_survey.png"
    # Save figure
    p.save(filename=str(out_png), width=6, height=6, units="in", dpi=200)
    print(f"Saved comparison figure to: {out_png}")


if __name__ == "__main__":
    main()
