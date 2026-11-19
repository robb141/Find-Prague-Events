# FindPragueEvents

A static Prague event finder. Open `index.html` directly in a browser.

## Refresh Events

Run:

```bash
python3 fetch_events.py --days 30
```

This writes `data.js`, which `index.html` loads before `script.js`.

## Daily Automatic Refresh

The GitHub Actions workflow at `.github/workflows/update-events.yml` runs every day at `04:17 UTC`, which is `06:17` in Prague during summer time and `05:17` during winter time.

It:

1. Runs `python3 fetch_events.py --days 30 --strict-health`.
2. Updates `data.js`.
3. Commits and pushes the change when event data changed.

The strict health check verifies that every source group can be reached and
returns upcoming events, that the total feed is not unexpectedly small, and
that event dates and source links are valid. A failed check leaves the last
known-good `data.js` untouched.

The workflow can also be run manually from:

```text
GitHub repository -> Actions -> Update events -> Run workflow
```

## Weekly Email Digest

The `Weekly event digest` workflow at `.github/workflows/weekly-digest.yml`
runs every Monday at `06:30 UTC` and emails the most interesting one-off
events for the coming seven days. It ranks AI/IT/DevOps events first, then
food and drink, then festivals, fairs, open days and other unique happenings.
Regular programme is left out: theatre, exhibitions, galleries and museums,
guided tours, weekly farmers' markets, anything whose title repeats on four or
more days in the feed, and events marked cancelled or postponed.

The workflow fetches a fresh eight-day feed first and falls back to the
committed `data.js` if the fetch fails. The rendered HTML is uploaded as the
`weekly-digest` workflow artifact so you can check what was sent.

Add these repository secrets under
`Settings -> Secrets and variables -> Actions`:

| Secret | Required | Purpose |
| --- | --- | --- |
| `DIGEST_EMAIL_TO` | yes | Recipient address. |
| `SMTP_USERNAME` | yes | SMTP login, for Gmail the full address. |
| `SMTP_PASSWORD` | yes | SMTP password, for Gmail a 16-character App Password. |
| `DIGEST_EMAIL_FROM` | no | Sender address; defaults to `SMTP_USERNAME`. |
| `SMTP_HOST` | no | Defaults to `smtp.gmail.com`. |
| `SMTP_PORT` | no | STARTTLS port, defaults to `587`. |

For Gmail, enable 2-Step Verification on the account and create an App
Password at <https://myaccount.google.com/apppasswords>. Use that password,
not the account password.

Preview the digest locally without sending anything:

```bash
python3 weekly_digest.py --dry-run
python3 weekly_digest.py --start 2026-10-19 --html-out digest.html
```

Send it locally with the same environment variables the workflow uses:

```bash
DIGEST_EMAIL_TO="you@example.com" SMTP_USERNAME="you@gmail.com" \
SMTP_PASSWORD="app-password" python3 weekly_digest.py --send
```

The workflow can also be started manually from
`Actions -> Weekly event digest -> Run workflow`, where you can pick a start
date or tick "dry run" to only print the digest in the job log.

## Tests

Run the automated test suite locally:

```bash
python3 -m unittest discover -s tests -v
```

The `Tests` GitHub Actions workflow runs this suite on every push to `main` and
on pull requests. The daily `Update events` workflow also runs it before
fetching or committing event data.

The repository workflow permission must allow GitHub Actions to write:

```text
Settings -> Actions -> General -> Workflow permissions -> Read and write permissions
```

### Ticketmaster Discovery Feed

Ticketmaster events use the official Czech Discovery Feed when an API key is
available. Add the Consumer Key from the Ticketmaster Developer Portal as a
GitHub Actions repository secret named `TICKETMASTER_API_KEY`:

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

For a local refresh, provide the key only through the environment:

```bash
TICKETMASTER_API_KEY="your-key" python3 fetch_events.py --days 30
```

The key is never written to `data.js`. If the key is missing or the feed is
temporarily unavailable, the collector falls back to the public Ticketmaster
Prague listings.

The app also filters `data.js` in the browser and never displays an event dated before the current local day. This means yesterday's events disappear at midnight even if the scheduled refresh is delayed.

## Build Failure Summaries

When the `Tests` workflow fails on a pull request, the `Build failure summary`
workflow at `.github/workflows/build-failure-summary.yml` comments on the PR.
The comment has the first error from the failing step and a short Claude
summary of likely causes, so you don't have to read the whole log. Each new
failure updates the same comment instead of adding another one, and once the
tests pass again the comment is edited to say the build is fixed.

It needs one repository secret under
`Settings -> Secrets and variables -> Actions`:

| Secret | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude API key from <https://platform.claude.com/>. |

Without the secret the comment is still posted with the extracted error. The
workflow uses `workflow_run`, so it only starts working once it is on `main`,
and it also runs for pull requests from forks without checking out their code.

Try it on a failed run locally (prints the comment, posts nothing):

```bash
pip install "anthropic>=2.10,<3"
gh run view <run-id> --log-failed > failed.log
python3 summarize_build_failure.py --log failed.log
```

## Run On Android

From this folder on your Mac:

```bash
python3 -m http.server 8000 --bind 0.0.0.0
```

Find your Mac's local Wi-Fi IP:

```bash
ipconfig getifaddr en0
```

On your Android phone, connect to the same Wi-Fi network and open:

```text
http://YOUR_MAC_IP:8000
```

For example, if the IP command prints `x.x.x.x`, open:

```text
http://x.x.x.x:8000
```

If it does not load, allow Python through the macOS firewall or try another port such as `8080`.

## Use Away From Home Wi-Fi

The local `x.x.x.x` address only works on your home Wi-Fi. To use the app from mobile data or another network, publish these static files to an HTTPS host, then install it on Android from Chrome.

Recommended safe options:

- GitHub Pages
- Cloudflare Pages
- Netlify

After publishing, open the HTTPS URL on Android Chrome, then use:

```text
Chrome menu -> Add to Home screen / Install app
```

The app includes `manifest.webmanifest` and `sw.js`, so Android can install it and cache the latest downloaded event data.

Do not expose the Python local server directly to the internet with router port forwarding. For a temporary private test, a tunnel such as Cloudflare Tunnel or ngrok is safer than opening your router, but a normal static host is better for daily use.

List the source pages:

```bash
python3 fetch_events.py --list-sources
```

## Source Sites

- Prague.eu events: `https://prague.eu/en/akce-kategorie/events/`
- Prague.eu concerts: `https://prague.eu/en/akce-kategorie/concerts/`
- Prague.eu exhibitions: `https://prague.eu/en/akce-kategorie/exhibitions/`
- Prague.eu festivals: `https://prague.eu/en/akce-kategorie/festivals-celebrations/`
- Prague.eu markets: `https://prague.eu/en/akce-kategorie/markets-gourmet/`
- Prague.eu performing arts: `https://prague.eu/en/akce-kategorie/performing-arts/`
- Prague.eu sports: `https://prague.eu/en/akce-kategorie/sports/`
- GoOut Prague events: `https://goout.net/en/events/lez/`
- O2 arena events: `https://www.o2arena.cz/en/events/`
- CityBee events: `https://www.citybee.cz/akce/`
- CityBee paginated listings: `https://www.citybee.cz/vyhledavani/:/akce/prehled/strana/{page}/` — the true page count is discovered from the site's pagination bar (capped at 40 pages as a safety limit), falling back to 5 pages if detection fails
- Ticketmaster Prague search: `https://www.ticketmaster.cz/search?keyword=Praha` (plus 3 more paginated result pages)
- Ticketportal O2 arena listings: `https://www.ticketportal.cz/venue/O2-arena?idpartner=382KD`
- Ticketportal Prague Congress Centre listings: `https://www.ticketportal.cz/Venue/1201393`
- Kudy z nudy Prague calendar: `https://www.kudyznudy.cz/kalendar-akci/hlavni-mesto-praha`
- Forum Karlín events: `https://www.forumkarlin.cz/en/events/`
- Divadlo Gong (Praha 9, Vysočany) program: `https://www.divadlogong.cz/program/`
- PVA EXPO Praha (Praha 9, Letňany) calendar: `https://pvaexpo.cz/cs/akce`
- Eventbrite Prague science & tech: `https://www.eventbrite.com/d/czech-republic--prague/science-and-tech--events/`
- confs.tech conference data (per-topic JSON): `https://raw.githubusercontent.com/tech-conferences/conference-data/main/conferences/<year>/<topic>.json`

Venue-only and tech sources (O2 arena, Forum Karlín, Divadlo Gong, PVA Expo,
Eventbrite, confs.tech) are optional: fetch failures there are recorded as
health warnings but do not block a strict-health refresh. The aggregator
sources (Prague.eu, CityBee, Ticketmaster, and the other listing sites) still
fail the health check when unreachable.
