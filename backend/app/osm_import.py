"""Import all fuel stations (amenity=fuel) in Russia from OpenStreetMap.

Queries the Overpass API tile-by-tile (so no single request is huge), upserts
stations into SQLite, and records progress in the `meta` table.

Run as a module:  python -m backend.app.osm_import
"""
import json
import time

import httpx

from .brands import fuels_from_tags, normalize_brand
from .db import cursor, init_db, set_meta

# Ordered fastest-first; mirrors that hang for this server are omitted.
OVERPASS_ENDPOINTS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

# Per-request timeout (s). Kept low so a slow mirror fails over quickly.
REQUEST_TIMEOUT = 90

# Bounding box covering Russia (antimeridian sliver of Chukotka omitted).
LAT_MIN, LAT_MAX = 41.0, 78.0
LON_MIN, LON_MAX = 19.0, 180.0
TILE = 3.0  # degrees per tile


def _tiles():
    lat = LAT_MIN
    while lat < LAT_MAX:
        lon = LON_MIN
        while lon < LON_MAX:
            yield (lat, lon, min(lat + TILE, LAT_MAX), min(lon + TILE, LON_MAX))
            lon += TILE
        lat += TILE


def _query(bbox):
    s, w, n, e = bbox
    return (
        f"[out:json][timeout:120];"
        f'area["ISO3166-1"="RU"][admin_level=2]->.ru;'
        f"("
        f'node["amenity"="fuel"](area.ru)({s},{w},{n},{e});'
        f'way["amenity"="fuel"](area.ru)({s},{w},{n},{e});'
        f");"
        f"out tags center;"
    )


def _fetch(bbox, client):
    q = _query(bbox)
    last_err = None
    for _ in range(2):
        for ep in OVERPASS_ENDPOINTS:
            try:
                r = client.post(ep, data={"data": q}, timeout=REQUEST_TIMEOUT)
                if r.status_code == 200:
                    return r.json().get("elements", [])
                last_err = f"{ep} -> HTTP {r.status_code}"
            except Exception as exc:  # noqa: BLE001
                last_err = f"{ep} -> {exc}"
            time.sleep(1)
    raise RuntimeError(f"all overpass endpoints failed: {last_err}")


def _upsert(elements):
    rows = 0
    with cursor() as cur:
        for el in elements:
            if el.get("type") == "node":
                lat, lon = el.get("lat"), el.get("lon")
            else:
                c = el.get("center") or {}
                lat, lon = c.get("lat"), c.get("lon")
            if lat is None or lon is None:
                continue
            tags = el.get("tags", {})
            osm_id = f"{el['type'][0]}{el['id']}"
            brand = normalize_brand(
                tags.get("brand"), tags.get("operator"), tags.get("name")
            )
            name = tags.get("name") or tags.get("brand") or brand or "АЗС"
            fuels = fuels_from_tags(tags)
            region = (
                tags.get("addr:region")
                or tags.get("addr:state")
                or tags.get("addr:city")
                or tags.get("is_in:region")
            )
            address = ", ".join(
                p
                for p in [
                    tags.get("addr:city"),
                    tags.get("addr:street"),
                    tags.get("addr:housenumber"),
                ]
                if p
            ) or None
            cur.execute(
                """
                INSERT INTO stations (osm_id, name, brand, lat, lon, region, address, fuels)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(osm_id) DO UPDATE SET
                    name=excluded.name,
                    brand=excluded.brand,
                    lat=excluded.lat,
                    lon=excluded.lon,
                    region=COALESCE(excluded.region, stations.region),
                    address=COALESCE(excluded.address, stations.address),
                    fuels=excluded.fuels
                """,
                (
                    osm_id,
                    name[:120],
                    brand,
                    lat,
                    lon,
                    region,
                    address,
                    json.dumps(fuels, ensure_ascii=False),
                ),
            )
            rows += 1
    return rows


def run(verbose=True):
    init_db()
    tiles = list(_tiles())
    total = 0
    set_meta("import_status", "running")
    with httpx.Client(headers={"User-Agent": "azs-online/1.0 (import)"}) as client:
        for i, bbox in enumerate(tiles, 1):
            try:
                els = _fetch(bbox, client)
            except Exception as exc:  # noqa: BLE001
                if verbose:
                    print(f"[{i}/{len(tiles)}] {bbox} FAILED: {exc}", flush=True)
                continue
            n = _upsert(els)
            total += len(els)
            if verbose:
                print(
                    f"[{i}/{len(tiles)}] {bbox} -> {len(els)} elements (upserted {n})",
                    flush=True,
                )
            set_meta("import_progress", f"{i}/{len(tiles)}")
            time.sleep(1)
    with cursor() as cur:
        cur.execute("SELECT COUNT(*) c FROM stations")
        count = cur.fetchone()["c"]
    set_meta("import_status", "done")
    set_meta("stations_count", count)
    set_meta("last_import", time.strftime("%Y-%m-%d %H:%M:%S"))
    if verbose:
        print(f"DONE. stations in DB: {count}", flush=True)
    return count


if __name__ == "__main__":
    run()
