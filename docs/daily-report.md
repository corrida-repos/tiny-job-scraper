# Tiny’s Daily Report

The production email now starts with **the best time to leave home and the best
time to return home** for Braga and Porto, chosen from forecast rain and predicted
traffic, followed by the complete job report. Gmail sender, recipient,
encrypted runtime state and duplicate-send reconciliation use the existing setup.
The subject is **Tiny’s Daily Report**. A weather failure leaves a visible
unavailable section and the job report still goes out. A prepared delivery retry
uses its original checkpointed draft rather than fetching a different forecast.

## Schedule

`.github/workflows/daily-jobs.yml` starts at **06:53 Europe/Lisbon**, every day,
leaving time for the scraper's 37-minute retrieval limit and report generation
before the requested **08:00** delivery target. Summer and winter UTC triggers
are filtered by Lisbon's offset. A delayed run still selects the right seasonal
trigger. GitHub scheduling and email transport can delay delivery; this is a
target, not a guaranteed deadline. No second scheduler or email is introduced.

## Weather and traffic setup

Open-Meteo supplies hourly temperature, rain, probability, gusts, visibility and
weather codes without an API key. Traffic-aware journey times need a TomTom key
stored as the GitHub Actions secret **`TOMTOM_API_KEY`**. Without it, the email
still arrives, and every direction is clearly labelled **weather-only** (see
below).

### 1. Get a TomTom API key

1. Sign up or log in at the [TomTom Developer Portal](https://developer.tomtom.com/).
2. Open the **Dashboard → Keys** (API keys) page. New accounts usually get a
   default key; otherwise create one. Make sure the key includes the
   **Routing API**.
3. Copy the key value. Never commit it, put it in a file in this repository, or
   paste it into chat.
4. Check the current free allowance, usage terms and billing settings on the
   portal. A normal morning run uses **24 Routing requests** (for each of Braga
   and Porto: five leave times 08:00–12:00 and seven return times 15:00–21:00)
   plus one address lookup; a manual run later in the day uses fewer because
   only future times are queried. Consider setting
   a spending limit or staying on the free tier.

### 2. Add the GitHub secret

1. Open the repository's
   [Settings → Secrets and variables → Actions](https://github.com/corrida-repos/tiny-job-scraper/settings/secrets/actions).
2. Choose **New repository secret**.
3. Name: `TOMTOM_API_KEY` (exactly, upper case). Secret: the TomTom key.
4. Choose **Add secret**. The workflow already passes it to the report step;
   no code or workflow change is needed. The existing Gmail and state secrets
   stay as they are.

### 3. Add your home address (kept out of the public repository)

This repository is public, so the home address is never committed. Add a second
repository secret on the same page: Name `HOME_ADDRESS`, Secret your full street
address including postcode, e.g. `Rua Example 1, 4780-000 Areias, Santo Tirso`.
Each run asks TomTom (same key) for its coordinates and routes from your door.
The address and coordinates are never printed in logs or the email. If the
secret is missing, the lookup fails, or the match is more than ~15 km from the
configured parish centre, the report uses the Areias parish centre and says so.

### 4. Verify without sending an email

1. Go to **Actions → Tiny’s Daily Report → Run workflow**, leave `send_email`
   unchecked, and run it. Run it before 20:00 Lisbon time so at least two
   future departures remain.
2. Open the run summary. A **Traffic forecasts** notice reports one of:
   - *TomTom traffic used for all 4 trips.* Setup is complete. If it also says
     *Home location: HOME_ADDRESS not set* (or *address lookup failed*), the
     report is using the parish centre instead of your door.
   - *TOMTOM_API_KEY not configured…* The secret is missing or misnamed.
   - *TOMTOM_API_KEY is set but N of 4 trips fell back to rain only…*
     The notice adds how many departure forecasts succeeded and the HTTP
     status of failures: 401/403 means the key is rejected or lacks Routing API
     access; 429 means it is over quota. The key and request URLs are never logged.
3. In the next email, each recommendation shows journey minutes and traffic
   level, and no *based on rain only* note appears.

To stop using traffic, delete the secret; recommendations return to rain only.

### What rain only means

Without that secret, or with failed routing, the email explicitly says the time
was chosen **based on rain only**, using an approximate corridor. It does not claim
to account for traffic or invent journey times. Requests to TomTom are spaced
out and rate-limit refusals are retried. If only some times fail, the trip keeps its
traffic comparison, lists the times without a forecast and never recommends
them; only a trip with no traffic forecasts at all falls back to rain only.

## Locations and recommendations

`config/daily-report.json` sets the home label and fallback point (the Areias
parish centre), the destinations (Braga and Porto city centres), and the hour
ranges: **leave 08:00–12:00** and **return 15:00–21:00**, checked hourly. Edit
those ranges to match your day. Routes are the fastest car route with tolls allowed.

For each destination the email gives:

- **Leave home: HH:MM** (home → destination) and **Return home: HH:MM**
  (destination → home), each with predicted minutes, traffic level (light under
  5 extra minutes, moderate under 15, heavy beyond) and rain;
- a *Next best* time and, when clearly worse, a time to *Avoid*;
- a short weather summary for home and each destination with the rain periods.

Each time is scored as predicted minutes plus a rain penalty: 15 minutes once
rain reaches 0.5 mm/h, gusts 40 km/h or visibility under 5 km, plus 5 × mm/h of
rain plus rain probability ÷ 20. The lowest score wins. So a time that is dry
beats one about 15–25 minutes quicker in steady rain. Times with rain at least
4 mm/h, gusts at least 60 km/h, visibility under 1 km, snow, ice, thunderstorms
or rain near freezing are never recommended; if every time is like that, the
email says there is no good time. Rain is checked at five points along the
route at the time you would pass each one, using the worse of the two bounding
hourly forecasts. Without traffic, the next two hours along an approximate
corridor are checked and no journey time is claimed. Missing weather is left
out rather than treated as dry. These are planning aids, not safety ratings.

TomTom predicts later traffic from historical patterns and available live
information. The uplift compares predicted duration to the provider's no-traffic
duration; it is not a live congestion measurement for later hours. Incidents,
closures and conditions can change after generation. The email links IPMA
warnings and recommends checking current navigation before departure.

Forecasts stay within the encrypted email draft. Public Actions artifacts keep
the existing encrypted-bundle policy. Tests mock providers and never require
credentials or send email. Manual workflow dispatch still defaults to validation
only; enabling `send_email` uses the configured production recipient.
