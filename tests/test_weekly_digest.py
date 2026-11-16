import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import weekly_digest

START = date(2026, 10, 19)


def event(title, day, category="Things to do", **extra):
    base = {
        "title": title,
        "category": category,
        "venue": "Somewhere",
        "date": f"{day}T19:00:00",
        "price": None,
        "popularity": 60,
        "english": True,
        "tags": [],
        "description": "",
        "sourceUrl": f"https://example.com/{title.lower().replace(' ', '-')}",
    }
    base.update(extra)
    return base


class SelectionTests(unittest.TestCase):
    def test_keeps_only_events_inside_the_window(self):
        events = [
            event("Before", "2026-10-18"),
            event("First day", "2026-10-19"),
            event("Last day", "2026-10-25"),
            event("After", "2026-10-26"),
        ]

        titles = [pick["title"] for pick in weekly_digest.select_picks(events, START)]

        self.assertEqual(sorted(titles), ["First day", "Last day"])

    def test_drops_theatre_exhibitions_and_goout_categories(self):
        events = [
            event("Hamlet", "2026-10-20", "Theatre"),
            event("Monet", "2026-10-20", "Exhibitions"),
            event("Harry Potter", "2026-10-20", "GoOut"),
            event("Soup Festival", "2026-10-20", "Food Events"),
        ]

        titles = [pick["title"] for pick in weekly_digest.select_picks(events, START)]

        self.assertEqual(titles, ["Soup Festival"])

    def test_drops_titles_that_repeat_across_the_feed(self):
        weekly = [event("Daily show", f"2026-10-{day}") for day in ("14", "20", "27")]
        weekly.append(event("Daily show", "2026-11-03"))
        events = weekly + [event("One-off", "2026-10-21")]

        titles = [pick["title"] for pick in weekly_digest.select_picks(events, START)]

        self.assertEqual(titles, ["One-off"])

    def test_drops_markets_tours_and_museums_by_keyword(self):
        events = [
            event("Náplavka Farmers’ Market", "2026-10-24", "Markets"),
            event("Castle guided tour", "2026-10-24"),
            event("Night at the museum", "2026-10-24"),
            event("Dyzajn market Autumn", "2026-10-24", "Markets"),
        ]

        titles = [pick["title"] for pick in weekly_digest.select_picks(events, START)]

        self.assertEqual(titles, ["Dyzajn market Autumn"])

    def test_drops_cancelled_and_postponed_events(self):
        events = [
            event("Rock Voices", "2026-10-21", description="ODLOŽENO NA NEURČITO Vážení klienti..."),
            event("Comedy night", "2026-10-21", description="Cancelled due to illness."),
            event("Still on", "2026-10-21"),
        ]

        titles = [pick["title"] for pick in weekly_digest.select_picks(events, START)]

        self.assertEqual(titles, ["Still on"])

    def test_ranks_tech_then_food_before_everything_else(self):
        events = [
            event("Slavia match", "2026-10-20", "Sports", popularity=99),
            event("Jazz concert", "2026-10-20", "Concerts", popularity=99),
            event("Coffee Festival", "2026-10-21", "Food Events", popularity=40),
            event("Prague DevOps Days", "2026-10-22", "IT & Tech", popularity=40),
            event("Halloween at the Zoo", "2026-10-23", "Festivals", popularity=40),
        ]

        titles = [pick["title"] for pick in weekly_digest.select_picks(events, START)]

        self.assertEqual(
            titles,
            ["Prague DevOps Days", "Coffee Festival", "Halloween at the Zoo", "Slavia match", "Jazz concert"],
        )

    def test_tech_keywords_in_title_promote_other_categories(self):
        events = [
            event("Random fair", "2026-10-20", "Fairs & Expos"),
            event("AI & Kubernetes meetup", "2026-10-20", "Fairs & Expos"),
        ]

        picks = weekly_digest.select_picks(events, START)

        self.assertEqual(picks[0]["title"], "AI & Kubernetes meetup")
        self.assertTrue(picks[0]["tech"])
        self.assertFalse(picks[1]["tech"])

    def test_concert_descriptions_never_count_as_tech_or_food(self):
        events = [
            event("Pluko", "2026-10-20", "Concerts", description="Producer famous on SoundCloud, beer on tap."),
        ]

        pick = weekly_digest.select_picks(events, START)[0]

        self.assertFalse(pick["tech"])
        self.assertFalse(pick["food"])

    def test_merges_multi_day_events_into_one_pick(self):
        events = [
            event("Coffee Festival", "2026-10-24", "Food Events"),
            event("Coffee Festival", "2026-10-25", "Food Events"),
        ]

        picks = weekly_digest.select_picks(events, START)

        self.assertEqual(len(picks), 1)
        self.assertEqual(picks[0]["days"], [date(2026, 10, 24), date(2026, 10, 25)])
        self.assertEqual(weekly_digest.format_days(picks[0]["days"]), "Sat 24 Oct – Sun 25 Oct")

    def test_respects_limit(self):
        events = [event(f"Event {index}", "2026-10-20") for index in range(20)]

        self.assertEqual(len(weekly_digest.select_picks(events, START, limit=5)), 5)

    def test_drops_boilerplate_descriptions(self):
        events = [
            event(
                "Soup Festival",
                "2026-10-20",
                "Food Events",
                description="Food Events listed by Prague.eu. Open the source page for tickets.",
            )
        ]

        self.assertEqual(weekly_digest.select_picks(events, START)[0]["description"], "")


class RenderTests(unittest.TestCase):
    def picks(self):
        events = [
            event("Prague DevOps Days", "2026-10-22", "IT & Tech", description="Talks & workshops"),
            event("Coffee Festival", "2026-10-24", "Food Events", price=250),
            event("Halloween at the Zoo", "2026-10-23", "Festivals", price=0),
        ]
        return weekly_digest.select_picks(events, START)

    def test_sections_follow_tech_food_other_order(self):
        names = [name for name, _ in weekly_digest.group_sections(self.picks())]

        self.assertEqual(names, ["AI, IT & DevOps", "Food & drink", "Other unique picks"])

    def test_text_body_lists_titles_links_and_prices(self):
        text = weekly_digest.render_text(self.picks(), START)

        self.assertIn("Prague events worth your week: 19 Oct – 25 Oct 2026", text)
        self.assertIn("- Prague DevOps Days (IT & Tech)", text)
        self.assertIn("https://example.com/prague-devops-days", text)
        self.assertIn("from 250 CZK", text)
        self.assertIn("Free", text)

    def test_html_body_escapes_and_links(self):
        html_body = weekly_digest.render_html(self.picks(), START)

        self.assertIn('<a href="https://example.com/coffee-festival"', html_body)
        self.assertIn("Talks &amp; workshops", html_body)
        self.assertIn(weekly_digest.APP_URL, html_body)

    def test_empty_digest_still_renders(self):
        self.assertIn("No one-off events matched", weekly_digest.render_text([], START))
        self.assertIn("No one-off events matched", weekly_digest.render_html([], START))

    def test_loads_events_from_data_js(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.js"
            payload = json.dumps([event("Loaded", "2026-10-20")], ensure_ascii=False)
            path.write_text(f'window.CATEGORIES = ["x"];\nwindow.EVENTS = {payload};\n', encoding="utf-8")

            self.assertEqual(weekly_digest.load_events(path)[0]["title"], "Loaded")


class SendTests(unittest.TestCase):
    def test_settings_require_recipient_and_credentials(self):
        with self.assertRaises(RuntimeError) as raised:
            weekly_digest.smtp_settings({"SMTP_USERNAME": "me@example.com"})

        self.assertIn("DIGEST_EMAIL_TO", str(raised.exception))
        self.assertIn("SMTP_PASSWORD", str(raised.exception))

    def test_settings_default_to_gmail_and_sender_from_username(self):
        settings = weekly_digest.smtp_settings(
            {"DIGEST_EMAIL_TO": "to@example.com", "SMTP_USERNAME": "me@example.com", "SMTP_PASSWORD": "secret"}
        )

        self.assertEqual(settings["host"], "smtp.gmail.com")
        self.assertEqual(settings["port"], 587)
        self.assertEqual(settings["sender"], "me@example.com")
        self.assertEqual(settings["recipient"], "to@example.com")

    def test_send_uses_starttls_login_and_multipart_message(self):
        message = weekly_digest.build_message([], START, 7, "me@example.com", "to@example.com")
        server = MagicMock()
        smtp = MagicMock()
        smtp.return_value.__enter__.return_value = server
        settings = {"host": "smtp.example.com", "port": 587, "username": "me@example.com", "password": "secret"}

        with patch.object(weekly_digest.smtplib, "SMTP", smtp):
            weekly_digest.send_message(message, settings)

        smtp.assert_called_once_with("smtp.example.com", 587, timeout=60)
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("me@example.com", "secret")
        server.send_message.assert_called_once_with(message)
        self.assertEqual(message["To"], "to@example.com")
        self.assertEqual([part.get_content_type() for part in message.iter_parts()], ["text/plain", "text/html"])

    def test_main_without_send_prints_and_skips_smtp(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.js"
            payload = json.dumps([event("Loaded", "2026-10-20", "Food Events")], ensure_ascii=False)
            path.write_text(f"window.EVENTS = {payload};\n", encoding="utf-8")
            with patch.object(weekly_digest, "send_message") as mocked_send:
                code = weekly_digest.main(["--data", str(path), "--start", "2026-10-19", "--dry-run"])

        self.assertEqual(code, 0)
        mocked_send.assert_not_called()

    def test_main_send_fails_clearly_without_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.js"
            path.write_text("window.EVENTS = [];\n", encoding="utf-8")
            with patch.dict(weekly_digest.os.environ, {}, clear=True):
                code = weekly_digest.main(["--data", str(path), "--start", "2026-10-19", "--send"])

        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
