import pandas as pd

from alerts.detection import detect_for_user, detect_in_series
from alerts.models import CostAnomaly
from analytics.tests import daily_rows
from ingestion.tests import AWS_HEADER, ImportTestCase, aws_row, csv_text  # noqa: F401


def series(values):
    index = pd.date_range("2026-06-01", periods=len(values), freq="D")
    return pd.Series([float(v) for v in values], index=index)


STABLE = [100, 102, 98, 101, 99, 103, 97, 100, 102, 98, 101, 99, 103, 97, 100, 101]


class DetectInSeriesTests(ImportTestCase):
    def test_stable_spend_is_not_flagged(self):
        self.assertEqual(detect_in_series(series(STABLE)), [])

    def test_spike_is_flagged_with_its_numbers(self):
        hits = detect_in_series(series(STABLE + [400]))
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(pd.Timestamp(hit["day"]).date().isoformat(), "2026-06-17")
        self.assertAlmostEqual(hit["observed"], 400.0, places=2)
        self.assertAlmostEqual(hit["expected"], 100.0, delta=2)
        self.assertGreater(hit["deviation"], 290)
        self.assertGreater(hit["pct"], 250)
        self.assertIn(hit["method"], {"rolling_zscore", "pct_threshold"})

    def test_spike_does_not_poison_the_baseline(self):
        # the day after a spike is back to normal and must not be flagged
        hits = detect_in_series(series(STABLE + [400, 100, 101]))
        self.assertEqual(len(hits), 1)

    def test_small_absolute_change_is_ignored(self):
        values = [1.0] * 14 + [3.0]  # +200% but only 2 USD
        self.assertEqual(detect_in_series(series(values)), [])

    def test_too_little_history_is_not_flagged(self):
        self.assertEqual(detect_in_series(series([100, 100, 100, 900])), [])
        self.assertEqual(detect_in_series(series([])), [])

    def test_new_spend_after_zero_baseline(self):
        hits = detect_in_series(series([0] * 10 + [80]))
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["method"], "new_spend")


class DetectForUserTests(ImportTestCase):
    def load(self):
        costs = STABLE + [400]
        self.run_csv(csv_text(AWS_HEADER, *daily_rows(len(costs), lambda i: costs[i])))

    def test_anomaly_is_stored_with_an_explanation(self):
        self.load()
        self.assertEqual(detect_for_user(self.user), 1)
        anomaly = CostAnomaly.objects.get(user=self.user)
        self.assertEqual(anomaly.provider, "aws")
        self.assertEqual(anomaly.service, "AmazonEC2")
        self.assertEqual(anomaly.usage_date.isoformat(), "2026-06-17")
        self.assertEqual(anomaly.status, "open")
        self.assertIn("400", anomaly.explanation)
        lowered = anomaly.explanation.lower()
        self.assertNotIn("fraud", lowered)

    def test_rerun_does_not_duplicate_and_keeps_review_status(self):
        self.load()
        detect_for_user(self.user)
        CostAnomaly.objects.filter(user=self.user).update(status="acknowledged")
        detect_for_user(self.user)
        self.assertEqual(CostAnomaly.objects.filter(user=self.user).count(), 1)
        self.assertEqual(CostAnomaly.objects.get(user=self.user).status, "acknowledged")

    def test_stable_spend_stores_nothing(self):
        self.run_csv(csv_text(AWS_HEADER, *daily_rows(len(STABLE), lambda i: STABLE[i])))
        self.assertEqual(detect_for_user(self.user), 0)
        self.assertFalse(CostAnomaly.objects.exists())

    def test_no_data_is_fine(self):
        self.assertEqual(detect_for_user(self.user), 0)
