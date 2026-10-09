#!/usr/bin/env python3
"""Match-alert tagger: when the "Matches at Carbon" message is posted, reply to it tagging everyone.

Run on its own:   python listener.py
Or together with the scam moderator:   python bot.py   (recommended)
Needs: pip install flask requests python-dotenv
"""
import os
import re
import threading
import time

from dotenv import load_dotenv
from flask import Flask, request, jsonify

load_dotenv()
import carbon_bot  # WAHA settings + send_with_tag_all()

TAG_TEXT = os.getenv("TAG_TEXT", "*MATCHES WAITING @ CARBON* 🎾 @all")
TRIGGER_SENDER = re.sub(r"\D", "", os.getenv("TRIGGER_SENDER", ""))  # only react to this number (blank = anyone)
DELAY_SECONDS = float(os.getenv("DELAY_SECONDS", "2"))
REPLY_TO_ALERT = os.getenv("REPLY_TO_ALERT", "1") == "1"   # quote the match message in the tag
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"
MODE = os.getenv("TAG_MODE", "list")
# Also react when the match message is sent FROM the bot's own number (e.g. typed on the bot phone),
# which is how it would work if the same bot both posts the games and tags everyone.
ALLOW_OWN_ALERTS = os.getenv("ALLOW_OWN_ALERTS", "1") == "1"
# 0 = switch the tag-all feature off entirely (e.g. if the match bot already tags everyone in its own alert)
TAG_ENABLED = os.getenv("TAG_ENABLED", "1") == "1"

# The alert always has: the "Matches at Carbon" title, numbered "Match N:" lines,
# the "Book in" line, and app.playtomic links.
TITLE_RE = re.compile(r"matches at carbon", re.I)
MATCH_LINE_RE = re.compile(r"^\s*match \d+\s*:", re.I | re.M)
BOOK_IN_RE = re.compile(r"book in", re.I)
LINK_RE = re.compile(r"app\.playtomic\.\w+/", re.I)

seen_ids = set()
last_fired = 0.0
lock = threading.Lock()


def is_match_alert(body: str) -> bool:
    b = body or ""
    return bool(TITLE_RE.search(b) and MATCH_LINE_RE.search(b) and BOOK_IN_RE.search(b) and LINK_RE.search(b))


def sender_number(payload) -> str:
    """Real phone digits of whoever sent the message, even in groups that hide numbers behind @lid ids."""
    raw = payload.get("participant") or payload.get("author") or ""
    if "@lid" in raw:
        try:
            return carbon_bot.lid_to_phone(carbon_bot.GROUP_ID).get(raw, "")
        except Exception:
            return ""
    return re.sub(r"[:@].*", "", raw)


def chat_of(payload) -> str:
    """The group the message is in (for the bot's own messages WAHA may put the group in 'to')."""
    for key in ("from", "to"):
        v = payload.get(key) or ""
        if v.endswith("@g.us"):
            return v
    return payload.get("from") or ""


def should_fire(payload) -> bool:
    global last_fired
    if not TAG_ENABLED:
        return False
    if chat_of(payload) != carbon_bot.GROUP_ID:
        return False
    if payload.get("fromMe") and not ALLOW_OWN_ALERTS:
        return False
    if not is_match_alert(payload.get("body")):
        return False
    if TRIGGER_SENDER and not payload.get("fromMe") and sender_number(payload) != TRIGGER_SENDER:
        return False
    with lock:
        mid = payload.get("id")
        if mid in seen_ids:
            return False
        # Each message reaches us twice (as 'message' and 'message.any'), so we only skip the SAME message.
        # A new match alert, even an identical copy, always gets its own @all reply.
        seen_ids.add(mid)
        last_fired = time.time()
    return True


def fire(payload):
    time.sleep(DELAY_SECONDS)
    reply_to = payload.get("id") if REPLY_TO_ALERT else None
    if DRY_RUN:
        print("[DRY RUN] would reply with:", TAG_TEXT)
        return
    try:
        carbon_bot.send_with_tag_all(TAG_TEXT, MODE, reply_to=reply_to)
    except Exception as e:
        print("TAG_FAILED:", e)


def handle(payload) -> bool:
    """Returns True if this was a match alert (and tagging was triggered)."""
    if should_fire(payload):
        print("Match alert detected -> tagging everyone")
        threading.Thread(target=fire, args=(payload,), daemon=True).start()
        return True
    return False


app = Flask(__name__)


@app.post("/webhook")
def webhook():
    data = request.get_json(silent=True) or {}
    if data.get("event") in ("message", "message.any"):
        handle(data.get("payload") or {})
    return jsonify(ok=True)


if __name__ == "__main__":
    print(f"Listening for match alerts in {carbon_bot.GROUP_ID or '(GROUP_ID not set!)'}")
    app.run(host="0.0.0.0", port=5000)
