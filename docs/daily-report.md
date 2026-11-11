# Tiny’s Daily Report

The existing production email now starts with today's weather and recommended
departure windows, followed by the complete job report. Gmail sender, recipient,
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
   portal. A normal morning run uses **56 Routing requests** (four directions ×
   fourteen hourly departures from 08:00 to 21:00); a manual run later in the
   day uses fewer because only future departures are queried. Consider setting
   a spending limit or staying on the free tier.

### 2. Add the GitHub secret

1. Open the repository's
   [Settings → Secrets and variables → Actions](https://github.com/corrida-repos/tiny-job-scraper/settings/secrets/actions).
2. Choose **New repository secret**.
3. Name: `TOMTOM_API_KEY` (exactly, upper case). Secret: the TomTom key.
4. Choose **Add secret**. The workflow already passes it to the report step;
   no code or workflow change is needed. The existing Gmail and state secrets
   stay as they are.

### 3. Verify without sending an email

1. Go to **Actions → Tiny’s Daily Report → Run workflow**, leave `send_email`
   unchecked, and run it. Run it before 20:00 Lisbon time so at least two
   future departures remain.
2. Open the run summary. A **Traffic forecasts** notice reports one of:
   - *TomTom traffic used for all 4 directions.* Setup is complete.
   - *TOMTOM_API_KEY not configured…* The secret is missing or misnamed.
   - *TOMTOM_API_KEY is set but N of 4 directions fell back to weather-only…*
     The key is rejected, lacks Routing API access, or is over quota; check the
     key on the TomTom dashboard. The key and request URLs are never logged.
3. In the next email, each direction's windows show journey minutes and a
   *traffic uplift*, and the **Weather-only comparison** banner is gone.

To stop using traffic, delete the secret; reports return to weather-only.

### What weather-only means

Without that secret, or with failed/incomplete routing, the email explicitly
shows **weather-only** windows using an approximate corridor. It does not claim
to account for traffic or invent journey times. A routing outage for any sample
in a direction makes that direction's comparison weather-only for consistency.

## Locations and recommendations

Edit `config/daily-report.json` for origin/destination coordinates and first/last
departure hours. Areias is the **parish centre in Santo Tirso**, near the supplied
home postcode, rather than an exact home address; Braga and Porto are city
centres. Door-to-door endpoints can materially change the results. Default
TomTom routes allow toll roads and use the fastest car route.

Each direction is queried independently for departures from **08:00 to 21:00**.
Only future departures are evaluated in manual/late runs. Five points along each
returned route get weather checks at approximate passage times proportional to
distance. These are rounded to 0.01° for weather lookup. The worse of the bounding
hourly forecasts is used, including arrival weather. Without routing, the next
two hours are checked at five approximate corridor points; no duration is inferred.

The email shows up to three nonoverlapping one-hour windows spanning adjacent
evaluated departures. Forecasts between those samples may differ. It ranks lower
weather concern first, then maximum journey minutes plus five times rain in mm/h
plus rain probability divided by twenty. Weather-only ranking omits journey
minutes. Caution starts at rain 0.5 mm/h, gusts 40 km/h or visibility under 5 km.
Samples with rain at least 4 mm/h, gusts at least 60 km/h, visibility under 1 km,
snow/ice/thunderstorms, or precipitation at temperatures at most 2 °C are excluded.
If no suitable pair remains, it says so. Missing weather is excluded rather than
treated as clear. These thresholds are planning aids, not calibrated safety ratings.

TomTom predicts later traffic from historical patterns and available live
information. The uplift compares predicted duration to the provider's no-traffic
duration; it is not a live congestion measurement for later hours. Incidents,
closures and conditions can change after generation. The email links IPMA
warnings and recommends checking current navigation before departure.

Forecasts stay within the encrypted email draft. Public Actions artifacts keep
the existing encrypted-bundle policy. Tests mock providers and never require
credentials or send email. Manual workflow dispatch still defaults to validation
only; enabling `send_email` uses the configured production recipient.
