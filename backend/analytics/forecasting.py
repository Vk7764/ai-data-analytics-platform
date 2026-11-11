# backend/analytics/forecasting.py
import pandas as pd
import numpy as np
from typing import Dict, Any


class Forecaster:
    """
    Generates a simple trend-based forecast for a numeric column over time,
    using linear regression (implemented with plain numpy, no scikit-learn/scipy,
    to avoid environments where those compiled dependencies are blocked).
    Always returns an uncertainty range alongside the prediction, since a
    single predicted number can be misleading.
    """

    @staticmethod
    def forecast(
        df: pd.DataFrame,
        date_column: str,
        value_column: str,
        periods: int = 3,
    ) -> Dict[str, Any]:
        total_input_rows = int(len(df))
        working_df = df[[date_column, value_column]].dropna().copy()
        rows_dropped_missing = total_input_rows - int(len(working_df))

        try:
            working_df[date_column] = pd.to_datetime(working_df[date_column], errors="coerce", format="mixed")
        except (TypeError, ValueError):
            working_df[date_column] = pd.to_datetime(working_df[date_column], errors="coerce")
        working_df = working_df.dropna(subset=[date_column])

        rows_with_valid_date = int(len(working_df))

        # Aggregate to one point per calendar day (sum), so several rows on the same date do not distort the trend.
        working_df[value_column] = pd.to_numeric(working_df[value_column], errors="coerce")
        working_df = working_df.dropna(subset=[value_column])
        rows_used_before_aggregation = int(len(working_df))
        working_df[date_column] = working_df[date_column].dt.normalize()
        working_df = (
            working_df.groupby(date_column, as_index=False)[value_column]
            .sum()
            .sort_values(date_column)
            .reset_index(drop=True)
        )

        if len(working_df) < 3:
            raise ValueError("Not enough valid data points to generate a forecast (need at least 3).")

        # Figure out the typical gap between data points (daily, monthly, etc.)
        try:
            inferred_freq = pd.infer_freq(working_df[date_column])
        except (ValueError, TypeError):
            inferred_freq = None
        avg_gap = working_df[date_column].diff().dropna().median()

        # Regress on real elapsed days so uneven date gaps are respected.
        first_date = working_df[date_column].iloc[0]
        x = (working_df[date_column] - first_date).dt.days.values.astype(float)
        y = working_df[value_column].values.astype(float)

        # Simple linear regression (least squares) using numpy only: y = slope * x + intercept
        slope, intercept = np.polyfit(x, y, 1)

        # Estimate uncertainty from residuals (how far actual points are from the trend line)
        predictions_on_history = slope * x + intercept
        residuals = y - predictions_on_history
        residual_std = float(np.std(residuals)) if len(residuals) > 1 else 0.0

        # Build future dates first, then place them on the same elapsed-days axis used for the fit.
        last_date = working_df[date_column].iloc[-1]
        if inferred_freq:
            future_dates = pd.date_range(start=last_date, periods=periods + 1, freq=inferred_freq)[1:]
        else:
            future_dates = pd.DatetimeIndex([last_date + (avg_gap * i) for i in range(1, periods + 1)])
        future_indices = np.array((future_dates - first_date).days, dtype=float)
        future_predictions = slope * future_indices + intercept

        forecast_points = []
        for date, pred in zip(future_dates, future_predictions):
            forecast_points.append({
                "date": str(pd.Timestamp(date).date()),
                "predicted_value": round(float(pred), 2),
                "lower_bound": round(float(pred - 1.96 * residual_std), 2),
                "upper_bound": round(float(pred + 1.96 * residual_std), 2),
            })

        historical_points = [
            {"date": str(row[date_column].date()), "actual_value": round(float(row[value_column]), 2)}
            for _, row in working_df.iterrows()
        ]

        trend_direction = "increasing" if slope > 0 else ("decreasing" if slope < 0 else "flat")

        return {
            "date_column": date_column,
            "value_column": value_column,
            "trend_direction": trend_direction,
            "historical": historical_points,
            "forecast": forecast_points,
            "methodology": {
                "date_column": date_column,
                "value_column": value_column,
                "date_grain": "day",
                "aggregation": "sum of the value column per calendar day",
                "model": "Ordinary least-squares linear regression (degree 1) of the daily value on elapsed days since the first date",
                "slope_per_day": (
                    round(float(locals().get("slope", 0.0)), 6)
                    if bool(np.isfinite(locals().get("slope", 0.0)))
                    else None
                ),
                "intercept": (
                    round(float(locals().get("intercept", 0.0)), 6)
                    if bool(np.isfinite(locals().get("intercept", 0.0)))
                    else None
                ),
                "periods_requested": int(periods),
                "future_date_rule": (
                    f"Future dates continue the detected frequency '{inferred_freq}'."
                    if inferred_freq
                    else "Future dates are spaced by the median gap between observed dates."
                ),
                "inferred_frequency": inferred_freq,
                "median_gap_between_dates": str(locals().get("avg_gap", "")),
                "uncertainty": {
                    "lower_upper_bound_rule": "prediction +/- 1.96 x standard deviation of the in-sample residuals",
                    "residual_std": (
                        round(float(locals().get("residual_std", 0.0)), 4)
                        if bool(np.isfinite(locals().get("residual_std", 0.0)))
                        else None
                    ),
                    "note": "An approximate band that assumes constant, roughly normal residuals; it is not a full prediction interval.",
                },
                "rows": {
                    "total_in_dataset": total_input_rows,
                    "used_before_daily_aggregation": rows_used_before_aggregation,
                    "daily_points_in_model": int(len(working_df)),
                },
                "missing_value_handling": {
                    "rows_dropped_missing_date_or_value": int(rows_dropped_missing),
                    "rows_dropped_unreadable_date": max(
                        0,
                        int((total_input_rows - rows_dropped_missing) - rows_with_valid_date),
                    ),
                    "rows_dropped_non_numeric_value": max(
                        0,
                        int(rows_with_valid_date - rows_used_before_aggregation),
                    ),
                    "imputation": "none; days without data are not filled, the fit uses real elapsed days",
                },
                "outlier_handling": "none; outliers are included in the daily sums and in the fit",
                "smoothing": {"applied": False, "moving_average_window": None},
                "limitations": [
                    "A straight-line trend only: seasonality, holidays and sudden shifts are not modelled.",
                    "Predictions far beyond the observed date range are increasingly unreliable.",
                    "The sum aggregation assumes the value is additive across rows (for example sales, not prices or rates).",
                ],
            },
        }