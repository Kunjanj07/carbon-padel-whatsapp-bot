#!/usr/bin/env python3
"""Carbon Padel demo bot: posts the match alert to a WhatsApp group and tags everyone.

Talks to a local WAHA container (see docker-compose.yml). Needs: pip install requests python-dotenv
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

WAHA_URL = os.getenv("WAHA_URL", "http://localhost:3000")
WAHA_KEY = os.getenv("WAHA_API_KEY", "")
SESSION = os.getenv("WAHA_SESSION", "default")
GROUP_ID = os.getenv("GROUP_ID", "")  # e.g. 1203630xxxxxxxxx@g.us
PLAYTOMIC_API = "https://api.playtomic.io/v1"
HEADERS = {"X-Api-Key": WAHA_KEY, "Content-Type": "application/json"}

# ---------- WhatsApp (WAHA) ----------

def waha(method, path, **kw):
    r = requests.request(method, f"{WAHA_URL}{path}", headers=HEADERS, timeout=60, **kw)
    r.raise_for_status()
    return r.json() if r.content else {}


def list_groups():
    groups = waha("GET", f"/api/{SESSION}/groups")
    items = groups.values() if isinstance(groups, dict) else groups
    for g in items:
        gid = g.get("id")
        gid = gid.get("_serialized") if isinstance(gid, dict) else gid
        print(f"{gid}  {g.get('name') or g.get('subject')}")


def _jid(x):
    return x.get("_serialized") if isinstance(x, dict) else x


_participants_cache = {}  # group_id -> (fetched_at, [participant dicts])


def group_participants(group_id, max_age=300):
    """Participant list with both the hidden id (@lid) and the real phone number when WhatsApp gives it."""
    import time
    hit = _participants_cache.get(group_id)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    data = None
    try:
        data = waha("GET", f"/api/{SESSION}/groups/{group_id}")
    except Exception:
        pass
    if not (isinstance(data, dict) and data.get("participants")):
        groups = waha("GET", f"/api/{SESSION}/groups")
        data = groups.get(group_id) if isinstance(groups, dict) else next(
            (g for g in groups if _jid(g.get("id")) == group_id), {})
    parts = (data or {}).get("participants") or []
    if not parts:  # last resort: the participants endpoint
        parts = waha("GET", f"/api/{SESSION}/groups/{group_id}/participants")
    _participants_cache[group_id] = (time.time(), parts)
    return parts


def phone_of(p):
    """Best phone number (digits) for a participant dict, or '' if WhatsApp hides it."""
    for key in ("phoneNumber", "pn", "jid"):
        v = _jid(p.get(key)) or ""
        if v and "@lid" not in v:
            return re.sub(r"[:@].*", "", v)
    pid = _jid(p.get("id")) or ""
    return "" if "@lid" in pid else re.sub(r"[:@].*", "", pid)


def lid_to_phone(group_id):
    """{'123456789012345@lid': '447700900123', ...} so we can show/check real numbers."""
    out = {}
    for p in group_participants(group_id):
        pid, ph = _jid(p.get("id")) or "", phone_of(p)
        if pid and ph:
            out[pid] = ph
    return out


def my_number():
    me = waha("GET", f"/api/sessions/{SESSION}").get("me", {}) or {}
    return re.sub(r"[:@].*", "", _jid(me.get("id")) or "")


MENTION_IDS = os.getenv("MENTION_IDS", "lid").lower()   # lid | phone  (which id type to tag people with)


def group_member_ids(group_id, exclude_self=True):
    """Mention ids for everyone in the group.
    MENTION_IDS=lid   -> the group's own hidden ids (what WhatsApp itself uses in 'lid' groups like yours)
    MENTION_IDS=phone -> real phone numbers (@c.us)"""
    me = my_number() if exclude_self else ""
    ids = []
    for p in group_participants(group_id):
        ph, pid = phone_of(p), _jid(p.get("id")) or ""
        if ph and ph == me:
            continue
        if MENTION_IDS == "phone" and ph:
            ids.append(f"{ph}@c.us")
        else:
            ids.append(pid or (f"{ph}@c.us" if ph else ""))
    return [i for i in ids if i]


def send_with_tag_all(text, mode="list", reply_to=None):
    # mode "list": every member goes in the mentions array, so each person gets a real tag notification
    #              while the message itself only shows the short text (e.g. "@all").
    # mode "all":  experimental, asks WAHA for a native mention-everyone.
    mentions = ["all"] if mode == "all" else group_member_ids(GROUP_ID)
    payload = {"session": SESSION, "chatId": GROUP_ID, "text": text, "mentions": mentions}
    if reply_to:
        payload["reply_to"] = reply_to
    res = waha("POST", "/api/sendText", json=payload)
    print(f"Sent. Tagged {len(mentions)} people ({mode} mode, {MENTION_IDS} ids){' as a reply' if reply_to else ''}.")
    return res

# ---------- Playtomic ----------

def match_id_from_link(link):
    m = re.search(r"matches/([0-9a-f-]{36})", link)
    return m.group(1) if m else link.strip()


def fetch_match(match_id):
    r = requests.get(f"{PLAYTOMIC_API}/matches/{match_id}", timeout=30,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json()


def summarise(raw):
    """Pull the fields we need. Playtomic's API is unofficial, so field names are
    read defensively: run with --dump once and adjust here if anything shows blank."""
    start = raw.get("start_date") or raw.get("start") or ""
    try:
        t = datetime.fromisoformat(start.replace("Z", "+00:00"))
        # Playtomic returns UTC; convert to UK time
        from zoneinfo import ZoneInfo
        t = t.astimezone(ZoneInfo("Europe/London"))
        time_str = t.strftime("%-I:%M%p").lower().replace(":00", ":00")
    except Exception:
        time_str = "?"
    lo = raw.get("min_level", raw.get("min_skill_level", "?"))
    hi = raw.get("max_level", raw.get("max_skill_level", "?"))
    players = sum(len(team.get("players", [])) for team in raw.get("teams", []))
    max_players = raw.get("max_players") or 4
    return {"time": time_str, "lo": lo, "hi": hi, "spots": max(max_players - players, 0),
            "id": raw.get("match_id") or raw.get("id", "")}


def build_message(matches, window, tag_line):
    lines = [f"*Matches at Carbon today, {window} 🎾🚀*", ""]
    for i, m in enumerate(matches, 1):
        s = "spot" if m["spots"] == 1 else "spots"
        lines.append(f"Match {i}: {m['time']} · Level {m['lo']}–{m['hi']} · {m['spots']} {s}")
    lines += ["", "Book in 🙌🔗"]
    for i, m in enumerate(matches, 1):
        lines.append(f"{i} → {m['time']}  app.playtomic.io/matches/{m['id']}")
    lines += ["", tag_line]
    return "\n".join(lines)

SAMPLE = [
    {"time": "3:00pm", "lo": "1.5", "hi": "3", "spots": 2, "id": "5b8b941a-be72-4990-9152-e6244843a76d"},
    {"time": "4:00pm", "lo": "2.4", "hi": "3.7", "spots": 1, "id": "60fca93c-0ce8-4ac7-980f-d1d5ba3d75a1"},
    {"time": "4:30pm", "lo": "1.1", "hi": "2.4", "spots": 2, "id": "3affd147-5db2-4566-a50b-e8e5cc321291"},
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", action="store_true", help="list groups the bot is in (to find GROUP_ID)")
    ap.add_argument("--sample", action="store_true", help="use hardcoded sample matches")
    ap.add_argument("--links", nargs="*", help="Playtomic match links/IDs to read live data from")
    ap.add_argument("--dump", action="store_true", help="print raw Playtomic JSON for the links and exit")
    ap.add_argument("--dry-run", action="store_true", help="print the message, do not send")
    ap.add_argument("--mode", choices=["list", "all"], default="list")
    ap.add_argument("--window", default="3:00-9:00pm")
    a = ap.parse_args()

    if a.groups:
        return list_groups()

    if a.links:
        raws = [fetch_match(match_id_from_link(l)) for l in a.links]
        if a.dump:
            print(json.dumps(raws, indent=2)[:6000]); return
        matches = [summarise(r) for r in raws]
    elif a.sample:
        matches = SAMPLE
    else:
        sys.exit("Use --sample or --links <playtomic links>")

    text = build_message(matches, a.window, "*MATCHES WAITING @ CARBON* 🎾 @all")
    print(text, "\n")
    if a.dry_run:
        return
    if not GROUP_ID:
        sys.exit("Set GROUP_ID in .env (run with --groups to find it)")
    send_with_tag_all(text, a.mode)

if __name__ == "__main__":
    main()
