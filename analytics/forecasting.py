"""Baseline cost forecasting.

Three simple, explainable models are compared with rolling-origin backtests on
the user's own history; the one with the lowest mean absolute error is used.
The uncertainty band comes from the backtest errors. This is a planning aid,
not a prediction of the invoice.
"""
from datetime import timedelta
from decimal import Decimal

import numpy as np
import pandas as pd

from .engine import daily_totals, load_frame
from .models import CostForecast

MIN_HISTORY_DAYS = 14
HORIZON_DAYS = 30
BACKTEST_DAYS = 7
MAX_FOLDS = 3
Z95 = 1.96


def _linear_trend(history, horizon):
    values = history.to_numpy(dtype=float)[-60:]
    x = np.arange(len(values))
    slope, intercept = np.polyfit(x, values, 1)
    future = np.arange(len(values), len(values) + horizon)
    return slope * future + intercept


def _moving_average(history, horizon):
    return np.full(horizon, float(history.to_numpy(dtype=float)[-7:].mean()))


def _weekday_average(history, horizon):
    recent = history[-28:]
    by_weekday = recent.groupby(recent.index.dayofweek).mean()
    overall = float(recent.mean())
    start = history.index[-1] + timedelta(days=1)
    days = pd.date_range(start, periods=horizon, freq="D")
    return np.array([float(by_weekday.get(d.dayofweek, overall)) for d in days])


MODELS = {
    "linear_trend": _linear_trend,
    "moving_average_7d": _moving_average,
    "weekday_average_4w": _weekday_average,
}

MODEL_LABELS = {
    "linear_trend": "Linear trend (last 60 days)",
    "moving_average_7d": "7-day moving average",
    "weekday_average_4w": "Day-of-week average (last 4 weeks)",
}


def backtest(history, model):
    """Rolling-origin backtest: returns the list of (prediction - actual) errors."""
    errors = []
    n = len(history)
    for fold in range(MAX_FOLDS):
        cutoff = n - BACKTEST_DAYS * (fold + 1)
        if cutoff < 7:
            break
        train = history[:cutoff]
        actual = history[cutoff:cutoff + BACKTEST_DAYS].to_numpy(dtype=float)
        predicted = np.clip(model(train, BACKTEST_DAYS), 0, None)
        errors.extend((predicted - actual).tolist())
    return errors


def build_forecast(history):
    """Pure function: history is a zero-filled daily Series. Returns a dict."""
    days = len(history)
    if days < MIN_HISTORY_DAYS:
        return {
            "status": "insufficient_history",
            "history_days": days,
            "message": (
                f"Only {days} day(s) of billing history are available. At least "
                f"{MIN_HISTORY_DAYS} days are needed before a forecast is shown."
            ),
        }
    scores = {}
    for name, model in MODELS.items():
        errors = backtest(history, model)
        if errors:
            arr = np.array(errors)
            scores[name] = (float(np.abs(arr).mean()), float(np.sqrt((arr ** 2).mean())))
    if scores:
        best = min(scores, key=lambda k: scores[k][0])
        mae, sigma = scores[best]
    else:  # not reachable with MIN_HISTORY_DAYS >= 14, kept as a safe fallback
        best, mae, sigma = "moving_average_7d", None, float(history.std())

    predicted = np.clip(MODELS[best](history, HORIZON_DAYS), 0, None)
    start = history.index[-1] + timedelta(days=1)
    dates = pd.date_range(start, periods=HORIZON_DAYS, freq="D")
    daily = [
        {
            "date": d.strftime("%Y-%m-%d"),
            "predicted": round(float(p), 2),
            "lower": round(max(float(p) - Z95 * sigma, 0.0), 2),
            "upper": round(float(p) + Z95 * sigma, 2),
        }
        for d, p in zip(dates, predicted)
    ]
    total = float(predicted.sum())
    spread = Z95 * sigma * (HORIZON_DAYS ** 0.5)
    notes = [
        f"Model: {MODEL_LABELS[best]}, chosen because it had the lowest mean absolute "
        f"error in backtests on your own history.",
        "The range is an approximate 95% band derived from backtest errors. The total "
        "band assumes daily errors are independent, so it is likely too narrow if "
        "errors persist from day to day.",
        "The forecast only extrapolates past spend. It does not know about planned "
        "launches, migrations, price changes, credits, or commitments.",
    ]
    if days < 60:
        notes.append(
            f"Only {days} days of history are available, so monthly seasonality cannot be learned."
        )
    return {
        "status": "ok",
        "history_days": days,
        "model_name": best,
        "model_label": MODEL_LABELS[best],
        "backtest_mae": None if mae is None else round(mae, 2),
        "scores": {k: round(v[0], 2) for k, v in scores.items()},
        "predicted": round(total, 2),
        "lower": round(max(total - spread, 0.0), 2),
        "upper": round(total + spread, 2),
        "period": f"{dates[0]:%Y-%m-%d} to {dates[-1]:%Y-%m-%d}",
        "daily": daily,
        "notes": notes,
    }


def _money(value):
    return Decimal(f"{value:.2f}")


def run_forecast(user):
    """Recompute and store the user's forecast (replacing earlier ones)."""
    history = daily_totals(load_frame(user))
    result = build_forecast(history)
    CostForecast.objects.filter(user=user).delete()
    if result["status"] != "ok":
        return result
    CostForecast.objects.create(
        user=user,
        forecast_period=result["period"],
        predicted_cost=_money(result["predicted"]),
        lower_bound=_money(result["lower"]),
        upper_bound=_money(result["upper"]),
        currency="USD",
        model_name=result["model_name"],
        daily=result["daily"],
        history_days=result["history_days"],
        backtest_mae=None if result["backtest_mae"] is None else _money(result["backtest_mae"]),
        notes="\n".join(result["notes"]),
    )
    return result
