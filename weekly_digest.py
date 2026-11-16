"""Build and send a weekly email with the most interesting Prague events.

The digest reads the event feed written by ``fetch_events.py`` (``data.js`` by
default), keeps the next seven days, drops recurring programme such as theatre,
exhibitions and weekly markets, and ranks what is left so that tech/AI/DevOps,
food and other one-off events come first.

Run ``python3 weekly_digest.py --dry-run`` to preview the email in the terminal.
Pass ``--send`` to deliver it through SMTP; see the README for the required
environment variables.
"""

import argparse
import html
import json
import os
import re
import smtplib
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from fetch_events import TECH_PATTERN, clean_text

APP_URL = "https://robb141.github.io/Find-Prague-Events/"
DEFAULT_DAYS = 7
DEFAULT_LIMIT = 12

# Categories that describe regular venue programme rather than one-off events.
EXCLUDED_CATEGORIES = {"Theatre", "Exhibitions", "GoOut"}

# Same title on at least this many different days inside the feed window means
# the event is a regular fixture (weekly markets, daily shows) rather than a pick.
RECURRING_DAY_THRESHOLD = 4

RECURRING_PATTERN = re.compile(
    r"farmers.? market|farmářsk|flea market|bleší trh|vegetable market"
    r"|guided tour|komentovaná prohlídka|permanent exhibition|stálá expozice"
    r"|museum|muzeum|gallery|galerie|every (monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"|každ[éý] (pondělí|úterý|středu|čtvrtek|pátek|sobotu|neděli)",
    re.I,
)

FOOD_PATTERN = re.compile(
    r"food|gastro|culinary|kulinář|restaurant|street ?food|beer|pivo|pivní|\bwine|víno|vinn"
    r"|whisky|whiskey|\bgin\b|\brum\b|coffee|káv|cocktail|koktejl|chocolate|čokolád|cheese|sýr"
    r"|burger|pizza|ramen|sushi|brunch|tasting|degustac|svatomartin|st\. martin",
    re.I,
)

DEVOPS_PATTERN = re.compile(
    r"devops|kubernetes|k8s|docker|terraform|ansible|\bsre\b|platform engineering"
    r"|cloud native|observability|ci/cd|gitops|\bai\b|umělá inteligence|artificial intelligence"
    r"|machine learning|\bllm|\bml\b|deep learning|data science|hackathon|meetup",
    re.I,
)

CATEGORY_WEIGHTS = {
    "IT & Tech": 100,
    "Food Events": 80,
    "Festivals": 60,
    "Fairs & Expos": 55,
    "Open Days": 55,
    "Markets": 35,
    "Things to do": 30,
    "Sports": 25,
    "Concerts": 10,
}

SECTIONS = [
    ("AI, IT & DevOps", lambda pick: pick["category"] == "IT & Tech" or pick["tech"]),
    ("Food & drink", lambda pick: pick["category"] == "Food Events" or pick["food"]),
    ("Other unique picks", lambda pick: True),
]

# Categories whose descriptions should never promote an event into the tech or food sections.
NON_TOPIC_CATEGORIES = {"Concerts", "Sports"}

BOILERPLATE_PATTERN = re.compile(r"open the (source|event) page", re.I)

CANCELLED_PATTERN = re.compile(
    r"\b(cancelled|canceled|postponed|sold out)\b|zrušen|odložen|přesunut|vyprodáno",
    re.I,
)

EVENTS_PATTERN = re.compile(r"window\.EVENTS\s*=\s*(\[.*?\]);\s*$", re.S | re.M)


def load_events(path):
    text = Path(path).read_text(encoding="utf-8")
    match = EVENTS_PATTERN.search(text)
    if not match:
        raise ValueError(f"{path} does not contain a window.EVENTS array")
    return json.loads(match.group(1))


def event_day(event):
    return datetime.fromisoformat(event["date"]).date()


def recurring_titles(events):
    days_by_title = defaultdict(set)
    for event in events:
        days_by_title[clean_text(event.get("title", "")).lower()].add(event_day(event))
    return {title for title, days in days_by_title.items() if len(days) >= RECURRING_DAY_THRESHOLD}


def is_cancelled(event):
    text = f"{event.get('title') or ''} {(event.get('description') or '')[:160]}"
    return bool(CANCELLED_PATTERN.search(text))


def is_recurring(event, recurring):
    title = clean_text(event.get("title", ""))
    if title.lower() in recurring:
        return True
    text = f"{title} {event.get('venue') or ''} {event.get('description') or ''}"
    return bool(RECURRING_PATTERN.search(text))


def useful_description(event):
    description = clean_text(event.get("description") or "")
    return "" if BOILERPLATE_PATTERN.search(description) else description


def score_event(event):
    """Return ``(score, is_tech, is_food)`` for a single event.

    Topic flags come from the title and tags only; descriptions are too noisy
    (a concert bio mentioning SoundCloud is not a tech event). Concerts and
    sports never count as tech or food picks.
    """
    category = event.get("category")
    title = f"{event.get('title') or ''} {' '.join(event.get('tags') or [])}"
    topical = category not in NON_TOPIC_CATEGORIES
    score = CATEGORY_WEIGHTS.get(category, 20)
    tech = topical and (category == "IT & Tech" or bool(TECH_PATTERN.search(title)))
    devops = topical and bool(DEVOPS_PATTERN.search(title))
    food = topical and (category == "Food Events" or bool(FOOD_PATTERN.search(title)))
    if tech:
        score += 30
    if devops:
        score += 20
    if food and category != "Food Events":
        score += 15
    score += (event.get("popularity") or 50) / 5
    if event.get("english"):
        score += 3
    if event.get("description"):
        score += 2
    return score, tech or devops, food


def select_picks(events, start, days=DEFAULT_DAYS, limit=DEFAULT_LIMIT):
    """Return the highest-ranked one-off events between ``start`` and ``start + days - 1``."""
    end = start + timedelta(days=days - 1)
    recurring = recurring_titles(events)
    grouped = {}
    for event in events:
        if event.get("category") in EXCLUDED_CATEGORIES:
            continue
        day = event_day(event)
        if not start <= day <= end:
            continue
        if is_recurring(event, recurring) or is_cancelled(event):
            continue
        score, tech, food = score_event(event)
        key = (clean_text(event.get("title", "")).lower(), clean_text(event.get("venue") or "").lower())
        pick = grouped.get(key)
        if pick is None:
            grouped[key] = {
                "title": clean_text(event.get("title", "")),
                "category": event.get("category"),
                "venue": event.get("venue") or "",
                "district": event.get("district") or "",
                "days": [day],
                "price": event.get("price"),
                "description": useful_description(event),
                "sourceUrl": event.get("sourceUrl") or APP_URL,
                "imageUrl": event.get("imageUrl"),
                "score": score,
                "tech": tech,
                "food": food,
            }
        else:
            pick["days"].append(day)
            pick["score"] = max(pick["score"], score)
            if not pick["description"]:
                pick["description"] = useful_description(event)
    picks = sorted(grouped.values(), key=lambda pick: (-pick["score"], min(pick["days"]), pick["title"]))
    for pick in picks:
        pick["days"] = sorted(set(pick["days"]))
    return picks[:limit]


def group_sections(picks):
    sections = []
    remaining = list(picks)
    for name, matcher in SECTIONS:
        matched = [pick for pick in remaining if matcher(pick)]
        remaining = [pick for pick in remaining if pick not in matched]
        if matched:
            sections.append((name, matched))
    return sections


def format_days(days):
    if len(days) == 1:
        return days[0].strftime("%a %-d %b")
    if days[-1] - days[0] == timedelta(days=len(days) - 1):
        return f"{days[0].strftime('%a %-d %b')} – {days[-1].strftime('%a %-d %b')}"
    return ", ".join(day.strftime("%a %-d %b") for day in days)


def format_price(price):
    if price is None:
        return ""
    if price == 0:
        return "Free"
    return f"from {price:g} CZK"


def digest_subject(start, days=DEFAULT_DAYS):
    end = start + timedelta(days=days - 1)
    return f"Prague events worth your week: {start.strftime('%-d %b')} – {end.strftime('%-d %b %Y')}"


def render_text(picks, start, days=DEFAULT_DAYS):
    lines = [digest_subject(start, days), ""]
    if not picks:
        lines.append("No one-off events matched this week. Browse everything at " + APP_URL)
        return "\n".join(lines) + "\n"
    for name, section in group_sections(picks):
        lines.append(name.upper())
        for pick in section:
            meta = " · ".join(part for part in [format_days(pick["days"]), pick["venue"], format_price(pick["price"])] if part)
            lines.append(f"- {pick['title']} ({pick['category']})")
            lines.append(f"  {meta}")
            if pick["description"]:
                lines.append(f"  {pick['description'][:200]}")
            lines.append(f"  {pick['sourceUrl']}")
        lines.append("")
    lines.append(f"All events: {APP_URL}")
    return "\n".join(lines) + "\n"


def render_html(picks, start, days=DEFAULT_DAYS):
    esc = html.escape
    parts = [
        "<!doctype html><html><body style=\"margin:0;padding:24px;background:#f4f4f7;"
        "font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#1f2430\">",
        "<div style=\"max-width:640px;margin:0 auto;background:#ffffff;border-radius:12px;padding:28px\">",
        f"<h1 style=\"font-size:22px;margin:0 0 4px\">{esc(digest_subject(start, days))}</h1>",
        "<p style=\"margin:0 0 20px;color:#5b6270\">One-off food, tech and other events in Prague this week. "
        "Regular theatre, exhibitions and weekly markets are left out.</p>",
    ]
    if not picks:
        parts.append(
            f"<p>No one-off events matched this week. <a href=\"{esc(APP_URL)}\">Browse everything</a>.</p>"
        )
    for name, section in group_sections(picks):
        parts.append(
            f"<h2 style=\"font-size:16px;margin:24px 0 8px;padding-bottom:4px;border-bottom:1px solid #e3e5ea\">{esc(name)}</h2>"
        )
        for pick in section:
            meta = " · ".join(part for part in [format_days(pick["days"]), pick["venue"], format_price(pick["price"])] if part)
            parts.append("<div style=\"padding:12px 0;border-bottom:1px solid #f0f1f4\">")
            parts.append(
                f"<div style=\"font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#7246a8\">{esc(pick['category'])}</div>"
            )
            parts.append(
                f"<a href=\"{esc(pick['sourceUrl'])}\" style=\"font-size:17px;font-weight:600;color:#1f2430;text-decoration:none\">{esc(pick['title'])}</a>"
            )
            parts.append(f"<div style=\"color:#5b6270;font-size:14px;margin-top:2px\">{esc(meta)}</div>")
            if pick["description"]:
                parts.append(f"<p style=\"margin:6px 0 0;font-size:14px\">{esc(pick['description'][:240])}</p>")
            parts.append("</div>")
    parts.append(
        f"<p style=\"margin-top:24px;font-size:13px;color:#5b6270\">All events: <a href=\"{esc(APP_URL)}\">{esc(APP_URL)}</a></p>"
    )
    parts.append("</div></body></html>")
    return "\n".join(parts)


def build_message(picks, start, days, sender, recipient):
    message = EmailMessage()
    message["Subject"] = digest_subject(start, days)
    message["From"] = sender
    message["To"] = recipient
    message.set_content(render_text(picks, start, days))
    message.add_alternative(render_html(picks, start, days), subtype="html")
    return message


def smtp_settings(environ=None):
    environ = os.environ if environ is None else environ
    recipient = environ.get("DIGEST_EMAIL_TO", "").strip()
    username = environ.get("SMTP_USERNAME", "").strip()
    password = environ.get("SMTP_PASSWORD", "")
    missing = [name for name, value in [("DIGEST_EMAIL_TO", recipient), ("SMTP_USERNAME", username), ("SMTP_PASSWORD", password)] if not value]
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))
    return {
        "host": environ.get("SMTP_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com",
        "port": int(environ.get("SMTP_PORT", "587") or 587),
        "username": username,
        "password": password,
        "sender": environ.get("DIGEST_EMAIL_FROM", "").strip() or username,
        "recipient": recipient,
    }


def send_message(message, settings):
    with smtplib.SMTP(settings["host"], settings["port"], timeout=60) as server:
        server.ehlo()
        server.starttls()
        server.login(settings["username"], settings["password"])
        server.send_message(message)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Email the best one-off Prague events for the coming week.")
    parser.add_argument("--data", default="data.js", help="Event feed written by fetch_events.py.")
    parser.add_argument("--start", help="First day of the digest window (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Length of the window in days.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Maximum number of picks.")
    parser.add_argument("--html-out", help="Also write the HTML email body to this path.")
    parser.add_argument("--send", action="store_true", help="Send the email through SMTP.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plain-text email and exit.")
    args = parser.parse_args(argv)

    start = date.fromisoformat(args.start) if args.start else date.today()
    events = load_events(args.data)
    picks = select_picks(events, start, args.days, args.limit)
    print(f"Selected {len(picks)} picks from {len(events)} events for {digest_subject(start, args.days)}")

    if args.html_out:
        Path(args.html_out).write_text(render_html(picks, start, args.days), encoding="utf-8")
    if args.dry_run or not args.send:
        print(render_text(picks, start, args.days))
        return 0

    try:
        settings = smtp_settings()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    message = build_message(picks, start, args.days, settings["sender"], settings["recipient"])
    send_message(message, settings)
    print(f"Sent digest with {len(picks)} picks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
