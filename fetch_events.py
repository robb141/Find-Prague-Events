#!/usr/bin/env python3
import argparse
import html
import json
import re
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


SOURCES = [
    ("Prague.eu events", "https://prague.eu/en/akce-kategorie/events/"),
    ("Prague.eu concerts", "https://prague.eu/en/akce-kategorie/concerts/"),
    ("Prague.eu exhibitions", "https://prague.eu/en/akce-kategorie/exhibitions/"),
    ("Prague.eu festivals", "https://prague.eu/en/akce-kategorie/festivals-celebrations/"),
    ("Prague.eu markets", "https://prague.eu/en/akce-kategorie/markets-gourmet/"),
    ("Prague.eu performing arts", "https://prague.eu/en/akce-kategorie/performing-arts/"),
    ("Prague.eu sports", "https://prague.eu/en/akce-kategorie/sports/"),
]

GOOUT_SOURCES = [
    ("GoOut Prague events", "https://goout.net/en/events/lez/"),
]

O2_SOURCES = [
    ("O2 arena events", "https://www.o2arena.cz/en/events/"),
]

CITYBEE_SOURCES = [
    ("CityBee events", "https://www.citybee.cz/akce/"),
    ("CityBee events page 2", "https://www.citybee.cz/vyhledavani/:/akce/prehled/strana/2/"),
    ("CityBee events page 3", "https://www.citybee.cz/vyhledavani/:/akce/prehled/strana/3/"),
    ("CityBee events page 4", "https://www.citybee.cz/vyhledavani/:/akce/prehled/strana/4/"),
    ("CityBee events page 5", "https://www.citybee.cz/vyhledavani/:/akce/prehled/strana/5/"),
]

ALL_SOURCES = SOURCES + GOOUT_SOURCES + O2_SOURCES + CITYBEE_SOURCES
COLORS = ["#7246a8", "#33794c", "#007f7a", "#9e3f4f", "#c8941d", "#4b7b8a", "#d63f2e", "#344b77"]
DEFAULT_TIME = "12:00"


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self):
        return " ".join(self.parts)


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def fetch(url):
    request = Request(url, headers={"User-Agent": "FindPragueEvents/1.0 (+local personal event finder)"})
    try:
        with urlopen(request, timeout=25) as response:
            return response.read().decode("utf-8", errors="replace")
    except URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        context = ssl._create_unverified_context()
        with urlopen(request, timeout=25, context=context) as response:
            return response.read().decode("utf-8", errors="replace")


def parse_date_piece(piece, year_hint):
    piece = piece.strip()
    match = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})?(?:,\s*(\d{1,2}):(\d{2}))?", piece)
    if not match:
        return None
    day, month, year, hour, minute = match.groups()
    year = int(year or year_hint)
    hour = int(hour) if hour else int(DEFAULT_TIME.split(":")[0])
    minute = int(minute) if minute else int(DEFAULT_TIME.split(":")[1])
    return datetime(year, int(month), int(day), hour, minute)


def parse_iso_or_http_date(value):
    if not value:
        return None
    value = str(value).strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        pass
    try:
        prefix = value.split(" (", 1)[0]
        parsed = parsedate_to_datetime(prefix)
        return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        return None


def in_window(date, now, horizon):
    return date and now <= date <= horizon


def slugify(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def event_id(title, date, source):
    return slugify(f"{source}-{title}-{date:%Y-%m-%d-%H%M}")


def dedupe_key(event):
    date = parse_iso_or_http_date(event["date"])
    day = date.strftime("%Y-%m-%d") if date else event["date"][:10]
    title = slugify(event["title"])
    venue = slugify(event.get("venue") or "")
    return f"{title}|{venue}|{day}"


def merge_event(existing, incoming):
    source = incoming.get("source")
    if source and source not in existing.get("source", ""):
        existing["source"] = f"{existing.get('source', 'Source')} + {source}"

    existing_tags = existing.get("tags", [])
    for tag in incoming.get("tags", []):
        if tag not in existing_tags:
            existing_tags.append(tag)
    existing["tags"] = existing_tags[:5]

    if not existing.get("price") and incoming.get("price"):
        existing["price"] = incoming["price"]
    if len(incoming.get("description", "")) > len(existing.get("description", "")):
        existing["description"] = incoming["description"]
    return existing


def normalize_url(url, root):
    if not url:
        return root
    url = html.unescape(url)
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return root.rstrip("/") + url
    return url


def parse_dates(tile, label, now, horizon):
    dates = []
    dates_json = re.search(r"data-datesjson='([^']+)'", tile)
    if dates_json:
        try:
            raw_dates = json.loads(html.unescape(dates_json.group(1)))
            for start, _end in raw_dates:
                parsed = datetime.strptime(start, "%d-%m-%Y %H:%M")
                if now <= parsed <= horizon:
                    dates.append(parsed)
        except (json.JSONDecodeError, ValueError):
            pass

    event_dates_attr = re.search(r"data-event_date='([^']*)'", tile)
    if event_dates_attr and event_dates_attr.group(1) not in ("", "all"):
        for date_value in event_dates_attr.group(1).split(","):
            try:
                date_only = datetime.strptime(date_value.strip(), "%d-%m-%Y")
                parsed = date_only.replace(hour=int(DEFAULT_TIME.split(":")[0]), minute=0)
                if now <= parsed <= horizon:
                    dates.append(parsed)
            except ValueError:
                continue

    if not dates:
        ranges = re.split(r"\s*[—-]\s*", label, maxsplit=1)
        candidates = ranges if len(ranges) > 1 else [label]
        for candidate in candidates:
            parsed = parse_date_piece(candidate, now.year)
            if parsed and now <= parsed <= horizon:
                dates.append(parsed)

    return sorted(set(dates))


def extract_tile_events(markup, source_name, now, days):
    horizon = now + timedelta(days=days)
    events = []
    tiles = re.split(r'<div class="tile-switching"', markup)[1:]

    for index, raw_tile in enumerate(tiles):
        tile = '<div class="tile-switching"' + raw_tile.split('<div class="tile-switching"', 1)[0]
        title_match = re.search(r"<h2>\s*<a href=\"([^\"]+)\">(.+?)</a>\s*</h2>", tile, re.S)
        if not title_match:
            continue

        source_url = html.unescape(title_match.group(1))
        title = clean_text(title_match.group(2))
        category = clean_text(re.search(r'tile-switching__beforeHeading">(.+?)</span>', tile, re.S).group(1)) if re.search(r'tile-switching__beforeHeading">(.+?)</span>', tile, re.S) else "Event"
        date_label = clean_text(re.search(r"<p>(.+?)</p>", tile, re.S).group(1)) if re.search(r"<p>(.+?)</p>", tile, re.S) else ""
        venue = clean_text(re.search(r'tile-switching__afterHeading">\s*(.+?)\s*</span>', tile, re.S).group(1)) if re.search(r'tile-switching__afterHeading">\s*(.+?)\s*</span>', tile, re.S) else "Prague"
        dates = parse_dates(tile, date_label, now, horizon)

        for date in dates[:3]:
            tags = [tag for tag in [category.title(), "Prague.eu"] if tag]
            events.append({
                "id": event_id(title, date, source_name),
                "title": title,
                "category": category.title(),
                "district": "Prague",
                "venue": venue,
                "date": date.isoformat(),
                "price": None,
                "popularity": 50 + ((index * 7) % 45),
                "english": True,
                "color": COLORS[index % len(COLORS)],
                "tags": tags,
                "description": f"{category.title()} listed by {source_name}. Open the source page for tickets, exact venue details, and current availability.",
                "source": source_name,
                "sourceUrl": source_url,
            })

    return events


def extract_goout_events(markup, source_name, now, days):
    horizon = now + timedelta(days=days)
    events = []
    scripts = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', markup, re.S)

    for index, script in enumerate(scripts):
        try:
            payload = json.loads(html.unescape(script))
        except json.JSONDecodeError:
            continue
        if payload.get("@type") != "Event":
            continue

        start = parse_iso_or_http_date(payload.get("startDate"))
        end = parse_iso_or_http_date(payload.get("endDate"))
        if not in_window(start, now, horizon) and not (start and end and start <= horizon and end >= now):
            continue

        date = start if start and start >= now else now.replace(hour=int(DEFAULT_TIME.split(":")[0]), minute=0)
        location = payload.get("location") or {}
        offer = (payload.get("offers") or [{}])[0]
        price = None
        try:
            price = int(float(offer.get("price"))) if offer.get("price") not in (None, "") else None
        except (TypeError, ValueError):
            price = None

        title = clean_text(payload.get("name", "GoOut event"))
        description = clean_text(payload.get("description", ""))[:240] or "Event listed by GoOut. Open the source page for tickets, venue details, and current availability."
        events.append({
            "id": event_id(title, date, source_name),
            "title": title,
            "category": "GoOut",
            "district": "Prague",
            "venue": clean_text(location.get("name", "Prague")),
            "date": date.isoformat(),
            "price": price,
            "popularity": 58 + ((index * 5) % 38),
            "english": True,
            "color": COLORS[index % len(COLORS)],
            "tags": ["GoOut"],
            "description": description,
            "source": source_name,
            "sourceUrl": normalize_url(payload.get("url"), "https://goout.net"),
        })

    return events


def extract_o2_events(markup, source_name, now, days):
    horizon = now + timedelta(days=days)
    events = []
    cards = re.split(r'<div class="event_preview toLeft">', markup)[1:]

    for index, raw_card in enumerate(cards):
        card = raw_card.split('<div class="event_preview toLeft">', 1)[0]
        title_match = re.search(r'<h3><a href="([^"]+)">(.+?)</a>', card, re.S)
        date_match = re.search(r'<p class="time">([^<]+)</p>', card)
        if not title_match or not date_match:
            continue
        try:
            date = datetime.strptime(clean_text(date_match.group(1)), "%d.%m.%Y %H:%M")
        except ValueError:
            continue
        if not in_window(date, now, horizon):
            continue

        title = clean_text(title_match.group(2))
        description = clean_text(re.search(r'<p class="perex">(.+?)</p>', card, re.S).group(1)) if re.search(r'<p class="perex">(.+?)</p>', card, re.S) else "Event listed by O2 arena."
        source_url = normalize_url(title_match.group(1), "https://www.o2arena.cz")
        venue = "O2 universum" if "o2universum.cz" in source_url else "O2 arena"

        events.append({
            "id": event_id(title, date, source_name),
            "title": title,
            "category": "Arena",
            "district": "Libeň",
            "venue": venue,
            "date": date.isoformat(),
            "price": None,
            "popularity": 75 + ((index * 3) % 20),
            "english": True,
            "color": COLORS[index % len(COLORS)],
            "tags": ["O2", "Arena"],
            "description": description,
            "source": source_name,
            "sourceUrl": source_url,
        })

    return events


def extract_citybee_events(markup, source_name, now, days):
    horizon = now + timedelta(days=days)
    events = []
    cards = re.split(r'<div class="vevent card"', markup)[1:]

    for index, raw_card in enumerate(cards):
        card = '<div class="vevent card"' + raw_card.split('<div class="vevent card"', 1)[0]
        title_match = re.search(r'<a class="url" href="([^"]+)">.*?<span class="summary display-none">(.+?)</span>', card, re.S)
        date_match = re.search(r'<span class="dtstart display-none">([^<]+)</span>', card)
        if not title_match or not date_match:
            continue
        date = parse_iso_or_http_date(date_match.group(1))
        if date and "T" not in date_match.group(1):
            date = date.replace(hour=int(DEFAULT_TIME.split(":")[0]), minute=0)
        if not in_window(date, now, horizon):
            continue

        title = clean_text(title_match.group(2))
        venue = clean_text(re.search(r'<span class="location display-none">(.+?)</span>', card, re.S).group(1)) if re.search(r'<span class="location display-none">(.+?)</span>', card, re.S) else "Prague"
        description = clean_text(re.search(r'<span class="description display-none">(.+?)</span>', card, re.S).group(1)) if re.search(r'<span class="description display-none">(.+?)</span>', card, re.S) else "Event listed by CityBee."
        source_url = normalize_url(title_match.group(1), "https://www.citybee.cz")

        events.append({
            "id": event_id(title, date, source_name),
            "title": title,
            "category": "CityBee",
            "district": "Prague",
            "venue": venue,
            "date": date.isoformat(),
            "price": 0 if re.search(r"zdarma|free", description, re.I) else None,
            "popularity": 54 + ((index * 6) % 34),
            "english": False,
            "color": COLORS[index % len(COLORS)],
            "tags": ["CityBee"],
            "description": description[:240],
            "source": source_name.replace(" page 2", "").replace(" page 3", "").replace(" page 4", "").replace(" page 5", ""),
            "sourceUrl": source_url,
        })

    return events


def collect(days):
    now = datetime.now().replace(second=0, microsecond=0)
    by_key = {}
    errors = []

    for source_name, url in SOURCES:
        try:
            markup = fetch(url)
            for event in extract_tile_events(markup, source_name, now, days):
                key = dedupe_key(event)
                by_key[key] = merge_event(by_key[key], event) if key in by_key else event
        except URLError as exc:
            errors.append(f"{source_name}: {exc}")

    for source_name, url in GOOUT_SOURCES:
        try:
            markup = fetch(url)
            for event in extract_goout_events(markup, source_name, now, days):
                key = dedupe_key(event)
                by_key[key] = merge_event(by_key[key], event) if key in by_key else event
        except URLError as exc:
            errors.append(f"{source_name}: {exc}")

    for source_name, url in O2_SOURCES:
        try:
            markup = fetch(url)
            for event in extract_o2_events(markup, source_name, now, days):
                key = dedupe_key(event)
                by_key[key] = merge_event(by_key[key], event) if key in by_key else event
        except URLError as exc:
            errors.append(f"{source_name}: {exc}")

    for source_name, url in CITYBEE_SOURCES:
        try:
            markup = fetch(url)
            for event in extract_citybee_events(markup, source_name, now, days):
                key = dedupe_key(event)
                by_key[key] = merge_event(by_key[key], event) if key in by_key else event
        except URLError as exc:
            errors.append(f"{source_name}: {exc}")

    events = sorted(by_key.values(), key=lambda event: event["date"])
    return events, errors


def write_data_js(events, output_path):
    output = "window.EVENTS = "
    output += json.dumps(events, ensure_ascii=False, indent=2)
    output += ";\n"
    Path(output_path).write_text(output, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Fetch Prague events for FindPragueEvents.")
    parser.add_argument("--days", type=int, default=30, help="Number of days ahead to include.")
    parser.add_argument("--output", default="data.js", help="Output JS file consumed by index.html.")
    parser.add_argument("--list-sources", action="store_true", help="Print source URLs and exit.")
    args = parser.parse_args()

    if args.list_sources:
        for name, url in ALL_SOURCES:
            print(f"{name}: {url}")
        return 0

    events, errors = collect(args.days)
    write_data_js(events, args.output)
    print(f"Wrote {len(events)} events to {args.output}")
    if errors:
        print("Some sources failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    return 0 if events else 1


if __name__ == "__main__":
    raise SystemExit(main())
