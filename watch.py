import json, os, urllib.request, urllib.parse, urllib.error
from datetime import date, datetime, timedelta

# ---- settings ----------------------------------------------------------
WATCH_FROM = "2026-12-05"
WATCH_TO = "2027-01-20"
HEARTBEAT_HOUR = 8     # Toronto hour for the daily "still watching" message; -1 = off
# ------------------------------------------------------------------------

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
BOOKING_URL = os.environ.get("BOOKING_URL") or "https://clients3.clicsante.ca/5035/take-appt"
BASE = "https://api3.clicsante.ca/v3/establishments/5035"
HEADERS = {
    "accept": "application/json, text/plain, */*",
    "origin": "https://clients3.clicsante.ca",
    "referer": "https://clients3.clicsante.ca/",
    "product": "clicsante",
    "x-trimoz-access-token": "public",
    "x-trimoz-role": "public",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36",
}


def window():
    start = max(date.today(), date.fromisoformat(WATCH_FROM))
    return start, date.fromisoformat(WATCH_TO)


def get(path, start, stop):
    params = {
        "places": 1480, "service": 1915, "timezone": "America/Toronto",
        "filter1": 0, "dateStart": start.isoformat(), "dateStop": stop.isoformat(),
        "gapMode": "false",
    }
    req = urllib.request.Request(f"{BASE}/{path}?" + urllib.parse.urlencode(params), headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code in (204, 404):
            return None
        raise
    return json.loads(body) if body.strip() else None


def open_days():
    start, end = window()
    days, s = set(), start
    while s < end:
        e = min(s + timedelta(days=31), end)
        data = get("schedules/public", s, e)
        if isinstance(data, dict):
            for d in data.get("availabilities") or []:
                d = str(d)[:10]
                if start.isoformat() <= d <= end.isoformat():
                    days.add(d)
        s = e
    return days


def to_local(ts):
    dt = datetime.fromisoformat(ts)
    try:
        from zoneinfo import ZoneInfo
        dt = dt.astimezone(ZoneInfo("America/Toronto"))
    except Exception:
        pass
    return dt


def now_local():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Toronto"))
    except Exception:
        return datetime.utcnow() - timedelta(hours=5)


def earliest_slot():
    start, end = window()
    data = get("availabilities/first", start, end)
    if isinstance(data, dict) and data.get("start"):
        dt = to_local(data["start"])
        if start <= dt.date() <= end:
            return dt
    return None


def notify(message, title, priority):
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"),
        headers={"Click": BOOKING_URL, "Title": title, "Priority": priority})
    urllib.request.urlopen(req, timeout=20).read()


def main():
    manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    error, days, slot_txt = None, set(), ""
    try:
        days = open_days()
        dt = earliest_slot()
        if dt:
            days.add(dt.date().isoformat())
            slot_txt = dt.strftime("%a %b %d at %H:%M")
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    print("open days:", sorted(days), "| earliest:", slot_txt or "none", "| error:", error)

    if days:
        msg = "Open: " + ", ".join(sorted(days))
        if slot_txt:
            msg += " | earliest " + slot_txt
        notify(msg, "Vaccine slot available!", "urgent")
        return

    now = now_local()
    beat = HEARTBEAT_HOUR >= 0 and now.hour == HEARTBEAT_HOUR
    if manual or beat:
        prio = "default" if manual else "low"
        if error:
            notify("Check failed: " + error, "Watcher problem", prio)
        else:
            notify("Watching OK. Nothing open yet.", "Watcher running", prio)


main()
