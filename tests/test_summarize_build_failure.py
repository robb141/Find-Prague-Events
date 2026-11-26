import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import summarize_build_failure as sbf


def gh_log(step, lines, job="test"):
    """Format lines the way `gh run view --log-failed` prints them."""
    return "\n".join(f"{job}\t{step}\t2026-11-19T10:00:00.0000000Z {line}" for line in lines)


UNITTEST_FAILURE = gh_log(
    "Run tests",
    [
        "test_ok (tests.test_x.T.test_ok) ... ok",
        "test_bad (tests.test_x.T.test_bad) ... FAIL",
        "",
        "======================================================================",
        "FAIL: test_bad (tests.test_x.T.test_bad)",
        "----------------------------------------------------------------------",
        "Traceback (most recent call last):",
        '  File "tests/test_x.py", line 12, in test_bad',
        "    self.assertEqual(1, 2)",
        "AssertionError: 1 != 2",
        "",
        "FAILED (failures=1)",
        "##[error]Process completed with exit code 1.",
    ],
)


def fake_response(text="**Likely causes:** x", stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
    )


class ExtractFirstErrorTests(unittest.TestCase):
    def test_finds_unittest_failure_header_and_step(self):
        excerpt = sbf.extract_first_error(UNITTEST_FAILURE)

        self.assertEqual(excerpt.step, "Run tests")
        self.assertEqual(excerpt.line_number, 5)
        self.assertIn("FAIL: test_bad", excerpt.text)
        self.assertIn("AssertionError: 1 != 2", excerpt.text)
        self.assertNotIn("2026-11-19T10", excerpt.text)

    def test_specific_error_beats_earlier_generic_mention(self):
        log = gh_log(
            "Run tests",
            ["Installing error-tracker 1.0", "ok"] + ["filler"] * 20 + ["ERROR: test_x (m.T)"],
        )

        excerpt = sbf.extract_first_error(log)

        self.assertEqual(excerpt.line_number, 23)

    def test_finds_ruff_full_output(self):
        log = gh_log(
            "Lint Python (ruff)",
            [
                "Successfully installed ruff-0.16.3",
                "F401 [*] `os` imported but unused",
                " --> fetch_events.py:3:8",
                "Found 1 error.",
            ],
        )

        excerpt = sbf.extract_first_error(log)

        self.assertEqual(excerpt.step, "Lint Python (ruff)")
        self.assertEqual(excerpt.line_number, 3)
        self.assertIn("F401 [*] `os` imported but unused", excerpt.text)

    def test_whole_job_log_is_searched_only_inside_the_failing_step(self):
        # gh labels every line "UNKNOWN STEP" and dumps the whole job, including
        # passing steps and post-job cleanup; the first line carries a BOM.
        log = gh_log(
            sbf.UNKNOWN_STEP,
            [
                "Current runner version: '2.337.0'",
                "##[group]Run python3 -m unittest discover -s tests -v",
                "##[endgroup]",
                "Traceback (most recent call last):",
                "ValueError: logged on purpose by a passing test",
                "OK",
                "##[group]Run python3 fetch_events.py --days 30 --strict-health",
                "##[endgroup]",
                "Fetching sources...",
                "Health checks failed; existing event data was not replaced.",
                '    "Kudy z nudy: HTTP Error 429: Too Many Requests"',
                "##[error]Process completed with exit code 1.",
                "##[group]Run actions/upload-artifact@v7",
                "SHA256 digest of uploaded artifact is abc123",
            ],
            job="refresh",
        ).replace("STEP\t2026", "STEP\t﻿2026", 1)

        excerpt = sbf.extract_first_error(log)

        self.assertEqual(sbf.clean_log(log)[0], ("", "Current runner version: '2.337.0'"))
        self.assertEqual(excerpt.step, "Run python3 fetch_events.py --days 30 --strict-health")
        self.assertEqual(excerpt.line_number, 10)
        self.assertIn("Health checks failed", excerpt.text)
        self.assertTrue(excerpt.text.endswith("##[error]Process completed with exit code 1."))
        self.assertNotIn("ValueError", excerpt.text)
        self.assertNotIn("SHA256", excerpt.text)

    def test_failing_step_without_error_lines_uses_its_last_lines(self):
        log = gh_log(
            "Build",
            ["##[group]Run make", "##[endgroup]", "step one", "step two",
             "##[error]Process completed with exit code 2.", "Post job cleanup."],
        )

        excerpt = sbf.extract_first_error(log)

        self.assertTrue(excerpt.text.startswith("##[group]Run make"))
        self.assertIn("step two", excerpt.text)
        self.assertNotIn("Post job cleanup", excerpt.text)

    def test_finds_eslint_error_with_file_name_above(self):
        log = gh_log(
            "Lint JS (eslint)",
            ["", "/repo/script.js", "  14:7  error  'x' is assigned a value but never used  no-unused-vars"],
        )

        excerpt = sbf.extract_first_error(log)

        self.assertEqual(excerpt.line_number, 3)
        self.assertIn("/repo/script.js", excerpt.text)

    def test_strips_ansi_colour_codes(self):
        log = gh_log("Run tests", ["\x1b[31mERROR: boom\x1b[0m"])

        self.assertEqual(sbf.extract_first_error(log).text, "ERROR: boom")

    def test_falls_back_to_the_log_tail(self):
        lines = [f"line {i}" for i in range(100)]

        excerpt = sbf.extract_first_error("\n".join(lines))

        self.assertTrue(excerpt.text.endswith("line 99"))
        self.assertNotIn("line 10\n", excerpt.text)

    def test_empty_log_returns_none(self):
        self.assertIsNone(sbf.extract_first_error("\n\n"))

    def test_long_excerpt_is_capped(self):
        log = "ERROR: x\n" + "\n".join("y" * 500 for _ in range(60))

        excerpt = sbf.extract_first_error(log)

        self.assertLessEqual(len(excerpt.text), sbf.MAX_EXCERPT_CHARS + 30)
        self.assertTrue(excerpt.text.endswith("(excerpt truncated)"))


class SummarizeTests(unittest.TestCase):
    def setUp(self):
        self.excerpt = sbf.ErrorExcerpt(step="Run tests", line_number=5, text="FAIL: test_bad")

    def test_sends_excerpt_and_changed_files_to_claude(self):
        client = MagicMock()
        client.beta.messages.create.return_value = fake_response("Cause A")

        summary = sbf.summarize(self.excerpt, ["weekly_digest.py"], client)

        self.assertEqual(summary, "Cause A")
        kwargs = client.beta.messages.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-opus-5-5")
        self.assertEqual(kwargs["fallbacks"], "default")
        prompt = kwargs["messages"][0]["content"]
        self.assertIn("FAIL: test_bad", prompt)
        self.assertIn("weekly_digest.py", prompt)
        self.assertIn("Failed step: Run tests", prompt)

    def test_refusal_raises(self):
        client = MagicMock()
        client.beta.messages.create.return_value = fake_response("", stop_reason="refusal")

        with self.assertRaises(sbf.SummaryError):
            sbf.summarize(self.excerpt, [], client)

    def test_empty_text_raises(self):
        client = MagicMock()
        client.beta.messages.create.return_value = fake_response("  ")

        with self.assertRaises(sbf.SummaryError):
            sbf.summarize(self.excerpt, [], client)

    def test_changed_file_list_is_capped(self):
        files = [f"f{i}.py" for i in range(sbf.MAX_CHANGED_FILES + 5)]

        prompt = sbf.build_prompt(self.excerpt, files)

        self.assertIn("... and 5 more", prompt)
        self.assertNotIn(f"f{sbf.MAX_CHANGED_FILES}.py", prompt)


class RenderCommentTests(unittest.TestCase):
    def test_includes_marker_summary_excerpt_and_link(self):
        excerpt = sbf.ErrorExcerpt(step="Run tests", line_number=5, text="FAIL: x")

        body = sbf.render_comment(excerpt, "Cause A", run_url="https://example.com/run/1")

        self.assertTrue(body.startswith(sbf.COMMENT_MARKER))
        self.assertIn("`Run tests`", body)
        self.assertIn("[full log](https://example.com/run/1)", body)
        self.assertIn("Cause A", body)
        self.assertIn("First error from the log", body)
        self.assertIn("can be wrong", body)

    def test_without_summary_explains_why(self):
        excerpt = sbf.ErrorExcerpt(step="", line_number=1, text="boom")

        body = sbf.render_comment(excerpt, None, failure_reason="no API key")

        self.assertIn("_No AI summary: no API key._", body)
        self.assertIn("unknown step", body)
        self.assertNotIn("Summary written by Claude", body)

    def test_fence_survives_backticks_in_the_log(self):
        excerpt = sbf.ErrorExcerpt(step="s", line_number=1, text="```\nmarkdown in log\n````")

        body = sbf.render_comment(excerpt, None, failure_reason="x")

        self.assertIn("`````text", body)


class UpsertCommentTests(unittest.TestCase):
    def test_updates_existing_bot_comment(self):
        comments = [
            {"id": 1, "user": {"type": "User"}, "body": sbf.COMMENT_MARKER},
            {"id": 2, "user": {"type": "Bot"}, "body": f"{sbf.COMMENT_MARKER}\nold"},
        ]
        calls = []

        def fake_request(method, url, token, payload=None):
            calls.append((method, url, payload))
            return comments if method == "GET" else {"html_url": "https://gh/c/2"}

        with patch.object(sbf, "github_request", side_effect=fake_request):
            url = sbf.upsert_comment("o/r", 7, "new", "tok")

        self.assertEqual(url, "https://gh/c/2")
        self.assertEqual(calls[-1][0], "PATCH")
        self.assertTrue(calls[-1][1].endswith("/repos/o/r/issues/comments/2"))

    def test_creates_comment_when_none_exists(self):
        calls = []

        def fake_request(method, url, token, payload=None):
            calls.append((method, url, payload))
            return [] if method == "GET" else {"html_url": "https://gh/c/9"}

        with patch.object(sbf, "github_request", side_effect=fake_request):
            sbf.upsert_comment("o/r", 7, "new", "tok")

        self.assertEqual(calls[-1][0], "POST")
        self.assertTrue(calls[-1][1].endswith("/repos/o/r/issues/7/comments"))
        self.assertEqual(calls[-1][2], {"body": "new"})


class ResolvedCommentTests(unittest.TestCase):
    def test_resolved_body_keeps_marker_and_shortens_sha(self):
        body = sbf.render_resolved_comment("https://example.com/run/2", "abcdef1234567890")

        self.assertTrue(body.startswith(sbf.COMMENT_MARKER))
        self.assertIn("as of `abcdef1`", body)
        self.assertIn("[run](https://example.com/run/2)", body)

    def test_edits_existing_comment(self):
        calls = []

        def fake_request(method, url, token, payload=None):
            calls.append((method, url, payload))
            if method == "GET":
                return [{"id": 5, "user": {"type": "Bot"}, "body": sbf.COMMENT_MARKER}]
            return {"html_url": "https://gh/c/5"}

        with patch.object(sbf, "github_request", side_effect=fake_request):
            url = sbf.resolve_comment("o/r", 7, "fixed", "tok")

        self.assertEqual(url, "https://gh/c/5")
        self.assertEqual(calls[-1], ("PATCH", f"{sbf.GITHUB_API}/repos/o/r/issues/comments/5", {"body": "fixed"}))

    def test_never_creates_a_comment_on_a_pr_that_never_failed(self):
        with patch.object(sbf, "github_request", return_value=[]) as request:
            url = sbf.resolve_comment("o/r", 7, "fixed", "tok")

        self.assertIsNone(url)
        self.assertEqual([c.args[0] for c in request.call_args_list], ["GET"])

    def test_resolved_mode_needs_no_log(self):
        args = sbf.parse_args(["--resolved", "--pr", "7"])

        self.assertTrue(args.resolved)
        self.assertIsNone(args.log)

    def test_log_required_without_resolved(self):
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            sbf.parse_args(["--pr", "7"])


class MainTests(unittest.TestCase):
    def test_prints_comment_with_extracted_error_when_claude_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp, "failed.log")
            log.write_text(UNITTEST_FAILURE, encoding="utf-8")
            out = Path(tmp, "comment.md")

            with (
                patch.object(sbf, "try_summarize", return_value=(None, "offline")),
                patch("builtins.print"),
            ):
                code = sbf.main(["--log", str(log), "--output", str(out)])

            body = out.read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertIn("FAIL: test_bad", body)
        self.assertIn("_No AI summary: offline._", body)

    def test_post_requires_pr(self):
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            sbf.parse_args(["--log", "x", "--post"])


if __name__ == "__main__":
    unittest.main()
