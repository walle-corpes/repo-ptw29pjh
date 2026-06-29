"""Standalone long-polling worker for the Telegram moderation bot.

Run as:  python -m app.bot_worker

Handles:
  * inline button callbacks ``ok:<id>`` / ``no:<id>`` -> approve/reject report;
  * ``/start`` (and any message) -> replies with the chat_id so the owner can
    be added to TELEGRAM_ADMIN_IDS.
"""
import logging
import time

import httpx

from . import db
from .config import TELEGRAM_ADMIN_IDS, TELEGRAM_ENABLED
from .telegram import API, _call, set_report_moderation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("azs.bot")


def _is_admin(uid) -> bool:
    # if no admins configured yet, allow nobody to moderate (only chat-id help)
    return str(uid) in TELEGRAM_ADMIN_IDS


def _handle_callback(cb: dict):
    data = cb.get("data") or ""
    cb_id = cb["id"]
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    msg_id = msg.get("message_id")
    uid = (cb.get("from") or {}).get("id")

    if ":" not in data:
        _call("answerCallbackQuery", {"callback_query_id": cb_id})
        return
    decision, _, rid_s = data.partition(":")
    if not _is_admin(uid):
        _call(
            "answerCallbackQuery",
            {"callback_query_id": cb_id, "text": "Нет прав на модерацию", "show_alert": True},
        )
        return
    try:
        rid = int(rid_s)
    except ValueError:
        _call("answerCallbackQuery", {"callback_query_id": cb_id})
        return

    new = set_report_moderation(rid, decision)
    if new is None:
        _call(
            "answerCallbackQuery",
            {"callback_query_id": cb_id, "text": "Отчёт не найден", "show_alert": True},
        )
        return

    approved = new == "approved"
    toast = "✅ Подтверждено" if approved else "🚫 Отклонено"
    _call("answerCallbackQuery", {"callback_query_id": cb_id, "text": toast})

    # strip buttons and mark the decision in the message
    suffix = f"\n\n— {toast} (#{rid})"
    if msg.get("photo"):
        _call(
            "editMessageCaption",
            {
                "chat_id": chat_id,
                "message_id": msg_id,
                "caption": (msg.get("caption") or "") + suffix,
                "parse_mode": "HTML",
            },
        )
    else:
        _call(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": msg_id,
                "text": (msg.get("text") or "") + suffix,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )


def _handle_message(m: dict):
    chat = m.get("chat") or {}
    chat_id = chat.get("id")
    uid = (m.get("from") or {}).get("id")
    text = (m.get("text") or "").strip()
    if chat_id is None:
        return
    is_admin = _is_admin(uid)
    role = "✅ Вы добавлены как модератор." if is_admin else (
        "Чтобы подтверждать отчёты, передайте этот chat_id администратору "
        "для добавления в список модераторов."
    )
    _call(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": (
                "🤖 <b>АЗС Онлайн — бот модерации</b>\n"
                f"Ваш chat_id: <code>{chat_id}</code>\n\n{role}"
            ),
            "parse_mode": "HTML",
        },
    )


def main():
    if not TELEGRAM_ENABLED:
        log.error("TELEGRAM_BOT_TOKEN not set; bot worker idle.")
        return
    db.init_db()
    log.info("bot worker started; admins=%s", TELEGRAM_ADMIN_IDS or "(none yet)")
    offset = None
    while True:
        try:
            params = {"timeout": 25}
            if offset is not None:
                params["offset"] = offset
            r = httpx.get(f"{API}/getUpdates", params=params, timeout=35)
            data = r.json()
            if not data.get("ok"):
                log.warning("getUpdates failed: %s", data)
                time.sleep(3)
                continue
            for upd in data["result"]:
                offset = upd["update_id"] + 1
                if "callback_query" in upd:
                    _handle_callback(upd["callback_query"])
                elif "message" in upd:
                    _handle_message(upd["message"])
        except Exception as e:  # noqa: BLE001
            log.warning("poll error: %s", e)
            time.sleep(3)


if __name__ == "__main__":
    main()
