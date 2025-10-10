"""Parse NH town boundaries from GeoJSON to tabular format."""

import json
from pathlib import Path

import polars as pl
from shapely.geometry import shape
from shapely.ops import transform
from pyproj import Transformer
from pint import UnitRegistry


def parse_geojson_to_municipalities(geojson_path: Path) -> pl.DataFrame:
    """Parse GeoJSON and extract NH municipalities (admin_level=8 relations)."""
    with open(geojson_path) as f:
        data = json.load(f)
    
    # Equal-area projection for contiguous US; outputs meters
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    ureg = UnitRegistry()
    meters_squared_to_miles_squared = (1 * (ureg.meter ** 2)).to(ureg.mile ** 2).magnitude

    rows = []
    for feature in data["features"]:
        props = feature["properties"]
        geom = shape(feature["geometry"])  # lon/lat (EPSG:4326)
        geom_equal_area = transform(transformer.transform, geom)
        area_sq_meters = geom_equal_area.area
        
        row = {
            "relation_id": props["@id"],
            "name": props.get("name"),
            "admin_level": props.get("admin_level"),
            "border_type": props.get("border_type"),
            "wikidata": props.get("wikidata"),
            "wikipedia": props.get("wikipedia"),
            "area_sq_meters": area_sq_meters,
            "area_sq_miles": area_sq_meters * meters_squared_to_miles_squared,
            "coordinates": feature["geometry"]["coordinates"],
        }
        rows.append(row)
    
    df = pl.DataFrame(rows)
    
    # Filter to admin_level=8 (towns/cities) that are relations with names
    municipalities = df.filter(
        (pl.col("admin_level") == "8") & 
        (pl.col("name").is_not_null()) &
        (pl.col("relation_id").str.contains("^relation/"))
    )
    
    return municipalities


if __name__ == "__main__":
    geojson_path = Path("2025-10-09_nh-boundaries.geojson")
    municipalities = parse_geojson_to_municipalities(geojson_path)
    
    print(f"Parsed {len(municipalities)} NH municipalities")
    print(f"\nSample:")
    print(municipalities.select(["name", "relation_id", "border_type", "area_sq_meters"]).head(10))
    
    # Save as JSON
    Path("nh_municipalities.json").write_text(json.dumps(municipalities.to_dicts(), indent=2))
