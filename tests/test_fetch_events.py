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
            "Ticketmaster": {
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


if __name__ == "__main__":
    unittest.main()
