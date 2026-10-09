#!/usr/bin/env python3
"""Runs BOTH features on one webhook:
  - match alert posted  -> reply tagging everyone (listener.py)
  - any other message   -> scam check (moderator.py)

Run:  python bot.py      (instead of listener.py / moderator.py)
"""
import threading

from flask import Flask, request, jsonify

import listener
import moderator
import carbon_bot

app = Flask(__name__)


@app.post("/webhook")
def webhook():
    data = request.get_json(silent=True) or {}
    # "message.any" also includes messages sent from the bot's own phone (needed for own match alerts)
    if data.get("event") in ("message", "message.any"):
        payload = data.get("payload") or {}
        if not listener.handle(payload):
            threading.Thread(target=moderator.handle, args=(payload,), daemon=True).start()
    return jsonify(ok=True)


if __name__ == "__main__":
    print(f"Carbon bot running on group {carbon_bot.GROUP_ID or '(GROUP_ID not set!)'}")
    print(f"  Tag-all on match alerts: {'ON' if listener.TAG_ENABLED else 'OFF'} (reply={'yes' if listener.REPLY_TO_ALERT else 'no'}, "
          f"trigger sender={listener.TRIGGER_SENDER or 'anyone'}, own alerts={'yes' if listener.ALLOW_OWN_ALERTS else 'no'}, "
          f"mode={listener.MODE}, ids={carbon_bot.MENTION_IDS})")
    print(f"  Scam moderator: {moderator.MOD_MODE} mode, Claude check {'ON' if moderator.API_KEY else 'OFF'}")
    app.run(host="0.0.0.0", port=5000)
