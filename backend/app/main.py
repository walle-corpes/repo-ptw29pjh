import json
import secrets
import time

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import (
    FRESH_HOURS,
    FRONTEND_DIR,
    FUEL_LABELS,
    FUEL_TYPES,
    PHOTO_DIR,
    REPORT_COOLDOWN_SEC,
    STALE_HOURS,
    STATUS_LABELS,
    STATUSES,
)
from .status import STATUS_COLOR, fuel_statuses, overall_maps, station_overall, window_expr

try:
    from PIL import Image  # noqa
    HAVE_PIL = True
except Exception:  # noqa: BLE001
    HAVE_PIL = False

app = FastAPI(title="АЗС Онлайн Табло", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(GZipMiddleware, minimum_size=512)


@app.on_event("startup")
def _startup():
    db.init_db()


# ---------------------------------------------------------------- meta / config
@app.get("/api/meta")
def meta():
    conn = db.get_conn()
    count = conn.execute("SELECT COUNT(*) c FROM stations").fetchone()["c"]
    return {
        "stations_count": count,
        "last_import": db.get_meta("last_import"),
        "import_status": db.get_meta("import_status"),
        "import_progress": db.get_meta("import_progress"),
        "fuel_types": FUEL_TYPES,
        "fuel_labels": FUEL_LABELS,
        "statuses": STATUSES,
        "status_labels": STATUS_LABELS,
        "status_color": STATUS_COLOR,
        "fresh_hours": FRESH_HOURS,
        "stale_hours": STALE_HOURS,
    }


# ---------------------------------------------------------------- stations list
@app.get("/api/stations")
def stations(
    bbox: str = Query(..., description="south,west,north,east"),
    brands: str | None = None,
    fuel: str | None = Query(None, description="filter: station sells this fuel"),
    status: str | None = Query(None, description="filter by current status"),
    only_with_data: bool = False,
    limit: int = Query(4000, le=8000),
):
    try:
        s, w, n, e = (float(x) for x in bbox.split(","))
    except Exception:
        raise HTTPException(400, "bad bbox")

    conn = db.get_conn()
    sql = [
        "SELECT id, osm_id, name, brand, lat, lon, fuels FROM stations "
        "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?"
    ]
    params = [s, n, w, e]
    if brands:
        wanted = [b.strip() for b in brands.split(",") if b.strip()]
        if wanted:
            sql.append("AND brand IN (%s)" % ",".join("?" * len(wanted)))
            params += wanted
    if fuel and fuel in FUEL_TYPES:
        sql.append("AND fuels LIKE ?")
        params.append(f'%"{fuel}"%')
    sql.append("LIMIT ?")
    params.append(limit)

    rows = conn.execute(" ".join(sql), params).fetchall()
    latest_map, fresh_set = overall_maps(conn)
    out = []
    for r in rows:
        rec = latest_map.get(r["id"])
        if rec is None:
            st, last_at, confirms, stale = None, None, 0, False
        else:
            st, last_at, confirms = rec
            stale = r["id"] not in fresh_set
        if only_with_data and st is None:
            continue
        if status and st != status:
            continue
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "brand": r["brand"],
                "lat": r["lat"],
                "lon": r["lon"],
                "fuels": json.loads(r["fuels"] or "[]"),
                "status": st,
                "color": STATUS_COLOR.get(st, "gray"),
                "last_report": last_at,
                "confirms": confirms,
                "stale": stale,
            }
        )
    return {"count": len(out), "stations": out}


# ---------------------------------------------------------------- station detail
@app.get("/api/stations/{station_id}")
def station_detail(station_id: int):
    conn = db.get_conn()
    r = conn.execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone()
    if not r:
        raise HTTPException(404, "not found")
    st, last_at, confirms, stale = station_overall(conn, station_id)
    reports = conn.execute(
        """
        SELECT id, status, fuel_type, comment, photo, confirms, flags, created_at
        FROM reports WHERE station_id=? AND hidden=0
        ORDER BY created_at DESC LIMIT 30
        """,
        (station_id,),
    ).fetchall()
    return {
        "id": r["id"],
        "name": r["name"],
        "brand": r["brand"],
        "lat": r["lat"],
        "lon": r["lon"],
        "region": r["region"],
        "address": r["address"],
        "fuels": json.loads(r["fuels"] or "[]"),
        "status": st,
        "color": STATUS_COLOR.get(st, "gray"),
        "last_report": last_at,
        "confirms": confirms,
        "stale": stale,
        "fuel_statuses": fuel_statuses(conn, station_id),
        "reports": [dict(x) for x in reports],
    }


# ---------------------------------------------------------------- create report
def _save_photo(upload: UploadFile) -> str | None:
    if not upload or not upload.filename:
        return None
    raw = upload.file.read()
    if not raw:
        return None
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(413, "Фото слишком большое (макс 8МБ)")
    name = f"{int(time.time())}_{secrets.token_hex(6)}.jpg"
    dest = PHOTO_DIR / name
    if HAVE_PIL:
        import io

        try:
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            img.thumbnail((1280, 1280))
            img.save(dest, "JPEG", quality=80)
            return name
        except Exception:  # noqa: BLE001
            pass
    dest.write_bytes(raw)
    return name


@app.post("/api/report")
async def create_report(
    station_id: int = Form(...),
    status: str = Form(...),
    fuel_type: str | None = Form(None),
    comment: str | None = Form(None),
    device_id: str | None = Form(None),
    photo: UploadFile | None = File(None),
):
    if status not in STATUSES:
        raise HTTPException(400, "bad status")
    if fuel_type in ("", "all", "overall"):
        fuel_type = None
    if fuel_type and fuel_type not in FUEL_TYPES:
        raise HTTPException(400, "bad fuel_type")
    conn = db.get_conn()
    if not conn.execute("SELECT 1 FROM stations WHERE id=?", (station_id,)).fetchone():
        raise HTTPException(404, "station not found")
    # rate limit per device per station
    if device_id:
        recent = conn.execute(
            "SELECT created_at FROM reports WHERE station_id=? AND device_id=? "
            "ORDER BY created_at DESC LIMIT 1",
            (station_id, device_id),
        ).fetchone()
        if recent:
            secs = conn.execute(
                "SELECT (julianday('now')-julianday(?))*86400 d", (recent["created_at"],)
            ).fetchone()["d"]
            if secs is not None and secs < REPORT_COOLDOWN_SEC:
                raise HTTPException(429, "Слишком часто, подождите немного")
    photo_name = _save_photo(photo) if photo else None
    if comment:
        comment = comment.strip()[:500]
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO reports (station_id, status, fuel_type, comment, photo, device_id) "
            "VALUES (?,?,?,?,?,?)",
            (station_id, status, fuel_type, comment, photo_name, device_id),
        )
        rid = cur.lastrowid
    return {"ok": True, "report_id": rid}


# ---------------------------------------------------------------- confirm / flag
@app.post("/api/reports/{report_id}/confirm")
def confirm_report(report_id: int, payload: dict):
    device_id = (payload or {}).get("device_id") or ""
    kind = (payload or {}).get("kind", "confirm")
    kind = "dispute" if kind == "dispute" else "confirm"
    conn = db.get_conn()
    if not conn.execute("SELECT 1 FROM reports WHERE id=?", (report_id,)).fetchone():
        raise HTTPException(404, "report not found")
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO confirmations (report_id, device_id, kind) VALUES (?,?,?)",
                (report_id, device_id, kind),
            )
            if kind == "confirm":
                cur.execute("UPDATE reports SET confirms=confirms+1 WHERE id=?", (report_id,))
            else:
                cur.execute("UPDATE reports SET flags=flags+1 WHERE id=?", (report_id,))
                cur.execute("UPDATE reports SET hidden=1 WHERE id=? AND flags>=3", (report_id,))
    except Exception:  # noqa: BLE001 (unique violation = already voted)
        raise HTTPException(409, "Вы уже голосовали")
    return {"ok": True}


@app.post("/api/reports/{report_id}/flag")
def flag_report(report_id: int, payload: dict):
    return confirm_report(report_id, {**(payload or {}), "kind": "dispute"})


# ---------------------------------------------------------------- subscriptions
@app.post("/api/subscribe")
def subscribe(payload: dict):
    station_id = (payload or {}).get("station_id")
    device_id = (payload or {}).get("device_id")
    fuel_type = (payload or {}).get("fuel_type")
    if not station_id or not device_id:
        raise HTTPException(400, "station_id and device_id required")
    with db.cursor() as cur:
        cur.execute(
            "INSERT OR IGNORE INTO subscriptions (station_id, device_id, fuel_type) "
            "VALUES (?,?,?)",
            (station_id, device_id, fuel_type),
        )
    return {"ok": True}


@app.delete("/api/subscribe")
def unsubscribe(station_id: int, device_id: str, fuel_type: str | None = None):
    with db.cursor() as cur:
        if fuel_type:
            cur.execute(
                "DELETE FROM subscriptions WHERE station_id=? AND device_id=? AND fuel_type=?",
                (station_id, device_id, fuel_type),
            )
        else:
            cur.execute(
                "DELETE FROM subscriptions WHERE station_id=? AND device_id=?",
                (station_id, device_id),
            )
    return {"ok": True}


@app.get("/api/subscriptions")
def list_subscriptions(device_id: str):
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT sub.station_id, sub.fuel_type, s.name, s.brand, s.lat, s.lon
        FROM subscriptions sub JOIN stations s ON s.id = sub.station_id
        WHERE sub.device_id=?
        """,
        (device_id,),
    ).fetchall()
    out = []
    for r in rows:
        st, last_at, confirms, stale = station_overall(conn, r["station_id"])
        out.append({**dict(r), "status": st, "color": STATUS_COLOR.get(st, "gray"),
                    "last_report": last_at, "stale": stale})
    return {"subscriptions": out}


# ---------------------------------------------------------------- analytics
@app.get("/api/analytics")
def analytics():
    conn = db.get_conn()
    win = window_expr(STALE_HOURS)
    # region load: counts of latest-report statuses grouped by region
    by_region = conn.execute(
        """
        WITH latest AS (
            SELECT r.station_id, r.status,
                   ROW_NUMBER() OVER (PARTITION BY r.station_id ORDER BY r.created_at DESC) rn
            FROM reports r WHERE r.hidden=0 AND r.created_at >= datetime('now', ?)
        )
        SELECT COALESCE(s.region, 'Не указан') region,
               SUM(CASE WHEN l.status='none' THEN 1 ELSE 0 END) no_fuel,
               SUM(CASE WHEN l.status='queue' THEN 1 ELSE 0 END) queues,
               SUM(CASE WHEN l.status='have' THEN 1 ELSE 0 END) have,
               COUNT(*) reported
        FROM latest l JOIN stations s ON s.id=l.station_id
        WHERE l.rn=1
        GROUP BY s.region ORDER BY reported DESC LIMIT 40
        """,
        (win,),
    ).fetchall()
    by_hour = conn.execute(
        """
        SELECT CAST(strftime('%H', created_at) AS INT) hour,
               SUM(CASE WHEN status='none' THEN 1 ELSE 0 END) no_fuel,
               SUM(CASE WHEN status='queue' THEN 1 ELSE 0 END) queues,
               COUNT(*) total
        FROM reports WHERE hidden=0 AND created_at >= datetime('now','-7 days')
        GROUP BY hour ORDER BY hour
        """,
    ).fetchall()
    totals = conn.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM stations) stations,
          (SELECT COUNT(*) FROM reports WHERE created_at >= datetime('now','-24 hours')) reports_24h,
          (SELECT COUNT(*) FROM reports) reports_total
        """
    ).fetchone()
    return {
        "totals": dict(totals),
        "by_region": [dict(x) for x in by_region],
        "by_hour": [dict(x) for x in by_hour],
    }


# ---------------------------------------------------------------- photos
@app.get("/api/photos/{name}")
def get_photo(name: str):
    p = (PHOTO_DIR / name).resolve()
    if PHOTO_DIR.resolve() not in p.parents or not p.exists():
        raise HTTPException(404, "not found")
    return FileResponse(p)


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------------- static frontend
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
