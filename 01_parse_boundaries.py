import marimo

__generated_with = "0.16.5"
app = marimo.App(width="medium")


@app.cell
def _(mo):
    mo.md("""# Parse NH town boundaries from GeoJSON to tabular format""")
    return


@app.cell
def _():
    import json
    from pathlib import Path

    import marimo as mo
    import polars as pl
    from pint import UnitRegistry
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform

    return Path, Transformer, UnitRegistry, json, mo, pl, shape, transform


@app.cell
def _(Path, Transformer, UnitRegistry, json, pl, shape, transform):
    def parse_geojson_to_municipalities(geojson_path: Path) -> pl.DataFrame:
        """Parse GeoJSON and extract NH municipalities (admin_level=8 relations)."""
        with open(geojson_path) as f:
            data = json.load(f)

        # Equal-area projection for contiguous US; outputs meters
        transformer = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
        ureg = UnitRegistry()
        meters_squared_to_miles_squared = (
            (1 * (ureg.meter**2)).to(ureg.mile**2).magnitude
        )

        rows = []
        for feature in data["features"]:
            props = feature["properties"]

            # Skip bbox-only and non-surface geometries (we only want true boundaries)
            if props.get("@geometry") == "bounds":
                continue
            geom_obj = feature.get("geometry")
            if not geom_obj:
                continue
            geom_type = geom_obj.get("type")
            if geom_type not in ("Polygon", "MultiPolygon"):
                continue

            geom = shape(geom_obj)  # lon/lat (EPSG:4326)
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
                "coordinates": geom_obj["coordinates"],
            }
            rows.append(row)

        df = pl.DataFrame(rows)

        # Filter to admin_level=8 (towns/cities) that are relations with names
        municipalities = df.filter(
            (pl.col("admin_level") == "8")
            .filter(pl.col("name").is_not_null())
            .filter(pl.col("relation_id").str.contains("^relation/"))
        )

        return municipalities

    return (parse_geojson_to_municipalities,)


@app.cell
def _(Path, parse_geojson_to_municipalities):
    geojson_path = Path("2025-10-09_nh-boundaries.geojson")
    municipalities = parse_geojson_to_municipalities(geojson_path)
    len(municipalities)
    return (municipalities,)


@app.cell
def _(municipalities):
    municipalities
    return


@app.cell
def _(Path, json, municipalities):
    # Save as JSON
    Path("nh_municipalities.json").write_text(
        json.dumps(municipalities.to_dicts(), indent=2) + "\n"
    )
    return


if __name__ == "__main__":
    app.run()
