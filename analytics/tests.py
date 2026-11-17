from datetime import date, timedelta

import pandas as pd

from analytics.engine import (
    UNASSIGNED,
    Filters,
    by_dimension,
    daily_totals,
    load_frame,
    service_daily_series,
    top_resources,
    total,
)
from analytics.forecasting import HORIZON_DAYS, build_forecast, run_forecast
from analytics.models import CostForecast
from ingestion.tests import AWS_HEADER, ImportTestCase, aws_row, csv_text


def daily_rows(days, cost_for_day, first=date(2026, 6, 1), **kwargs):
    rows = []
    for offset in range(days):
        day = first + timedelta(days=offset)
        rows.append(
            aws_row(
                cost=str(cost_for_day(offset)),
                start=f"{day.isoformat()}T00:00:00Z",
                end=f"{(day + timedelta(days=1)).isoformat()}T00:00:00Z",
                **kwargs,
            )
        )
    return rows


class EmptyDataTests(ImportTestCase):
    def test_no_records_gives_zero_everywhere(self):
        data = load_frame(self.user)
        self.assertTrue(data.empty)
        self.assertEqual(total(data), 0.0)
        self.assertEqual(by_dimension(data, "provider"), [])
        self.assertEqual(top_resources(data), [])
        self.assertEqual(len(daily_totals(data)), 0)
        self.assertEqual(service_daily_series(data), {})


class CurrencyTests(ImportTestCase):
    def test_foreign_currency_is_converted_to_usd(self):
        self.run_csv(csv_text(AWS_HEADER, aws_row(cost="100", currency="EUR")))
        self.assertAlmostEqual(total(load_frame(self.user)), 108.0, places=2)

    def test_mixed_currencies_are_never_summed_raw(self):
        self.run_csv(
            csv_text(
                AWS_HEADER,
                aws_row(cost="100", currency="USD", resource="i-usd"),
                aws_row(cost="100", currency="EUR", resource="i-eur"),
            )
        )
        self.assertAlmostEqual(total(load_frame(self.user)), 208.0, places=2)

    def test_currency_without_rate_is_excluded_and_reported(self):
        self.run_csv(
            csv_text(
                AWS_HEADER,
                aws_row(cost="50", currency="USD", resource="i-usd"),
                aws_row(cost="999", currency="XYZ", resource="i-xyz"),
            )
        )
        data = load_frame(self.user)
        self.assertAlmostEqual(total(data), 50.0, places=2)
        self.assertEqual(data.unconverted, {"XYZ": 1})


class BreakdownTests(ImportTestCase):
    def setUp(self):
        super().setUp()
        self.run_csv(
            csv_text(
                AWS_HEADER,
                aws_row(cost="30", service="AmazonEC2", resource="i-1"),
                aws_row(cost="70", service="AmazonS3", resource=""),
                aws_row(
                    cost="5", service="AmazonRDS", resource="db-1",
                    start="2026-07-25T00:00:00Z", end="2026-07-26T00:00:00Z",
                ),
            )
        )

    def test_by_dimension_is_sorted_by_cost(self):
        rows = by_dimension(load_frame(self.user), "service")
        self.assertEqual([r["label"] for r in rows], ["AmazonS3", "AmazonEC2", "AmazonRDS"])
        self.assertEqual(rows[0]["cost"], 70.0)

    def test_blank_dimension_is_labelled_unassigned(self):
        labels = [r["label"] for r in by_dimension(load_frame(self.user), "resource_id")]
        self.assertIn(UNASSIGNED, labels)

    def test_unknown_dimension_is_rejected(self):
        with self.assertRaises(ValueError):
            by_dimension(load_frame(self.user), "cost_usd; DROP TABLE billing")

    def test_top_resources_skip_blank_ids(self):
        ids = [r["resource_id"] for r in top_resources(load_frame(self.user))]
        self.assertEqual(ids, ["i-1", "db-1"])

    def test_filters_narrow_the_data(self):
        self.assertAlmostEqual(
            total(load_frame(self.user, Filters(service="AmazonS3"))), 70.0, places=2
        )
        self.assertAlmostEqual(
            total(load_frame(self.user, Filters(provider="azure"))), 0.0, places=2
        )
        ranged = Filters(start=date(2026, 7, 25), end=date(2026, 7, 25))
        self.assertAlmostEqual(total(load_frame(self.user, ranged)), 5.0, places=2)

    def test_daily_totals_fill_missing_days_with_zero(self):
        series = daily_totals(load_frame(self.user))
        self.assertEqual(len(series), 6)  # 20 July to 25 July inclusive
        self.assertAlmostEqual(float(series.iloc[0]), 100.0, places=2)
        self.assertEqual(float(series.iloc[2]), 0.0)


class ForecastTests(ImportTestCase):
    def series(self, days):
        index = pd.date_range("2026-06-01", periods=days, freq="D")
        return pd.Series([100.0 + (i % 7) * 3 for i in range(days)], index=index)

    def test_insufficient_history_gives_no_forecast(self):
        result = build_forecast(self.series(10))
        self.assertEqual(result["status"], "insufficient_history")
        self.assertEqual(result["history_days"], 10)
        self.assertIn("14 days", result["message"])

    def test_empty_history_gives_no_forecast(self):
        result = build_forecast(pd.Series(dtype=float))
        self.assertEqual(result["status"], "insufficient_history")

    def test_forecast_has_band_and_backtest(self):
        result = build_forecast(self.series(45))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["daily"]), HORIZON_DAYS)
        self.assertLessEqual(result["lower"], result["predicted"])
        self.assertLessEqual(result["predicted"], result["upper"])
        self.assertGreaterEqual(result["lower"], 0)
        for point in result["daily"]:
            self.assertLessEqual(point["lower"], point["predicted"])
            self.assertLessEqual(point["predicted"], point["upper"])
        self.assertIn(result["model_name"], result["scores"])
        self.assertTrue(result["notes"])
        # roughly 30 days at about 109 USD a day
        self.assertGreater(result["predicted"], 2500)
        self.assertLess(result["predicted"], 4000)

    def test_run_forecast_stores_nothing_without_enough_history(self):
        self.run_csv(csv_text(AWS_HEADER, *daily_rows(5, lambda i: 10 + i)))
        result = run_forecast(self.user)
        self.assertEqual(result["status"], "insufficient_history")
        self.assertFalse(CostForecast.objects.filter(user=self.user).exists())

    def test_run_forecast_stores_one_row_and_replaces_it(self):
        self.run_csv(csv_text(AWS_HEADER, *daily_rows(30, lambda i: 100 + i % 5)))
        run_forecast(self.user)
        run_forecast(self.user)
        self.assertEqual(CostForecast.objects.filter(user=self.user).count(), 1)
