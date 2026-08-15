import gzip
import json
import unittest
from datetime import datetime
from unittest.mock import patch

import fetch_events


class DateTests(unittest.TestCase):
    def test_parses_czech_date_with_time(self):
        parsed = fetch_events.parse_czech_date("14. června 2026, 19:30")

        self.assertEqual(parsed, datetime(2026, 6, 14, 19, 30))

    def test_window_includes_boundaries(self):
        start = datetime(2026, 6, 10, 9, 0)
        end = datetime(2026, 7, 10, 9, 0)

        self.assertTrue(fetch_events.in_window(start, start, end))
        self.assertTrue(fetch_events.in_window(end, start, end))
        self.assertFalse(fetch_events.in_window(datetime(2026, 6, 10, 8, 59), start, end))


class DuplicateTests(unittest.TestCase):
    def test_same_title_venue_and_day_share_key(self):
        first = {
            "title": "The Bodyguard",
            "venue": "Musical Theatre Karlín",
            "date": "2026-06-10T14:00:00",
        }
        second = {
            "title": "The Bodyguard!",
            "venue": "Musical Theatre Karlin",
            "date": "2026-06-10T19:00:00",
        }

        self.assertEqual(
            fetch_events.dedupe_key(first),
            fetch_events.dedupe_key(second),
        )

    def test_merge_preserves_sources_and_enriches_event(self):
        existing = {
            "source": "Prague.eu",
            "tags": ["Theatre"],
            "description": "Short",
            "price": None,
            "imageUrl": None,
        }
        incoming = {
            "source": "Ticketmaster",
            "tags": ["Tickets"],
            "description": "A more useful event description.",
            "price": 490,
            "imageUrl": "https://example.com/event.jpg",
        }

        merged = fetch_events.merge_event(existing, incoming)

        self.assertEqual(merged["source"], "Prague.eu + Ticketmaster")
        self.assertEqual(merged["tags"], ["Theatre", "Tickets"])
        self.assertEqual(merged["price"], 490)
        self.assertEqual(merged["imageUrl"], incoming["imageUrl"])
        self.assertEqual(merged["description"], incoming["description"])


class TicketmasterFeedTests(unittest.TestCase):
    def test_feed_keeps_only_upcoming_prague_events(self):
        metadata = {
            "countries": {
                "CZ": {
                    "JSON": {
                        "uri": "https://feed.example/events.json.gz",
                        "num_events": 3,
                        "last_updated": "2026-06-10T08:00:00Z",
                    }
                }
            }
        }
        feed = {
            "events": [
                {
                    "eventId": "prague-event",
                    "eventName": "Prague Test Concert",
                    "primaryEventUrl": "https://www.ticketmaster.cz/event/test/1",
                    "eventStatus": "onsale",
                    "eventStartLocalDate": "2026-06-15",
                    "eventStartLocalTime": "19:30",
                    "eventImageUrl": "https://example.com/fallback.jpg",
                    "classificationGenre": "Rock",
                    "venue": {
                        "venueName": "Rock Café",
                        "venueCity": "Praha 1",
                    },
                    "images": [
                        {
                            "image": {
                                "ratio": "16_9",
                                "url": "https://example.com/large.jpg",
                                "width": 1136,
                            }
                        }
                    ],
                },
                {
                    "eventId": "brno-event",
                    "eventName": "Brno Event",
                    "primaryEventUrl": "https://www.ticketmaster.cz/event/test/2",
                    "eventStatus": "onsale",
                    "eventStartLocalDate": "2026-06-15",
                    "eventStartLocalTime": "20:00",
                    "venue": {"venueName": "Club", "venueCity": "Brno"},
                },
                {
                    "eventId": "cancelled-event",
                    "eventName": "Cancelled Prague Event",
                    "primaryEventUrl": "https://www.ticketmaster.cz/event/test/3",
                    "eventStatus": "cancelled",
                    "eventStartLocalDate": "2026-06-16",
                    "eventStartLocalTime": "20:00",
                    "venue": {"venueName": "Club", "venueCity": "Praha"},
                },
            ]
        }

        with (
            patch.object(fetch_events, "fetch", return_value=json.dumps(metadata)),
            patch.object(
                fetch_events,
                "fetch_bytes",
                return_value=gzip.compress(json.dumps(feed).encode()),
            ),
        ):
            events, feed_metadata = fetch_events.fetch_ticketmaster_feed_events(
                "test-key",
                datetime(2026, 6, 10, 9, 0),
                30,
            )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["id"], "prague-event")
        self.assertEqual(events[0]["venue"], "Rock Café")
        self.assertEqual(events[0]["imageUrl"], "https://example.com/large.jpg")
        self.assertEqual(feed_metadata["num_events"], 3)

    def test_missing_czech_feed_is_rejected(self):
        with patch.object(fetch_events, "fetch", return_value='{"countries": {}}'):
            with self.assertRaisesRegex(ValueError, "CZ JSON feed"):
                fetch_events.fetch_ticketmaster_feed_events(
                    "test-key",
                    datetime(2026, 6, 10, 9, 0),
                    30,
                )


class CategoryTests(unittest.TestCase):
    def test_maps_source_categories_to_canonical_set(self):
        cases = {
            "Concert": "Concerts",
            "Concerts": "Concerts",
            "Rock": "Concerts",
            "Live Music & Gigs": "Concerts",
            "Classical Music": "Concerts",
            "Opera": "Concerts",
            "Hip-Hop/Rap": "Concerts",
            "Dance/Electronic": "Concerts",
            "Arena": "Concerts",
            "Kultura": "Concerts",
            "Theatre": "Theatre",
            "Drama": "Theatre",
            "Musical Theatre": "Theatre",
            "Black Light & Shadow Theatre": "Theatre",
            "New Circus & Physical Theatre": "Theatre",
            "Contemporary Dance": "Theatre",
            "Ballet": "Theatre",
            "Contemporary Art": "Exhibitions",
            "Photography": "Exhibitions",
            "Museum Exhibitions": "Exhibitions",
            "Výstava": "Exhibitions",
            "Food Events & Festivals": "Food Events",
            "Festivals": "Festivals",
            "Festivities & Traditions": "Festivals",
            "Markets": "Markets",
            "Sports": "Sports",
            "Soccer": "Sports",
            "Football": "Sports",
            "Open Days": "Open Days",
            "Veletrh": "Fairs & Expos",
            "GoOut": "GoOut",
            "CityBee": "Things to do",
            "Things to do": "Things to do",
            "Miscellaneous": "Things to do",
            "": "Things to do",
        }

        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(fetch_events.normalize_category(raw), expected)

    def test_tech_events_are_detected_from_titles(self):
        cases = {
            "Google Cloud Summit Prague": "IT & Tech",
            "AI Days 2026": "IT & Tech",
            "Prague DevOps Meetup": "IT & Tech",
            "Hackathon Praha": "IT & Tech",
            "IT konference pro vývojáře": "IT & Tech",
            "Kubernetes Community Day": "IT & Tech",
        }

        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(
                    fetch_events.normalize_category("Arena", title), expected
                )

    def test_non_tech_titles_keep_their_category(self):
        self.assertEqual(
            fetch_events.normalize_category("Rock", "Depeche Mode: Memento Mori Tour"),
            "Concerts",
        )
        self.assertEqual(
            fetch_events.normalize_category("Drama", "Hamlet"),
            "Theatre",
        )

    def test_canonical_category_list_is_complete_and_sorted(self):
        categories = fetch_events.canonical_categories()

        self.assertEqual(categories, sorted(categories))
        for name in ("IT & Tech", "Concerts", "Theatre", "Things to do", "Open Days"):
            self.assertIn(name, categories)

    def test_collected_events_use_canonical_categories(self):
        by_key = {}
        fetch_events.add_event(by_key, {
            "title": "Test Gig",
            "venue": "Club",
            "date": "2026-06-12T20:00:00",
            "category": "Indie",
            "tags": [],
        })

        self.assertEqual(list(by_key.values())[0]["category"], "Concerts")


class GongExtractorTests(unittest.TestCase):
    def test_parses_program_rows_within_window(self):
        markup = """
        <div class="tribe-common-g-row tribe-events-calendar-list__event-row" >
          <time class="tribe-events-calendar-list__event-date-tag-datetime" datetime="2026-06-20"></time>
          <img class="tribe-events-calendar-list__event-featured-image" src="https://www.divadlogong.cz/img/show.jpg">
          <h3><a href="https://www.divadlogong.cz/predstaveni/test-show/" class="tribe-events-calendar-list__event-title-link tribe-common-anchor-thin">Test Show</a></h3>
          <span class="tribe-event-date-start">20. června: 19:30</span>
          <div class="tribe-events-calendar-list__event-description tribe-common-b2"> <p>A short description.</p> </div>
        </div>
        <div class="tribe-common-g-row tribe-events-calendar-list__event-row" >
          <time class="tribe-events-calendar-list__event-date-tag-datetime" datetime="2026-09-01"></time>
          <h3><a href="https://www.divadlogong.cz/predstaveni/late-show/" class="tribe-events-calendar-list__event-title-link">Late Show</a></h3>
          <span class="tribe-event-date-start">1. září: 19:00</span>
        </div>
        """

        events = fetch_events.extract_gong_events(
            markup, "Divadlo Gong", datetime(2026, 6, 10, 9, 0), 30
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["title"], "Test Show")
        self.assertEqual(events[0]["date"], "2026-06-20T19:30:00")
        self.assertEqual(events[0]["venue"], "Divadlo Gong")
        self.assertEqual(events[0]["district"], "Vysočany")
        self.assertEqual(events[0]["description"], "A short description.")
        self.assertEqual(events[0]["imageUrl"], "https://www.divadlogong.cz/img/show.jpg")


class PvaExtractorTests(unittest.TestCase):
    def test_keeps_running_and_upcoming_fairs_only(self):
        markup = """
        <div class="dk-event__card--small">
          <div class="dk-event__card--small__image" style="background: url(http://pvaexpo.cz/cdn/image/1.jpg)"></div>
          <span class="dk-event__card__date dk-style--body-m-med">1. 6. — 23. 8. 2026</span>
          <a href="http://pvaexpo.cz/cs/akce/475" class="dk-style--body-xl-high dk-event__card__link">Running Expo</a>
          <span class="dk-style--body-m-low dk-event__card__category">Veletrh</span>
        </div>
        <div class="dk-event__card--small">
          <span class="dk-event__card__date dk-style--body-m-med">26. 6. 2026</span>
          <a href="http://pvaexpo.cz/cs/akce/480" class="dk-style--body-xl-high dk-event__card__link">Single Day Concert</a>
          <span class="dk-style--body-m-low dk-event__card__category">Kultura</span>
        </div>
        <div class="dk-event__card--small">
          <span class="dk-event__card__date dk-style--body-m-med">21. 4. — 23. 4. 2027</span>
          <a href="http://pvaexpo.cz/cs/akce/353" class="dk-style--body-xl-high dk-event__card__link">Next Year Fair</a>
          <span class="dk-style--body-m-low dk-event__card__category">Veletrh</span>
        </div>
        """

        events = fetch_events.extract_pva_events(
            markup, "PVA EXPO Letňany", datetime(2026, 6, 10, 9, 0), 30
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["title"], "Running Expo")
        self.assertEqual(events[0]["date"], "2026-06-10T12:00:00")
        self.assertEqual(events[0]["category"], "Veletrh")
        self.assertEqual(events[0]["imageUrl"], "http://pvaexpo.cz/cdn/image/1.jpg")
        self.assertEqual(events[1]["title"], "Single Day Concert")
        self.assertEqual(events[1]["date"], "2026-06-26T12:00:00")
        self.assertEqual(events[1]["district"], "Letňany")


class EventbriteExtractorTests(unittest.TestCase):
    def test_keeps_only_prague_events_in_window(self):
        payload = {
            "@type": "ItemList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "item": {
                        "@type": "Event",
                        "name": "Prague Tech Mixer",
                        "url": "https://www.eventbrite.com/e/prague-tech-mixer-1",
                        "startDate": "2026-06-17",
                        "description": "Networking with tech workers.",
                        "image": "https://img.evbuc.com/mixer.jpg",
                        "location": {
                            "name": "Groove Bar",
                            "address": {"addressLocality": "Praha 1", "addressRegion": "Hlavní město Praha"},
                        },
                    },
                },
                {
                    "@type": "ListItem",
                    "item": {
                        "@type": "Event",
                        "name": "Berlin Robotics Workshop",
                        "url": "https://www.eventbrite.de/e/berlin-robotics-2",
                        "startDate": "2026-06-18",
                        "location": {"address": {"addressLocality": "Berlin", "addressRegion": "Berlin"}},
                    },
                },
                {
                    "@type": "ListItem",
                    "item": {
                        "@type": "Event",
                        "name": "Prague Autumn Conference",
                        "url": "https://www.eventbrite.com/e/prague-autumn-3",
                        "startDate": "2026-10-08",
                        "location": {"address": {"addressLocality": "Praha 4", "addressRegion": "Hlavní město Praha"}},
                    },
                },
                {
                    "@type": "ListItem",
                    "item": {
                        "@type": "Event",
                        "name": "Plant Biology World Congress PWC-2026",
                        "url": "https://www.eventbrite.com/e/plant-biology-4",
                        "startDate": "2026-06-18",
                        "location": {"address": {"addressLocality": "Praha 4", "addressRegion": "Hlavní město Praha"}},
                    },
                },
            ],
        }
        markup = f'<script type="application/ld+json">{json.dumps(payload)}</script>'

        events = fetch_events.extract_eventbrite_events(
            markup, "Eventbrite Prague tech", datetime(2026, 6, 10, 9, 0), 30
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["title"], "Prague Tech Mixer")
        self.assertEqual(events[0]["category"], "IT & Tech")
        self.assertEqual(events[0]["venue"], "Groove Bar")
        self.assertEqual(events[0]["district"], "Praha 1")
        self.assertEqual(events[0]["date"], "2026-06-17T12:00:00")
        self.assertEqual(events[1]["title"], "Plant Biology World Congress PWC-2026")
        self.assertEqual(events[1]["category"], "Things to do")


class ConfsTechTests(unittest.TestCase):
    def test_collects_prague_conferences_and_tolerates_missing_files(self):
        listing = json.dumps([
            {
                "name": "PragueConf",
                "url": "https://pragueconf.example",
                "startDate": "2026-06-20",
                "endDate": "2026-06-21",
                "city": "Prague",
                "country": "Czech Republic",
            },
            {
                "name": "BrnoConf",
                "url": "https://brnoconf.example",
                "startDate": "2026-06-20",
                "city": "Brno",
                "country": "Czech Republic",
            },
        ])

        def fake_fetch(url):
            if "/2026/devops.json" in url:
                return listing
            raise ValueError("missing file")

        with patch.object(fetch_events, "fetch", side_effect=fake_fetch):
            events, fetched, expected = fetch_events.fetch_confs_tech_events(
                datetime(2026, 6, 10, 9, 0), 30
            )

        self.assertEqual(fetched, 1)
        self.assertEqual(expected, len(fetch_events.CONFS_TECH_TOPICS))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["title"], "PragueConf")
        self.assertEqual(events[0]["category"], "IT & Tech")
        self.assertEqual(events[0]["date"], "2026-06-20T12:00:00")


def citybee_card(event_id, title, date_str, venue="Prague"):
    return f"""
        <div class="vevent card" >
            <div class="cbthumb">
                <a href="https://www.citybee.cz/kultura/:/akce/{event_id}/">
                    <img src="https://c.citybee.cz/images/{event_id}.jpg" alt="" class="photo" />
                </a>
            </div>
            <h3><a class="url" href="https://www.citybee.cz/kultura/:/akce/{event_id}/"><span class="summary display-none">{title}</span>{title}</a></h3>
            <p class="meta">
                <span class="dtstart display-none">{date_str}</span>
                <span class="location display-none">{venue}</span>
            </p>
            <p><span class="description display-none">Event listed by CityBee.</span>Event listed by CityBee.</p>
        </div>
    """


def citybee_pager(current, last, links=None):
    if links is None:
        links = list(range(1, last + 1))
    numbered = "".join(
        f'<li class="active">{n}</li>' if n == current
        else f'<li><a href="https://www.citybee.cz/vyhledavani/:/akce/prehled/strana/{n}/">{n}</a></li>'
        for n in links
    )
    last_href = "" if current >= last else f"https://www.citybee.cz/vyhledavani/:/akce/prehled/strana/{last}/"
    return f"""
        <ul class="pager">
        <li class="first"><a href="">&laquo;</a></li>
        <li class="prev"><a href="">&lt;</a></li>
        {numbered}
        <li class="next"><a href="">&gt;</a></li>
        <li class="last"><a href="{last_href}">&raquo;</a></li>
        </ul>
    """


def citybee_page_markup(cards_html, current, last, links=None):
    return f"<html><body><div class='card-list'>{cards_html}</div>{citybee_pager(current, last, links)}</body></html>"


class CityBeeExtractorTests(unittest.TestCase):
    def test_parses_card_fields_within_window(self):
        markup = citybee_card("1", "Romský Bašavel 2026", "2026-06-20T15:00", "Praha 4")
        events = fetch_events.extract_citybee_events(
            markup, "CityBee events", datetime(2026, 6, 10, 9, 0), 30
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["title"], "Romský Bašavel 2026")
        self.assertEqual(events[0]["venue"], "Praha 4")
        self.assertEqual(events[0]["source"], "CityBee events")

    def test_source_label_strips_page_suffix(self):
        markup = citybee_card("1", "Some Event", "2026-06-20T15:00")
        events = fetch_events.extract_citybee_events(
            markup, "CityBee events page 7", datetime(2026, 6, 10, 9, 0), 30
        )

        self.assertEqual(events[0]["source"], "CityBee events")


class CityBeePaginationTests(unittest.TestCase):
    def test_detects_last_page_from_pager_bar(self):
        markup = citybee_page_markup("", current=1, last=4)

        self.assertEqual(fetch_events.detect_citybee_last_page(markup), 4)

    def test_detects_last_page_when_only_one_page_exists(self):
        markup = "<html><body><div class='card-list'></div><ul class=\"pager\"></ul></body></html>"

        self.assertEqual(fetch_events.detect_citybee_last_page(markup), 1)

    def test_returns_none_when_pager_missing(self):
        markup = "<html><body><div class='card-list'></div></body></html>"

        self.assertIsNone(fetch_events.detect_citybee_last_page(markup))

    def test_fetches_all_discovered_pages_and_stops_at_last_page(self):
        pages = {
            1: citybee_page_markup(citybee_card("1", "Event One", "2026-06-20T15:00"), 1, 3),
            2: citybee_page_markup(citybee_card("2", "Event Two", "2026-06-21T15:00"), 2, 3),
            3: citybee_page_markup(citybee_card("3", "Event Three", "2026-06-22T15:00"), 3, 3),
        }

        def fake_fetch(url):
            for page, markup in pages.items():
                if fetch_events.citybee_page_url(page) == url:
                    return markup
            raise AssertionError(f"unexpected page fetched: {url}")

        with patch.object(fetch_events, "fetch", side_effect=fake_fetch):
            events, pages_fetched, pages_expected, warnings = fetch_events.fetch_citybee_events(
                datetime(2026, 6, 10, 9, 0), 30
            )

        self.assertEqual(pages_fetched, 3)
        self.assertEqual(pages_expected, 3)
        self.assertEqual(warnings, [])
        self.assertEqual(
            {event["title"] for event in events},
            {"Event One", "Event Two", "Event Three"},
        )

    def test_stops_early_when_a_later_page_is_empty(self):
        # Pager claims 5 pages, but the site clamps out-of-range requests to
        # an empty listing starting at page 3; the empty-page safety net
        # should stop the crawl instead of fetching pages 4 and 5.
        pages = {
            1: citybee_page_markup(citybee_card("1", "Event One", "2026-06-20T15:00"), 1, 5),
            2: citybee_page_markup(citybee_card("2", "Event Two", "2026-06-21T15:00"), 2, 5),
            3: citybee_page_markup("", 3, 5),
        }
        fetched_urls = []

        def fake_fetch(url):
            fetched_urls.append(url)
            for page, markup in pages.items():
                if fetch_events.citybee_page_url(page) == url:
                    return markup
            raise AssertionError(f"unexpected page fetched: {url}")

        with patch.object(fetch_events, "fetch", side_effect=fake_fetch):
            events, pages_fetched, pages_expected, warnings = fetch_events.fetch_citybee_events(
                datetime(2026, 6, 10, 9, 0), 30
            )

        self.assertEqual(pages_fetched, 3)
        self.assertEqual(pages_expected, 5)
        self.assertEqual(len(events), 2)
        self.assertEqual(
            fetched_urls,
            [fetch_events.citybee_page_url(p) for p in (1, 2, 3)],
        )

    def test_falls_back_to_fixed_page_count_when_pager_cannot_be_parsed(self):
        # Site markup changed enough that the pager bar isn't found; we
        # should still keep walking pages up to the fallback count instead
        # of only fetching page 1, using the empty-page check to stop.
        pages = {
            page: f"<html><body><div class='card-list'>{citybee_card(str(page), f'Event {page}', '2026-06-20T15:00')}</div></body></html>"
            for page in range(1, fetch_events.CITYBEE_FALLBACK_PAGES + 1)
        }

        def fake_fetch(url):
            for page, markup in pages.items():
                if fetch_events.citybee_page_url(page) == url:
                    return markup
            raise AssertionError(f"unexpected page fetched: {url}")

        with patch.object(fetch_events, "fetch", side_effect=fake_fetch):
            events, pages_fetched, pages_expected, warnings = fetch_events.fetch_citybee_events(
                datetime(2026, 6, 10, 9, 0), 30
            )

        self.assertEqual(pages_fetched, fetch_events.CITYBEE_FALLBACK_PAGES)
        self.assertEqual(pages_expected, fetch_events.CITYBEE_FALLBACK_PAGES)
        self.assertEqual(len(events), fetch_events.CITYBEE_FALLBACK_PAGES)

    def test_records_warning_and_stops_when_first_page_fetch_fails(self):
        def fake_fetch(url):
            raise ValueError("boom")

        with patch.object(fetch_events, "fetch", side_effect=fake_fetch):
            events, pages_fetched, pages_expected, warnings = fetch_events.fetch_citybee_events(
                datetime(2026, 6, 10, 9, 0), 30
            )

        self.assertEqual(events, [])
        self.assertEqual(pages_fetched, 0)
        self.assertEqual(len(warnings), 1)
        self.assertIn("boom", warnings[0])


class HealthTests(unittest.TestCase):
    def test_health_reports_empty_source_and_bad_url(self):
        events = [
            {
                "id": "broken",
                "title": "Broken event",
                "sourceUrl": "not-a-url",
                "date": "2026-06-12T12:00:00",
            }
        ] * fetch_events.MIN_HEALTHY_EVENTS
        health = {
            "Prague.eu": {
                "events": 0,
                "pagesFetched": 1,
                "pagesExpected": 1,
            }
        }

        with patch.object(
            fetch_events,
            "datetime",
            wraps=fetch_events.datetime,
        ) as mocked_datetime:
            mocked_datetime.now.return_value = datetime(2026, 6, 10, 9, 0)
            issues = fetch_events.validate_health(events, [], health, 30)

        self.assertTrue(any("no upcoming events" in issue for issue in issues))
        self.assertTrue(any("Invalid source URL" in issue for issue in issues))

    def test_health_allows_empty_venue_specific_sources(self):
        events = [
            {
                "id": f"valid-{index}",
                "title": f"Valid event {index}",
                "sourceUrl": "https://example.com/event",
                "date": "2026-06-12T12:00:00",
            }
            for index in range(fetch_events.MIN_HEALTHY_EVENTS)
        ]
        health = {
            "O2 arena": {
                "events": 0,
                "pagesFetched": 1,
                "pagesExpected": 1,
            }
        }

        with patch.object(
            fetch_events,
            "datetime",
            wraps=fetch_events.datetime,
        ) as mocked_datetime:
            mocked_datetime.now.return_value = datetime(2026, 6, 10, 9, 0)
            issues = fetch_events.validate_health(events, [], health, 30)

        self.assertEqual(issues, [])

    def test_health_allows_unreachable_optional_sources(self):
        events = [
            {
                "id": f"valid-{index}",
                "title": f"Valid event {index}",
                "sourceUrl": "https://example.com/event",
                "date": "2026-06-12T12:00:00",
            }
            for index in range(fetch_events.MIN_HEALTHY_EVENTS)
        ]
        health = {
            group: {
                "events": 0,
                "pagesFetched": 0,
                "pagesExpected": 1,
            }
            for group in ("Eventbrite tech", "Divadlo Gong", "O2 arena")
        }

        with patch.object(
            fetch_events,
            "datetime",
            wraps=fetch_events.datetime,
        ) as mocked_datetime:
            mocked_datetime.now.return_value = datetime(2026, 6, 10, 9, 0)
            issues = fetch_events.validate_health(events, [], health, 30)

        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
