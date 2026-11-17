# CloudCost AI

Multi-cloud cost management and optimization. Import AWS, Azure and GCP billing
exports, normalize them into one schema, and get a unified dashboard, anomaly
alerts, a spend forecast, rule-based savings recommendations and CSV reports.

Everything runs on sample data out of the box. No cloud account is needed and
the app never creates, stops, resizes or deletes cloud resources: it is
read-only by design.

## Quick start (local, SQLite)

Requires Python 3.11+.

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

(On macOS/Linux use `.venv/bin/python`.)

Copy `.env.example` to `.env`, then set `DJANGO_SECRET_KEY` to a long random
string and `DEMO_USER_PASSWORD` to a password of your choice. Keep
`DJANGO_DEBUG=true` for local use.

```bash
.venv/Scripts/python manage.py migrate
```

```bash
.venv/Scripts/python manage.py seed_demo
```

```bash
.venv/Scripts/python manage.py runserver
```

Open http://localhost:8000 and sign in as `demo` with the password you set in
`DEMO_USER_PASSWORD`. `seed_demo` creates the user, three cloud accounts,
imports the sample billing CSVs, the sample resource inventory and the sample
Infracost estimate, then runs the analysis pipeline.

You can also sign up as a new user and upload the files in `sample_data/`
yourself. Each user only ever sees their own data.

## What is in the app

| Page | What it does |
|---|---|
| Dashboard | Total spend, period-over-period change, daily trend by provider, breakdowns by provider, service, region and project, top resources. Filters: provider, service, project, date range. |
| Cloud accounts | Register the AWS / Azure / GCP accounts that imports belong to. No credentials are stored. |
| Imports | Upload a billing CSV (10 MB limit). Shows rows imported, rejected (with the reason per row) and skipped as duplicates. |
| Resources | Resource inventory imported from CloudQuery JSON. Inventory only, not billing. |
| Estimates | Infracost JSON for a Terraform plan. Shown separately and labelled as an estimate, never mixed into actual spend. |
| Anomalies | Days where a service's spend deviated from its rolling baseline, with the numbers that triggered the alert. Status: open, acknowledged, resolved, dismissed. |
| Forecast | 30-day forecast with an uncertainty band, the backtest error of each candidate model and the method's limitations. Needs 14 days of history. |
| Recommendations | Rule-based suggestions with the evidence behind each one and an estimated saving only where the data supports it. Status: open, accepted, rejected, implemented, with a review note. |
| Reports | CSV exports (costs, anomalies, recommendations) and a printable summary. |

### How the numbers are produced

- **Normalization.** Each provider has a column mapping (`ingestion/adapters.py`)
  into one `BillingRecord` schema. Rows are de-duplicated by a content hash, so
  re-uploading a file does not double-count.
- **Currencies.** Costs are converted to USD with the `ExchangeRate` table
  (edit it in the Django admin). Rows in a currency without a rate are left out
  of totals and the page says so; currencies are never summed unconverted. The
  seeded rates are static sample values, not live market rates.
- **Analytics.** `analytics/engine.py` loads a user's records into Pandas and
  queries them with DuckDB.
- **Anomalies.** Per provider and service, each day is compared with the
  previous 14 days: a z-score of 3 or more (and at least 25% above the mean), or
  75% above the mean, or new spend with no history. An anomaly is a statistical
  deviation worth a look, not a claim of error or fraud.
- **Forecast.** Three simple baselines (linear trend, 7-day moving average,
  weekday average) are backtested on the most recent weeks; the one with the
  lowest error is used and its error sets the band.
- **Recommendations.** Rules in `recommendations/rules.py` over billing and
  inventory: idle or unattached resources, concentration, fast-growing
  services, unattributed spend, steady compute suited to commitments.
- **Gemini (optional).** If `GEMINI_API_KEY` is set, a recommendation can be
  given a plain-language explanation. All figures are computed in code; the
  model only rephrases them, and a reply containing a number that is not in the
  evidence is discarded. Clicking "Explain" sends that recommendation's title
  and evidence to Google's API, so leave the key unset if that is not
  acceptable.

## Running the analysis

Uploading a billing file re-runs the analysis for that user. To run it for
everyone (this is what the scheduler calls):

```bash
.venv/Scripts/python manage.py run_pipeline
```

Add `--username demo` to limit it to one user.

## Tests

```bash
.venv/Scripts/python manage.py test
```

The suite covers valid files for each provider, missing columns, malformed
rows, negative, zero and implausibly large costs, multiple currencies,
duplicates, date formats and time zones, empty files, spike versus stable
spend, insufficient history and cross-user access.

## Docker Compose (PostgreSQL)

Set `POSTGRES_PASSWORD`, `DJANGO_SECRET_KEY` and `DEMO_USER_PASSWORD` in `.env`
first; Compose refuses to start without them and nothing has a default
password.

```bash
docker compose up --build
```

```bash
docker compose exec web python manage.py seed_demo
```

The app is at http://localhost:8000. For anything other than local use, serve
it over HTTPS and set `DJANGO_SECURE_COOKIES=true`, `DJANGO_ALLOWED_HOSTS` and
`DJANGO_CSRF_TRUSTED_ORIGINS`.

Optional services are behind profiles:

```bash
docker compose --profile kestra up
```

Kestra (http://localhost:8080) runs
`infra/kestra/cloudcost_daily_pipeline.yml`, which calls `run_pipeline` daily
at 06:00 UTC. Import the flow in the Kestra UI. The profile mounts the Docker
socket so the flow can start the app image; only enable it on a machine where
that is acceptable.

```bash
docker compose --profile grafana up
```

Grafana (http://localhost:3000) needs `GRAFANA_ADMIN_PASSWORD` in `.env` and is
provisioned with the PostgreSQL datasource. It reads the database directly and
so sees every user's rows: treat it as an operator tool and give it a
read-only database role before using it beyond your own machine.

## Deploy to Render

The repository includes a Render Blueprint (`render.yaml`) that creates one free
web service and one free PostgreSQL database. No secrets are stored in the repo.

1. Push this repository to GitHub.
2. In the Render dashboard choose **New > Blueprint** and pick the repository.
3. When asked, type a value for `DEMO_USER_PASSWORD` (the password of the `demo`
   sample user). `DJANGO_SECRET_KEY` is generated by Render and `DATABASE_URL`
   is wired to the database automatically.
4. Click **Apply**. The build runs `build.sh`: install, `collectstatic`,
   `migrate`, and (first deploy only) `seed_demo` with the simulated sample data.
5. Open the service's `*.onrender.com` URL and sign in as `demo`.

Free-tier notes: the web service sleeps when idle, so the first request after a
pause takes up to a minute; the free PostgreSQL database expires after a limited
period (Render shows the date). Only simulated sample data is loaded - no cloud
credentials are needed and no cloud resources are created.

## Infracost and CloudQuery

Both are optional; sample outputs are in `sample_data/` so the features work
without installing either.

- **Infracost.** `infra/terraform/main.tf` is a sample plan for estimation
  only. Do not `terraform apply` it: that would create paid resources.

  ```bash
  infracost breakdown --path infra/terraform --format json --out-file infracost.json
  ```

  Upload `infracost.json` on the Estimates page.

- **CloudQuery.** `infra/cloudquery/aws.yml` syncs a read-only inventory to
  JSON files. Use an identity with read-only access through the normal AWS
  credential chain, pin the plugin versions (the file has placeholders), then:

  ```bash
  cloudquery sync infra/cloudquery/aws.yml
  ```

  Upload the files from `cloudquery-output/` on the Resources page.

## Security notes

- Secrets come from environment variables (`.env` is git-ignored). Never commit
  keys, cloud credentials or passwords.
- The app stores no cloud credentials and makes no calls to cloud providers.
- Recommendations are advice for a person to review; nothing is applied
  automatically.
- Uploads are limited to 10 MB, checked by type, parsed in memory and not
  stored. Row errors are kept per import, not written to logs.
- Every query is scoped to the signed-in user.

## Limitations

- Billing data arrives by CSV upload; there is no live billing API connection.
- Exchange rates are a static table.
- The forecast uses simple baselines and assumes recent patterns continue. It
  does not know about planned launches, migrations or price changes.
- Savings figures are estimates from observed spend, not quotes.
- The Dockerfile, Compose file, Kestra flow, Grafana provisioning, CloudQuery
  config, Terraform sample and GitHub Actions workflow are written to each
  tool's documented format but have not been run end to end in this build.

## Layout

```
config/            settings, URLs
accounts/          sign-up and login
cloud_accounts/    provider accounts
ingestion/         CSV adapters and import jobs
billing/           normalized billing records, exchange rates
resources/         CloudQuery inventory
estimates/         Infracost estimates
analytics/         DuckDB/Pandas engine, forecast, pipeline, dashboard
alerts/            anomaly detection
recommendations/   rules and optional Gemini explanation
reports/           CSV and summary exports
sample_data/       sample billing CSVs, inventory, Infracost output
infra/             Kestra, Grafana, CloudQuery, Terraform sample
```
