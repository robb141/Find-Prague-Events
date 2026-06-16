#!/usr/bin/env python3
import argparse
import gzip
import html
import json
import os
import re
import ssl
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
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

TICKETMASTER_SOURCES = [
    ("Ticketmaster Prague", "https://www.ticketmaster.cz/search?keyword=Praha"),
    ("Ticketmaster Prague page 2", "https://www.ticketmaster.cz/search?keyword=Praha&page=1"),
    ("Ticketmaster Prague page 3", "https://www.ticketmaster.cz/search?keyword=Praha&page=2"),
    ("Ticketmaster Prague page 4", "https://www.ticketmaster.cz/search?keyword=Praha&page=3"),
]

TICKETPORTAL_SOURCES = [
    ("Ticketportal O2 arena", "https://www.ticketportal.cz/venue/O2-arena?idpartner=382KD"),
    ("Ticketportal Prague Congress Centre", "https://www.ticketportal.cz/Venue/1201393"),
]

KUDY_SOURCES = [
    ("Kudy z nudy Prague", "https://www.kudyznudy.cz/kalendar-akci/hlavni-mesto-praha"),
]

FORUM_KARLIN_SOURCES = [
    ("Forum Karlín", "https://www.forumkarlin.cz/en/events/"),
]

ALL_SOURCES = (
    SOURCES + GOOUT_SOURCES + O2_SOURCES + CITYBEE_SOURCES
    + TICKETMASTER_SOURCES + TICKETPORTAL_SOURCES + KUDY_SOURCES
    + FORUM_KARLIN_SOURCES
)
COLORS = ["#7246a8", "#33794c", "#007f7a", "#9e3f4f", "#c8941d", "#4b7b8a", "#d63f2e", "#344b77"]
DEFAULT_TIME = "12:00"
MIN_HEALTHY_EVENTS = 20
REQUIRED_EVENT_SOURCES = {"Prague.eu", "CityBee", "Ticketmaster"}
CZECH_MONTHS = {
    "ledna": 1,
    "února": 2,
    "března": 3,
    "dubna": 4,
    "května": 5,
    "června": 6,
    "července": 7,
    "srpna": 8,
    "září": 9,
    "října": 10,
    "listopadu": 11,
    "prosince": 12,
}
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


def fetch_bytes(url):
    request = Request(url, headers={"User-Agent": "FindPragueEvents/1.0 (+local personal event finder)"})
    try:
        with urlopen(request, timeout=40) as response:
            return response.read()
    except URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        context = ssl._create_unverified_context()
        with urlopen(request, timeout=40, context=context) as response:
            return response.read()


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
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


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
    if not existing.get("imageUrl") and incoming.get("imageUrl"):
        existing["imageUrl"] = incoming["imageUrl"]
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


def extract_image(markup, root, json_image=None):
    candidates = []
    if isinstance(json_image, str):
        candidates.append(json_image)
    elif isinstance(json_image, list):
        candidates.extend(item for item in json_image if isinstance(item, str))
    elif isinstance(json_image, dict):
        candidates.append(json_image.get("url"))

    for pattern in (
        r'<img[^>]+(?:data-src|src)="([^"]+)"',
        r'<source[^>]+srcset="([^"]+)"',
        r'background-image:\s*url\([\'"]?([^\'")]+)',
    ):
        match = re.search(pattern, markup, re.I)
        if match:
            candidates.append(match.group(1).split()[0])

    for candidate in candidates:
        if candidate and not candidate.startswith("data:"):
            return normalize_url(candidate, root)
    return None


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
        image_url = extract_image(tile, "https://prague.eu")

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
                "imageUrl": image_url,
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
        image_url = extract_image("", "https://goout.net", payload.get("image"))
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
            "imageUrl": image_url,
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
        image_url = extract_image(card, "https://www.o2arena.cz")

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
            "imageUrl": image_url,
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
        image_url = extract_image(card, "https://www.citybee.cz")

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
            "imageUrl": image_url,
        })

    return events


def extract_ticketmaster_events(markup, source_name, now, days):
    horizon = now + timedelta(days=days)
    events = []
    next_data = re.search(
        r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>',
        markup,
        re.S,
    )
    if not next_data:
        return events

    try:
        payload = json.loads(next_data.group(1))
        queries = payload["props"]["pageProps"]["initialReduxState"]["api"]["queries"]
        search_data = next(
            item["data"] for key, item in queries.items() if key.startswith("searchEvents(")
        )
    except (json.JSONDecodeError, KeyError, StopIteration, TypeError):
        return events

    for index, item in enumerate(search_data.get("events", [])):
        title = clean_text(item.get("title", ""))
        if not title or re.search(r"parkovací lístek|fast track|mobilní aplikace", title, re.I):
            continue
        date = parse_iso_or_http_date((item.get("dates") or {}).get("startDate"))
        if not in_window(date, now, horizon):
            continue
        venue = item.get("venue") or {}
        city = clean_text(venue.get("city", ""))
        if "praha" not in city.lower():
            continue

        artists = item.get("artists") or []
        image_url = next(
            (
                image
                for artist in artists
                for image in (artist.get("imageUrls") or {}).values()
                if image
            ),
            None,
        ) or venue.get("imageUrl")
        events.append({
            "id": event_id(title, date, source_name),
            "title": title,
            "category": clean_text((item.get("majorCategory") or {}).get("name", "Tickets")) or "Tickets",
            "district": city or "Prague",
            "venue": clean_text(venue.get("name", "Prague")),
            "date": date.isoformat(),
            "price": None,
            "popularity": 72 + ((index * 3) % 24),
            "english": True,
            "color": COLORS[index % len(COLORS)],
            "tags": ["Ticketmaster"],
            "description": "Event listed by Ticketmaster. Open the source page for tickets, prices, and current availability.",
            "source": "Ticketmaster",
            "sourceUrl": item.get("url"),
            "imageUrl": image_url,
        })
    return events


def ticketmaster_feed_image(item):
    images = [
        entry.get("image", {})
        for entry in item.get("images", [])
        if isinstance(entry, dict)
    ]
    landscape = [
        image for image in images
        if image.get("url") and image.get("ratio") == "16_9"
    ]
    if landscape:
        return max(landscape, key=lambda image: image.get("width") or 0)["url"]
    return item.get("eventImageUrl")


def fetch_ticketmaster_feed_events(api_key, now, days):
    metadata_url = "https://app.ticketmaster.com/discovery-feed/v2/events?" + urlencode({
        "apikey": api_key,
    })
    metadata = json.loads(fetch(metadata_url))
    feed = (metadata.get("countries") or {}).get("CZ", {}).get("JSON")
    if not feed or not feed.get("uri"):
        raise ValueError("Ticketmaster feed metadata did not include the CZ JSON feed.")

    payload = json.loads(gzip.decompress(fetch_bytes(feed["uri"])).decode("utf-8"))
    horizon = now + timedelta(days=days)
    events = []

    for index, item in enumerate(payload.get("events", [])):
        venue = item.get("venue") or {}
        city = clean_text(venue.get("venueCity", ""))
        if "praha" not in city.lower() and "prague" not in city.lower():
            continue
        if item.get("eventStatus") in {"cancelled", "canceled"}:
            continue

        date = parse_iso_or_http_date(item.get("eventStartDateTime"))
        if not date:
            local_date = item.get("eventStartLocalDate")
            local_time = item.get("eventStartLocalTime") or DEFAULT_TIME
            date = parse_iso_or_http_date(f"{local_date}T{local_time}") if local_date else None
        if not in_window(date, now, horizon):
            continue

        title = clean_text(item.get("eventName", ""))
        source_url = item.get("primaryEventUrl")
        if not title or not source_url:
            continue
        description = clean_text(
            item.get("eventInfo")
            or item.get("importantInformation")
            or item.get("pleaseNote")
            or ""
        )
        category = clean_text(
            item.get("classificationGenre")
            or item.get("classificationSegment")
            or "Tickets"
        )
        events.append({
            "id": item.get("eventId") or event_id(title, date, "Ticketmaster"),
            "title": title,
            "category": category,
            "district": city or "Prague",
            "venue": clean_text(venue.get("venueName", "Prague")),
            "date": date.isoformat(),
            "price": None,
            "popularity": 72 + ((index * 3) % 24),
            "english": True,
            "color": COLORS[index % len(COLORS)],
            "tags": ["Ticketmaster", category],
            "description": description[:240] or "Event listed by Ticketmaster. Open the source page for tickets, prices, and current availability.",
            "source": "Ticketmaster",
            "sourceUrl": source_url,
            "imageUrl": ticketmaster_feed_image(item),
        })

    return events, feed


def parse_czech_date(value):
    match = re.search(
        r"(\d{1,2})\.\s*([A-Za-zÁ-ž]+)\s+(\d{4})(?:.*?(\d{1,2}):(\d{2}))?",
        clean_text(value),
        re.I,
    )
    if not match:
        return None
    day, month_name, year, hour, minute = match.groups()
    month = CZECH_MONTHS.get(month_name.lower())
    if not month:
        return None
    return datetime(
        int(year),
        month,
        int(day),
        int(hour or DEFAULT_TIME.split(":")[0]),
        int(minute or DEFAULT_TIME.split(":")[1]),
    )


def extract_ticketportal_events(markup, source_name, now, days):
    horizon = now + timedelta(days=days)
    events = []
    cards = re.split(r'<div class="row[^"]*"[^>]+itemscope itemtype="http://schema.org/Event">', markup)[1:]

    for index, card in enumerate(cards):
        date_match = re.search(r'itemprop="startDate" content="([^"]+)"', card)
        title_match = re.search(r'<a href="([^"]+)" class="event" itemprop="name">(.*?)</a>', card, re.S)
        venue_match = re.search(r'class="building".*?<span itemprop=[\'"]name[\'"]>(.*?)</span>', card, re.S)
        city_match = re.search(r'itemprop="addressLocality">(.*?)</span>', card, re.S)
        if not title_match or not date_match:
            continue
        title = clean_text(title_match.group(2))
        if re.search(r"parkovací lístek|fast track|mobilní aplikace|permanentka", title, re.I):
            continue
        date = parse_iso_or_http_date(date_match.group(1))
        if not in_window(date, now, horizon):
            continue
        venue = clean_text(venue_match.group(1)) if venue_match else "Prague"
        city = clean_text(city_match.group(1)) if city_match else "Prague"
        if "praha" not in f"{venue} {city}".lower():
            continue
        source_url = normalize_url(title_match.group(1), "https://www.ticketportal.cz")
        events.append({
            "id": event_id(title, date, source_name),
            "title": title,
            "category": "Tickets",
            "district": city,
            "venue": venue,
            "date": date.isoformat(),
            "price": None,
            "popularity": 68 + ((index * 4) % 26),
            "english": False,
            "color": COLORS[index % len(COLORS)],
            "tags": ["Ticketportal"],
            "description": "Event listed by Ticketportal. Open the source page for tickets, prices, and current availability.",
            "source": "Ticketportal",
            "sourceUrl": source_url,
            "imageUrl": None,
        })
    return events


def extract_kudy_events(markup, source_name, now, days):
    horizon = now + timedelta(days=days)
    events = []
    cards = re.split(r'<div[^>]+itemscope itemtype="http://schema.org/Event"[^>]*>', markup)[1:]

    for index, card in enumerate(cards):
        card = card.split('<div[^>]+itemscope itemtype="http://schema.org/Event"', 1)[0]
        start_match = re.search(r'itemprop="startDate" content="([^"]+)"', card)
        end_match = re.search(r'itemprop="endDate" content="([^"]+)"', card)
        title_match = re.search(r'<span itemprop="name">(.*?)</span>', card, re.S)
        link_match = re.search(r'<a href="([^"]+)"[^>]+title="([^"]+)"', card)
        if not start_match or not title_match or not link_match:
            continue
        start = parse_iso_or_http_date(start_match.group(1))
        end = parse_iso_or_http_date(end_match.group(1)) if end_match else start
        if not start or not end or start > horizon or end < now.replace(hour=0, minute=0):
            continue
        date = start if start >= now else now.replace(hour=int(DEFAULT_TIME.split(":")[0]), minute=0)
        title = clean_text(title_match.group(1))
        location_match = re.search(r'itemprop="location".*?<span itemprop="name">(.*?)</span>', card, re.S)
        location = clean_text(location_match.group(1)) if location_match else "Prague"
        if "praha" not in location.lower():
            continue
        description_match = re.search(r'itemprop="description" content="([^"]*)"', card)
        image_match = re.search(r'<img[^>]+src="([^"]+)"[^>]+itemprop="image"', card)
        events.append({
            "id": event_id(title, date, source_name),
            "title": title,
            "category": "Things to do",
            "district": location,
            "venue": location,
            "date": date.isoformat(),
            "price": None,
            "popularity": 56 + ((index * 5) % 32),
            "english": False,
            "color": COLORS[index % len(COLORS)],
            "tags": ["Kudy z nudy"],
            "description": clean_text(description_match.group(1))[:240] if description_match else "Prague event listed by Kudy z nudy.",
            "source": source_name,
            "sourceUrl": normalize_url(link_match.group(1), "https://www.kudyznudy.cz"),
            "imageUrl": normalize_url(image_match.group(1), "https://www.kudyznudy.cz") if image_match else None,
        })
    return events


def extract_forum_karlin_events(markup, source_name, now, days):
    horizon = now + timedelta(days=days)
    events = []
    cards = re.split(r'<div class="event(?: [^"]*)?"><div class="event_inner">', markup)[1:]

    for index, card in enumerate(cards):
        title_match = re.search(r"<h3>\s*<a href=\"([^\"]+)\"[^>]*>(.*?)</a>", card, re.S)
        date_match = re.search(r'<div class="date">([^<]+)', card)
        if not title_match or not date_match or re.search(r"CANCELLED|MOVED", card, re.I):
            continue
        date = parse_date_piece(date_match.group(1), now.year)
        if not in_window(date, now, horizon):
            continue
        title = clean_text(title_match.group(2))
        image_url = extract_image(card, "https://www.forumkarlin.cz")
        description_match = re.search(r"</div><p>(.*?)</p>", card, re.S)
        description = clean_text(description_match.group(1)) if description_match else ""
        events.append({
            "id": event_id(title, date, source_name),
            "title": title,
            "category": "Concert",
            "district": "Karlín",
            "venue": "Forum Karlín",
            "date": date.isoformat(),
            "price": None,
            "popularity": 76 + ((index * 3) % 20),
            "english": True,
            "color": COLORS[index % len(COLORS)],
            "tags": ["Forum Karlín"],
            "description": description or "Concert at Forum Karlín. Open the event page for tickets and current details.",
            "source": source_name,
            "sourceUrl": title_match.group(1),
            "imageUrl": image_url,
        })
    return events


def collect(days):
    now = datetime.now().replace(second=0, microsecond=0)
    by_key = {}
    errors = []
    health = {}

    today = now.strftime("%Y-%m-%d")
    end = (now + timedelta(days=days)).strftime("%Y-%m-%d")
    kudy_pages = [
        (
            f"Kudy z nudy Prague page {page}",
            f"https://www.kudyznudy.cz/kalendar-akci/hlavni-mesto-praha?datum={today},{end}&stranka={page}",
        )
        for page in range(1, 6)
    ]

    source_groups = (
        ("Prague.eu", SOURCES, extract_tile_events),
        ("GoOut", GOOUT_SOURCES, extract_goout_events),
        ("O2 arena", O2_SOURCES, extract_o2_events),
        ("CityBee", CITYBEE_SOURCES, extract_citybee_events),
        ("Ticketportal", TICKETPORTAL_SOURCES, extract_ticketportal_events),
        ("Kudy z nudy", kudy_pages, extract_kudy_events),
        ("Forum Karlín", FORUM_KARLIN_SOURCES, extract_forum_karlin_events),
    )

    for group_name, sources, extractor in source_groups:
        group_count = 0
        successful_pages = 0
        for source_name, url in sources:
            try:
                markup = fetch(url)
                source_events = extractor(markup, source_name, now, days)
                successful_pages += 1
                group_count += len(source_events)
                for event in source_events:
                    key = dedupe_key(event)
                    by_key[key] = merge_event(by_key[key], event) if key in by_key else event
            except Exception as exc:
                errors.append(f"{source_name}: {exc}")
        health[group_name] = {
            "events": group_count,
            "pagesFetched": successful_pages,
            "pagesExpected": len(sources),
        }

    ticketmaster_key = os.environ.get("TICKETMASTER_API_KEY")
    ticketmaster_events = []
    ticketmaster_mode = "website fallback"
    if ticketmaster_key:
        try:
            ticketmaster_events, feed = fetch_ticketmaster_feed_events(
                ticketmaster_key, now, days
            )
            ticketmaster_mode = "official Discovery Feed"
            health["Ticketmaster"] = {
                "events": len(ticketmaster_events),
                "pagesFetched": 1,
                "pagesExpected": 1,
                "mode": ticketmaster_mode,
                "feedEvents": feed.get("num_events"),
                "feedUpdated": feed.get("last_updated"),
            }
        except Exception as exc:
            print(
                f"Ticketmaster feed failed ({exc}); using website fallback.",
                file=sys.stderr,
            )

    if not ticketmaster_events:
        successful_pages = 0
        for source_name, url in TICKETMASTER_SOURCES:
            try:
                ticketmaster_events.extend(
                    extract_ticketmaster_events(fetch(url), source_name, now, days)
                )
                successful_pages += 1
            except Exception as exc:
                errors.append(f"{source_name}: {exc}")
        health["Ticketmaster"] = {
            "events": len(ticketmaster_events),
            "pagesFetched": successful_pages,
            "pagesExpected": len(TICKETMASTER_SOURCES),
            "mode": ticketmaster_mode,
        }

    for event in ticketmaster_events:
        key = dedupe_key(event)
        by_key[key] = merge_event(by_key[key], event) if key in by_key else event

    events = sorted(by_key.values(), key=lambda event: event["date"])
    return events, errors, health


def validate_health(events, errors, health, days):
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    horizon = (today + timedelta(days=days)).replace(hour=23, minute=59, second=59)
    issues = list(errors)

    if len(events) < MIN_HEALTHY_EVENTS:
        issues.append(f"Only {len(events)} events were collected; expected at least {MIN_HEALTHY_EVENTS}.")

    for source, status in health.items():
        if status["pagesFetched"] == 0:
            issues.append(f"{source}: no source pages could be fetched.")
        if source in REQUIRED_EVENT_SOURCES and status["events"] == 0:
            issues.append(f"{source}: no upcoming events were parsed.")

    for event in events:
        date = parse_iso_or_http_date(event.get("date"))
        if not event.get("title") or not event.get("sourceUrl"):
            issues.append(f"Invalid required fields in event {event.get('id', '<unknown>')}.")
        elif not re.match(r"^https?://", event["sourceUrl"]):
            issues.append(f"Invalid source URL for {event['id']}: {event['sourceUrl']}")
        if not date or date < today or date > horizon:
            issues.append(f"Date outside collection window for {event.get('id', '<unknown>')}.")

    return issues


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
    parser.add_argument("--strict-health", action="store_true", help="Fail without replacing data when health checks fail.")
    parser.add_argument("--health-report", help="Optional path for a JSON health report.")
    args = parser.parse_args()

    if args.list_sources:
        for name, url in ALL_SOURCES:
            print(f"{name}: {url}")
        return 0

    events, errors, health = collect(args.days)
    issues = validate_health(events, errors, health, args.days)
    report = {
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "eventCount": len(events),
        "imageCount": sum(bool(event.get("imageUrl")) for event in events),
        "sources": health,
        "issues": issues,
    }
    if args.health_report:
        Path(args.health_report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2))
    if args.strict_health and issues:
        print("Health checks failed; existing event data was not replaced.", file=sys.stderr)
        return 1

    write_data_js(events, args.output)
    print(f"Wrote {len(events)} events to {args.output}")
    if issues:
        print("Health warnings:", file=sys.stderr)
        for issue in issues:
            print(f"- {issue}", file=sys.stderr)
    return 0 if events else 1


if __name__ == "__main__":
    raise SystemExit(main())
