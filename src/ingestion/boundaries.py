import geopandas as gpd
import shapely

from src.config import LAYERS_RAW as RAW, SPATIAL

# Official BIG kecamatan boundaries (BATASWILAYAH_KECAMATAN_20260601), downloaded from the share link BIG gave out: one polygon per kecamatan, no dissolve
KECAMATAN_GDB = RAW / "big_kecamatan" / "unzipped" / "BATASWILAYAH_KECAMATAN.gdb"
SIMPLIFY_DEGREES = 0.0002  # about 20 m; coverage_simplify keeps shared borders identical, so neighbours leave no gaps
JABODETABEK_REGENCIES = [
    "Kota Administrasi Jakarta Barat", "Kota Administrasi Jakarta Pusat", "Kota Administrasi Jakarta Selatan",
    "Kota Administrasi Jakarta Timur", "Kota Administrasi Jakarta Utara",
    "Kota Tangerang", "Kota Tangerang Selatan", "Tangerang", "Kota Bekasi", "Bekasi", "Kota Bogor", "Bogor", "Kota Depok",
]


def load_kecamatan() -> gpd.GeoDataFrame:
    gdf = gpd.read_file(KECAMATAN_GDB, layer="BATAS_KECAMATAN_AR")
    gdf.columns = [c.lower() if c != "geometry" else c for c in gdf.columns]
    gdf = gdf[gdf.wadmkk.isin(JABODETABEK_REGENCIES)][["kdcpum", "wadmkc", "wadmkk", "wadmpr", "geometry"]].reset_index(drop=True)
    gdf["geometry"] = shapely.coverage_simplify(shapely.force_2d(gdf.geometry.to_numpy()), SIMPLIFY_DEGREES)
    return gdf.set_crs("EPSG:4326", allow_override=True)


if __name__ == "__main__":
    SPATIAL.mkdir(parents=True, exist_ok=True)
    kecamatan = load_kecamatan()
    kecamatan.to_file(SPATIAL / "big_kecamatan_jabodetabek.geojson", driver="GeoJSON")
    print(f"{len(kecamatan)} kecamatan")
    print(kecamatan.groupby("wadmkk").size().to_string())
