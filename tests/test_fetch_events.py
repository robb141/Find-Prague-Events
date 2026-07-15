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
            "Eventbrite tech": {
                "events": 0,
                "pagesFetched": 0,
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


if __name__ == "__main__":
    unittest.main()
