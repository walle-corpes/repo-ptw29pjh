"""Helpers to turn raw reports into station statuses."""
from .config import FRESH_HOURS, FUEL_TYPES, STALE_HOURS

# status -> map colour key used by the frontend
STATUS_COLOR = {
    "have": "green",
    "low": "amber",
    "queue": "yellow",
    "none": "red",
    "closed": "black",
}


def window_expr(hours):
    return f"-{hours} hours"


def station_overall(conn, station_id):
    """Return (status, last_report_at, confirms, stale) for the station overall."""
    row = conn.execute(
        """
        SELECT status, created_at, confirms
        FROM reports
        WHERE station_id=? AND hidden=0 AND created_at >= datetime('now', ?)
        ORDER BY created_at DESC LIMIT 1
        """,
        (station_id, window_expr(STALE_HOURS)),
    ).fetchone()
    if not row:
        return None, None, 0, False
    fresh = conn.execute(
        "SELECT 1 FROM reports WHERE station_id=? AND hidden=0 "
        "AND created_at >= datetime('now', ?) LIMIT 1",
        (station_id, window_expr(FRESH_HOURS)),
    ).fetchone()
    return row["status"], row["created_at"], row["confirms"], (fresh is None)


def fuel_statuses(conn, station_id):
    """Latest status per fuel type within the stale window."""
    out = {}
    for f in FUEL_TYPES:
        row = conn.execute(
            """
            SELECT status, created_at FROM reports
            WHERE station_id=? AND fuel_type=? AND hidden=0
              AND created_at >= datetime('now', ?)
            ORDER BY created_at DESC LIMIT 1
            """,
            (station_id, f, window_expr(STALE_HOURS)),
        ).fetchone()
        if row:
            out[f] = {"status": row["status"], "updated_at": row["created_at"]}
    return out
