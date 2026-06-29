"""Telegram moderation bot helpers.

Two roles:
  * the FastAPI app calls ``notify_new_report`` to push a pending report to
    all admins with inline ✅/🚫 buttons;
  * the standalone bot worker (``bot_worker.py``) long-polls Telegram, handles
    the button callbacks and ``/start``, and approves/rejects reports.

Both share the low-level API helpers and the message formatting here.
"""
import logging

import httpx

from . import db
from .config import (
    FUEL_LABELS,
    PUBLIC_BASE_URL,
    STATUS_LABELS,
    TELEGRAM_ADMIN_IDS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_ENABLED,
)

log = logging.getLogger("azs.telegram")

API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

STATUS_EMOJI = {
    "have": "🟢",
    "low": "🟡",
    "queue": "🟠",
    "none": "🔴",
    "closed": "⚫️",
}


def _call(method: str, payload: dict, timeout: float = 15.0) -> dict | None:
    """Call a Telegram Bot API method; return the result dict or None."""
    if not TELEGRAM_ENABLED:
        return None
    try:
        r = httpx.post(f"{API}/{method}", json=payload, timeout=timeout)
        data = r.json()
        if not data.get("ok"):
            log.warning("telegram %s failed: %s", method, data)
            return None
        return data.get("result")
    except Exception as e:  # noqa: BLE001
        log.warning("telegram %s error: %s", method, e)
        return None


def _moderation_keyboard(report_id: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Подтвердить", "callback_data": f"ok:{report_id}"},
                {"text": "🚫 Отклонить", "callback_data": f"no:{report_id}"},
            ]
        ]
    }


def _report_caption(rep: dict) -> str:
    fuel = FUEL_LABELS.get(rep["fuel_type"], "Все виды") if rep["fuel_type"] else "Все виды"
    status = STATUS_LABELS.get(rep["status"], rep["status"])
    emoji = STATUS_EMOJI.get(rep["status"], "•")
    brand = rep.get("brand") or ""
    name = rep.get("name") or "АЗС"
    where = rep.get("address") or rep.get("region") or ""
    lat, lon = rep.get("lat"), rep.get("lon")
    lines = [
        f"🆕 <b>Новый отчёт на проверку</b> #{rep['id']}",
        f"🏷 {(brand + ' ').strip()} {name}".strip(),
    ]
    if where:
        lines.append(f"📍 {where}")
    lines.append(f"⛽️ {fuel}: {emoji} <b>{status}</b>")
    if rep.get("comment"):
        lines.append(f"💬 {rep['comment']}")
    if lat is not None and lon is not None:
        lines.append(f'🗺 <a href="https://yandex.ru/maps/?pt={lon},{lat}&z=17&l=map">на карте</a>')
    return "\n".join(lines)


def notify_new_report(report_id: int) -> None:
    """Send a pending report to every configured admin with action buttons."""
    if not TELEGRAM_ENABLED or not TELEGRAM_ADMIN_IDS:
        return
    conn = db.get_conn()
    rep = conn.execute(
        """
        SELECT r.id, r.status, r.fuel_type, r.comment, r.photo,
               s.name, s.brand, s.address, s.region, s.lat, s.lon
        FROM reports r JOIN stations s ON s.id = r.station_id
        WHERE r.id=?
        """,
        (report_id,),
    ).fetchone()
    if not rep:
        return
    rep = dict(rep)
    caption = _report_caption(rep)
    kb = _moderation_keyboard(report_id)
    photo_url = f"{PUBLIC_BASE_URL}/api/photos/{rep['photo']}" if rep.get("photo") else None
    for chat_id in TELEGRAM_ADMIN_IDS:
        if photo_url:
            ok = _call(
                "sendPhoto",
                {
                    "chat_id": chat_id,
                    "photo": photo_url,
                    "caption": caption,
                    "parse_mode": "HTML",
                    "reply_markup": kb,
                },
            )
            if ok:
                continue  # photo sent (with caption + buttons)
        _call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": caption,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": kb,
            },
        )


def set_report_moderation(report_id: int, decision: str) -> str | None:
    """Apply an admin decision. Returns the new moderation value or None if gone."""
    conn = db.get_conn()
    row = conn.execute(
        "SELECT moderation FROM reports WHERE id=?", (report_id,)
    ).fetchone()
    if not row:
        return None
    new = "approved" if decision == "ok" else "rejected"
    with db.cursor() as cur:
        cur.execute("UPDATE reports SET moderation=? WHERE id=?", (new, report_id))
    return new
