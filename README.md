# Carbon Padel WhatsApp bot: handover guide

For whoever runs the existing Carbon match-alert bot.

## What it does

1. **Tag-all on match alerts.** When the "Matches at Carbon today…" alert is posted, the bot replies to it with
   `*MATCHES WAITING @ CARBON* 🎾 @all`, and every group member gets a real mention notification.
   The message itself only shows "@all": the individual tags are invisible, so there is no wall of names.
2. **Scam moderation.** Every group message is checked against scam rules:
   - **clear scam** → deleted for everyone, and the owner gets a private message saying what was removed
   - **unclear** → left alone, and the owner gets a private message to decide
   - **normal chat / Playtomic shares** → nothing happens

It runs on **one WhatsApp number**. The intended setup is to run it on the **same number as the existing match bot**,
so no new number, SIM or server is needed.

---

## ⚠️ Important limitations (please read)

**1. Tagging 1,000 members is untested.**
It has been tested in groups of up to 66 people, where every member received the notification.
It has **not** been tested on a group of ~1,000. WhatsApp may handle a message that mentions 1,000 people
differently (slower delivery, partial notifications, or the message failing to send). The first real alert in the
Carbon group is effectively the test, so someone should check the bot's log and ask a few members if they were notified.

**2. Scam detection is rule-based, not AI, and it does not learn.**
It works from a fixed list of scam words and patterns (investment/crypto, assignment help, fake jobs, phishing, loans,
adult spam, invites to other groups, etc.).
- It **will miss** scams worded in a new way. Those still need deleting by hand, and the pattern can then be added to
  the list in `moderator.py`.
- It **may occasionally flag a genuine message.** To limit the damage, uncertain messages are never deleted (the owner
  is told instead), and anything mentioning padel/courts/Carbon/matches is never auto-deleted.
- An optional AI second opinion can be switched on (`ANTHROPIC_API_KEY`), but this is a paid service and is off by default.

**3. It uses an unofficial WhatsApp connection.**
WAHA connects as a "linked device" (like WhatsApp Web). This is against WhatsApp's terms of service, so there is a
small risk WhatsApp restricts or bans **the number it runs on**. If the existing match bot already uses an unofficial
library (Baileys, whatsapp-web.js, WAHA, etc.) it is already in the same position. The group itself and other members'
accounts are not affected by a ban on the bot's number.
If the existing bot uses the **official WhatsApp Business/Cloud API**, this package cannot share its number: that API
does not support this kind of group activity. See "Option 3" below.

**4. It only works while it is running.** Messages posted while it is off are not checked afterwards.

---

## What's needed

- The server/computer that already runs the match bot (or any machine that is always on)
- **Docker** (with Docker Compose)
- ~5 minutes with the match bot's phone to scan a QR code
- The bot's number made a **group admin** in the Carbon group (needed for deleting; tagging works without it)

Cost: **free** (no paid services are used unless the optional AI check is turned on).

---

## Option 1 (recommended): run this package next to the existing bot, on the same number

Nothing in the existing bot needs changing.

1. Copy this folder to the server.
2. `cp .env.example .env` and fill in `WAHA_API_KEY`, `OWNER_NUMBER`, and leave `MOD_MODE=watch` for now.
3. `docker compose up -d`
4. Link the match bot's WhatsApp number as an extra linked device:
   - Start the session:
     `curl -X POST -H "X-Api-Key: YOURKEY" -H "Content-Type: application/json" -d '{"name":"default"}' http://localhost:3000/api/sessions/start`
   - Get the QR code: `curl -H "X-Api-Key: YOURKEY" "http://localhost:3000/api/default/auth/qr?format=image" -o qr.png`
   - On the bot's phone: **WhatsApp → Settings → Linked devices → Link a device**, scan `qr.png` (it refreshes every ~20s).
   - Check: `curl -H "X-Api-Key: YOURKEY" http://localhost:3000/api/sessions` → status `WORKING`.
   - (A WhatsApp account can have up to 4 linked devices, so this sits alongside whatever the existing bot uses.)
5. Find the group ID: `docker compose exec bot python carbon_bot.py --groups`, put it in `.env` as `GROUP_ID`.
6. `docker compose up -d` again to load the new settings. Check the log: `docker compose logs -f bot`
   It should say which group it's on, `own alerts=yes`, and `watch mode`.
7. Because it runs on the same number, it automatically reacts when the bot posts its own match alert
   (`ALLOW_OWN_ALERTS=1`) and replies with the @all tag. `TRIGGER_SENDER` can stay blank.

**Going live safely**
- **Week 1:** `MOD_MODE=watch`. Nothing is deleted; the owner receives a message for everything that *would* have been.
  Check those for mistakes.
- **Week 2:** if happy, make the bot's number a group admin, set `MOD_MODE=delete`, `docker compose up -d`.
- **First tagged alert:** watch `docker compose logs -f bot` for `Sent. Tagged N people` (or `TAG_FAILED`)
  and ask a few members whether they got the notification.

## Option 2: build the tagging into the existing bot's own alert

Cleanest result: the alert itself carries the tags, so there is no second message.
The trick is to send the message with **every member's id in the `mentions` list** while the text just says "@all":

- **WAHA:** `POST /api/sendText` with `{"chatId": GROUP_ID, "text": "...alert...\n\n@all", "mentions": [ ...member ids... ]}`
- **Baileys:** `sock.sendMessage(groupId, { text: alertText + "\n\n@all", mentions: memberJids })`
- **whatsapp-web.js:** `chat.sendMessage(alertText + "\n\n@all", { mentions: memberIds })`

Member ids come from the group's participant list (see `group_member_ids()` in `carbon_bot.py`). In newer groups
WhatsApp identifies members by `...@lid` ids; those worked in testing (`MENTION_IDS=lid`).
The scam moderation can still run via Option 1. Set `TAG_ENABLED=0` there so the alert isn't tagged twice.

## Option 3: existing bot uses the official WhatsApp API

Run this package on a **separate number** instead (a spare SIM), added to the group as a member (admin for deletion).
Set `TRIGGER_SENDER` to the match bot's number so it only tags real alerts.

---

## Settings at a glance (`.env`)

| Setting | What it does |
|---|---|
| `GROUP_ID` | The group the bot works in |
| `OWNER_NUMBER` | Who gets the private "deleted / please check" messages |
| `MOD_MODE` | `watch` = never deletes, `delete` = deletes clear scams |
| `ADMIN_NUMBERS` | Numbers never checked (admins, staff) |
| `TRIGGER_SENDER` | Only tag alerts from this number (blank = any) |
| `TAG_ENABLED` | `1` = tag-all on, `0` = off |
| `TAG_TEXT` | The text of the @all message |
| `MENTION_IDS` | `lid` (default) or `phone`; switch only if notifications stop arriving |

After any change: `docker compose up -d`.

## Turning it off

- **Instantly, from a phone (no tech needed):** a group admin removes the bot's admin rights. It can no longer delete anything.
- **Stop everything:** `docker compose stop bot` on the server.
- **Permanently:** `docker compose down` and unlink it on the phone (Linked devices → log out).

## Adding new scam patterns

Open `moderator.py` and add phrases to the lists near the top:
- `HIGH`: phrases that are always a scam → deleted on their own
- `CATEGORIES`: scam topics → one hit = owner is told, two hits = deleted
Then `docker compose up -d --build`.

## Files

| File | Purpose |
|---|---|
| `bot.py` | Entry point: runs tagging + moderation together |
| `listener.py` | Detects the match alert and sends the @all reply |
| `moderator.py` | Scam rules and actions |
| `carbon_bot.py` | WhatsApp (WAHA) helpers: members, mentions, sending |
| `docker-compose.yml`, `Dockerfile`, `requirements.txt` | Running it |
| `.env.example` | Settings template (copy to `.env`) |

**Never share:** `.env` (contains the key), `waha-sessions/` (contains the WhatsApp login), `logs/` (contains members' messages and numbers).
