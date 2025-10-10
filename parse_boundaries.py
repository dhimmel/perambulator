"""Parse NH town boundaries from GeoJSON to tabular format."""

import json
from pathlib import Path

import polars as pl
from shapely.geometry import shape


def parse_geojson_to_municipalities(geojson_path: Path) -> pl.DataFrame:
    """Parse GeoJSON and extract NH municipalities (admin_level=8 relations)."""
    with open(geojson_path) as f:
        data = json.load(f)
    
    rows = []
    for feature in data["features"]:
        props = feature["properties"]
        geom = shape(feature["geometry"])
        
        row = {
            "relation_id": props["@id"],
            "name": props.get("name"),
            "admin_level": props.get("admin_level"),
            "border_type": props.get("border_type"),
            "wikidata": props.get("wikidata"),
            "wikipedia": props.get("wikipedia"),
            "area_sq_meters": geom.area,
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
    output_path = "nh_municipalities.json"
    municipalities.write_json(output_path)
    print(f"\nSaved to {output_path}")
