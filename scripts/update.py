"""Sammelt alle Daten fuer das Dashboard und schreibt data.json.

Laeuft alle 30 Minuten per GitHub Actions (.github/workflows/update.yml).
Nur Python-Standardbibliothek, damit nichts installiert werden muss.

Optionale Einstellungen (GitHub: Settings -> Secrets and variables -> Actions):
  Secret   YT_API_KEY   YouTube-Data-API-Schluessel
  Variable YT_CHANNELS  Kanaele, mit Komma getrennt: @handle oder UC...-Kanal-ID
"""
import datetime as dt
import email.utils
import html
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data.json")
HISTORY = os.path.join(ROOT, "history.json")
TZ = ZoneInfo("Europe/Berlin")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) tv-dashboard/1.0"}

NEWS_FEEDS = [
    ("Tagesschau", "https://www.tagesschau.de/wirtschaft/finanzen/index~rss2.xml"),
    ("finanzen.net", "https://www.finanzen.net/rss/news"),
    ("n-tv", "https://www.n-tv.de/wirtschaft/rss"),
]
ETF = "EUNL.DE"  # iShares Core MSCI World (Xetra), steht fuer den MSCI World


def get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ---------- MSCI World ----------
def market():
    j = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ETF}?range=1y&interval=1d"))
    res = j["chart"]["result"][0]
    meta = res["meta"]
    closes = res["indicators"]["quote"][0]["close"]
    pts = [(t, round(c, 2)) for t, c in zip(res["timestamp"], closes) if c is not None]
    price = round(meta.get("regularMarketPrice") or pts[-1][1], 2)
    # Vortag = vorletzter Schlusskurs (chartPreviousClose bezieht sich bei range=1y auf vor einem Jahr)
    prev = pts[-2][1] if len(pts) > 1 else price
    if pts and dt.datetime.fromtimestamp(pts[-1][0], TZ).date() < dt.datetime.now(TZ).date():
        prev = pts[-1][1]

    def change(days):
        if len(pts) <= days:
            return None
        base = pts[-days - 1][1]
        return round((price - base) / base * 100, 2)

    year = [p[1] for p in pts]
    return {
        "name": "MSCI World",
        "symbol": ETF,
        "label": "iShares Core MSCI World · Xetra",
        "currency": meta.get("currency", "EUR"),
        "price": price,
        "change_pct": round((price - prev) / prev * 100, 2) if prev else 0,
        "change_abs": round(price - prev, 2),
        "change_30d": change(21),
        "change_1y": round((price - year[0]) / year[0] * 100, 2) if year else None,
        "high_1y": max(year) if year else None,
        "low_1y": min(year) if year else None,
        "spark": year[-30:],
        "year": [[dt.datetime.fromtimestamp(t, TZ).strftime("%Y-%m-%d"), c] for t, c in pts],
        "market_time": dt.datetime.fromtimestamp(meta.get("regularMarketTime", pts[-1][0]), TZ).isoformat(),
    }


# ---------- News ----------
def clean(text):
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def news():
    items, seen = [], set()
    for source, url in NEWS_FEEDS:
        try:
            root = ET.fromstring(get(url))
        except Exception as e:  # eine kaputte Quelle soll den Rest nicht stoppen
            print("News-Quelle fehlgeschlagen:", source, e)
            continue
        for it in root.iter("item"):
            title = clean(it.findtext("title"))
            key = title.lower()[:60]
            if not title or key in seen:
                continue
            seen.add(key)
            try:
                when = email.utils.parsedate_to_datetime(it.findtext("pubDate")).astimezone(TZ)
            except Exception:
                when = dt.datetime.now(TZ)
            desc = clean(it.findtext("description"))
            items.append({
                "title": title,
                "text": desc[:400],
                "source": source,
                "time": when.isoformat(),
                "link": (it.findtext("link") or "").strip(),
            })
    items.sort(key=lambda x: x["time"], reverse=True)
    return items[:12]


# ---------- YouTube ----------
def yt(path, **params):
    params["key"] = os.environ["YT_API_KEY"]
    return json.loads(get("https://www.googleapis.com/youtube/v3/" + path + "?" + urllib.parse.urlencode(params)))


def num(text):
    """'1.234 Aufrufe' / '1,234 views' / '1 Abonnent' -> 1234"""
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else 0


def channel_public(handle):
    """Ohne API-Schluessel: oeffentliche Kanalseite + Video-Feed (letzte 15 Videos mit Aufrufen)."""
    page = get(f"https://www.youtube.com/{handle}/about").decode("utf-8", "replace")
    cid = re.search(r'"externalId":"(UC[\w-]+)"', page) or re.search(r'"channelId":"(UC[\w-]+)"', page)
    if not cid:
        raise RuntimeError(f"Kanal {handle} nicht gefunden")
    title = re.search(r'<meta property="og:title" content="([^"]*)"', page)
    views = re.search(r'"viewCountText":"([^"]*)"', page)
    subs = re.search(r'"subscriberCountText":"([^"]*)"', page)
    vcount = re.search(r'"videoCountText":"([^"]*)"', page)
    ns = {"a": "http://www.w3.org/2005/Atom", "m": "http://search.yahoo.com/mrss/"}
    feed = ET.fromstring(get("https://www.youtube.com/feeds/videos.xml?channel_id=" + cid.group(1)))
    videos = []
    for e in feed.findall("a:entry", ns):
        st = e.find("m:group/m:community/m:statistics", ns)
        videos.append({
            "title": e.findtext("a:title", "", ns),
            "published": dt.datetime.fromisoformat(e.findtext("a:published", "", ns)).astimezone(TZ).isoformat(),
            "views": int(st.get("views", 0)) if st is not None else 0,
        })
    total = num(views.group(1)) if views else sum(v["views"] for v in videos)
    return {
        "id": cid.group(1),
        "name": html.unescape(title.group(1)) if title else handle,
        "views": total,
        "subs": num(subs.group(1)) if subs else 0,
        "videos_total": num(vcount.group(1)) if vcount else len(videos),
        "latest": videos,
    }


def youtube(history):
    key = os.environ.get("YT_API_KEY")
    raw = os.environ.get("YT_CHANNELS") or "@GtaSix_clipsdaily"
    chans = [c.strip() for c in raw.split(",") if c.strip()]
    today = dt.datetime.now(TZ).date()
    out = []
    if not key:
        for c in chans:
            ch = channel_public(c)
            ch["uploads_today"] = sum(1 for v in ch["latest"] if dt.datetime.fromisoformat(v["published"]).date() == today)
            out.append(ch)
    for c in (chans if key else []):
        q = {"forHandle": c} if c.startswith("@") else {"id": c}
        items = yt("channels", part="snippet,statistics,contentDetails", **q).get("items", [])
        if not items:
            print("Kanal nicht gefunden:", c)
            continue
        ch = items[0]
        st = ch["statistics"]
        uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
        pl = yt("playlistItems", part="contentDetails,snippet", playlistId=uploads, maxResults=10).get("items", [])
        ids = [p["contentDetails"]["videoId"] for p in pl]
        stats = {}
        if ids:
            for v in yt("videos", part="statistics", id=",".join(ids)).get("items", []):
                stats[v["id"]] = int(v["statistics"].get("viewCount", 0))
        videos = []
        for p in pl:
            vid = p["contentDetails"]["videoId"]
            pub = p["contentDetails"].get("videoPublishedAt") or p["snippet"]["publishedAt"]
            videos.append({
                "title": p["snippet"]["title"],
                "published": dt.datetime.fromisoformat(pub.replace("Z", "+00:00")).astimezone(TZ).isoformat(),
                "views": stats.get(vid, 0),
            })
        out.append({
            "id": ch["id"],
            "name": ch["snippet"]["title"],
            "views": int(st.get("viewCount", 0)),
            "subs": int(st.get("subscriberCount", 0)),
            "videos_total": int(st.get("videoCount", 0)),
            "uploads_today": sum(1 for v in videos if dt.datetime.fromisoformat(v["published"]).date() == today),
            "latest": videos[:6],
        })
    total = sum(c["views"] for c in out)
    # "Heute" = Zuwachs seit dem letzten Stand von gestern (oder seit dem ersten Stand von heute)
    days = history.setdefault("views", {})
    ytd = (today - dt.timedelta(days=1)).isoformat()
    base = days.get(ytd, {}).get("last") or days.get(today.isoformat(), {}).get("first") or total
    days.setdefault(today.isoformat(), {"first": total})["last"] = total
    for d in sorted(days)[:-14]:
        del days[d]
    return {
        "configured": True,
        "channels": out,
        "views_total": total,
        "views_today": max(0, total - base),
        "views_yesterday": (days.get(ytd, {}).get("last", 0) - days.get(ytd, {}).get("first", 0)) if ytd in days else None,
        "uploads_today": sum(c["uploads_today"] for c in out),
        "subs_total": sum(c["subs"] for c in out),
    }


# ---------- Manager ----------
def fmt(n):
    return f"{n:,}".replace(",", ".")


def manager(m, y, now):
    h = now.hour
    hi = "Guten Morgen" if h < 11 else "Guten Tag" if h < 18 else "Guten Abend"
    lines = [f"{hi}, Sir."]
    if y.get("configured"):
        wer = "Dein Kanal steht" if len(y["channels"]) == 1 else "Deine Kanäle stehen"
        if y.get("views_yesterday") is None and y["views_today"] == 0:
            lines.append(f"{wer} bei {fmt(y['views_total'])} Aufrufen. Die Tageszählung läuft ab jetzt mit.")
        else:
            lines.append(f"{wer} bei {fmt(y['views_total'])} Aufrufen, heute kamen {fmt(y['views_today'])} dazu.")
        if y.get("views_yesterday"):
            diff = y["views_today"] - y["views_yesterday"]
            lines.append("Das liegt schon über gestern." if diff > 0 else f"Bis zum Stand von gestern fehlen noch {fmt(-diff)}.")
        up = y["uploads_today"]
        lines.append("Heute ist noch kein Short online gegangen." if up == 0 else
                     f"Heute {'ist 1 Short' if up == 1 else f'sind {up} Shorts'} online gegangen.")
        vids = [v for c in y["channels"] for v in c["latest"]]
        if vids:
            best = max(vids, key=lambda v: v["views"])
            lines.append(f"Stärkstes der letzten Videos: „{best['title'][:60]}“ mit {fmt(best['views'])} Aufrufen.")
    else:
        lines.append("Der Shorts-Bot ist noch nicht mit mir verbunden. Sobald der Kanal eingetragen ist, berichte ich hier.")
    if m:
        d = m["change_pct"]
        trend = "legt zu" if d > 0.15 else "gibt nach" if d < -0.15 else "bewegt sich seitwärts"
        de = lambda x, sign="": format(x, sign + ".2f").replace(".", ",")
        lines.append(f"Der MSCI World {trend}: {de(d, '+')} % auf {de(m['price'])} €.")
    return " ".join(lines)


def main():
    now = dt.datetime.now(TZ)
    old = load(DATA, {})
    history = load(HISTORY, {})
    errors = []
    try:
        m = market()
    except Exception as e:
        errors.append(f"Kurs: {e}")
        m = old.get("market")
    try:
        n = news() or old.get("news", [])
    except Exception as e:
        errors.append(f"News: {e}")
        n = old.get("news", [])
    try:
        y = youtube(history)
    except Exception as e:
        errors.append(f"YouTube: {e}")
        y = old.get("youtube", {"configured": False})
    report = manager(m, y, now)
    log = history.setdefault("manager", [])
    log.insert(0, {"time": now.isoformat(), "text": report})
    del log[24:]
    data = {"updated": now.isoformat(), "market": m, "news": n, "youtube": y,
            "manager": {"text": report, "log": log}, "errors": errors}
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)
    print("OK", now.isoformat(), "Fehler:", errors or "keine")


if __name__ == "__main__":
    main()
