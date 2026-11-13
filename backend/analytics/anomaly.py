# backend/analytics/anomaly.py
import pandas as pd
import numpy as np
from typing import List, Dict, Any
from backend.visualization.charts import ChartEngine


class AnomalyDetector:
    """
    Detects unusual patterns in the data:
    1. Numeric outliers within a single column (IQR method).
    2. Category-wise anomalies (a group whose average is far from the overall average).
    """

    @staticmethod
    def detect_numeric_outliers(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Flags individual rows that are outliers in any numeric column.
        """
        anomalies = []
        numeric_cols = df.select_dtypes(include="number").columns.tolist()

        for col in numeric_cols:
            series = df[col].dropna()
            if len(series) < 4:
                continue

            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr

            outlier_mask = (df[col] < lower_bound) | (df[col] > upper_bound)
            outlier_rows = df[outlier_mask]

            for idx, row in outlier_rows.iterrows():
                anomalies.append({
                    "type": "numeric_outlier",
                    "column": col,
                    "row_index": int(idx),
                    "value": float(row[col]),
                    "expected_range": [round(float(lower_bound), 2), round(float(upper_bound), 2)],
                })

        return anomalies

    @staticmethod
    def detect_category_anomalies(
        df: pd.DataFrame,
        group_column: str = None,
        value_column: str = None,
        z_threshold: float = 1.5,
        method: str = "zscore",
        iqr_scale: float = 1.5,
    ) -> List[Dict[str, Any]]:
        """
        Groups the data by a categorical column and flags groups whose average
        (for a numeric column) is far from the overall average across groups.

        If group_column/value_column are not given, auto-picks the first
        categorical column and first non-identifier numeric column.
        """
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        categorical_cols = df.select_dtypes(exclude="number").columns.tolist()

        if not group_column:
            row_count = len(df)
            group_column = None
            for candidate in categorical_cols:
                if ChartEngine.is_identifier_name(candidate):
                    continue
                distinct = df[candidate].nunique(dropna=True)
                if 2 <= distinct <= 50 and row_count and distinct / row_count <= 0.5:
                    group_column = candidate
                    break
        if not value_column:
            # prefer a numeric column that isn't an obvious identifier
            non_id_candidates = [c for c in numeric_cols if not ChartEngine.is_identifier_name(c)]
            value_column = non_id_candidates[0] if non_id_candidates else (numeric_cols[0] if numeric_cols else None)

        if not group_column or not value_column:
            return []

        group_means = df.groupby(group_column)[value_column].mean()
        if len(group_means) < 2:
            return []  # need at least 2 groups to compare

        overall_mean = group_means.mean()
        overall_std = group_means.std()

        anomalies = []
        if overall_std == 0 or np.isnan(overall_std):
            return []

        group_q1 = group_means.quantile(0.25)
        group_q3 = group_means.quantile(0.75)
        group_iqr = group_q3 - group_q1

        # If the group means are degenerate, IQR bounds are not meaningful; fall back to z-score.
        if not (group_iqr > 0):
            method = "zscore"
        else:
            iqr_lower = group_q1 - iqr_scale * group_iqr
            iqr_upper = group_q3 + iqr_scale * group_iqr

        for group_value, group_mean in group_means.items():
            z_score = (group_mean - overall_mean) / overall_std
            if method == "iqr":
                is_anomalous = group_mean < iqr_lower or group_mean > iqr_upper
            else:
                is_anomalous = abs(z_score) >= z_threshold
            if is_anomalous:
                anomalies.append({
                    "type": "category_anomaly",
                    "group_column": group_column,
                    "group_value": str(group_value),
                    "value_column": value_column,
                    "group_average": round(float(group_mean), 2),
                    "overall_average": round(float(overall_mean), 2),
                    "z_score": round(float(z_score), 2),
                    "direction": "above" if z_score > 0 else "below",
                })

        return anomalies

    @staticmethod
    def detect(df: pd.DataFrame, z_threshold: float = 2.5, method: str = "zscore") -> Dict[str, Any]:
        threshold = max(1.5, min(5.0, float(z_threshold)))
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        numeric_outliers: List[Dict[str, Any]] = []

        for col in numeric_cols:
            series = df[col].dropna()
            if len(series) < 4:
                continue

            if method == "iqr":
                q1 = series.quantile(0.25)
                q3 = series.quantile(0.75)
                iqr = q3 - q1
                scale = max(1.0, threshold - 1.0)
                lower = q1 - scale * iqr
                upper = q3 + scale * iqr
                denom = iqr if iqr > 0 else 1.0
                for idx, val in series.items():
                    if val < lower or val > upper:
                        nearest = lower if val < lower else upper
                        score_val = round(float(abs(val - nearest) / denom), 2)
                        numeric_outliers.append({
                            "type": "numeric_outlier",
                            "column": col,
                            "row_index": int(idx),
                            "value": float(val),
                            "z_score": score_val,
                            "score": score_val,
                            "direction": "below" if val < lower else "above",
                            "expected_range": [round(float(lower), 2), round(float(upper), 2)],
                        })
            else:
                std = series.std()
                if std == 0 or np.isnan(std):
                    continue
                mean = series.mean()
                z = (series - mean) / std
                expected = [round(float(mean - threshold * std), 2), round(float(mean + threshold * std), 2)]
                for idx in z[z.abs() >= threshold].index:
                    score_val = round(float(z[idx]), 2)
                    numeric_outliers.append({
                        "type": "numeric_outlier",
                        "column": col,
                        "row_index": int(idx),
                        "value": float(series[idx]),
                        "z_score": score_val,
                        "score": score_val,
                        "direction": "above" if z[idx] > 0 else "below",
                        "expected_range": expected,
                    })

        return {
            "method": method,
            "threshold": threshold,
            "numeric_outliers": numeric_outliers,
            # The selected sensitivity applies here too. Group-mean z-scores are bounded by the number of
            # groups, so the numeric threshold is scaled (2.5 -> 1.5) to preserve the previous default behavior.
            "category_anomalies": AnomalyDetector.detect_category_anomalies(
                df,
                z_threshold=threshold * 0.6,
                method=method,
                iqr_scale=max(1.0, threshold - 1.0),
            ),
        }

    @staticmethod
    def describe_methodology(df: pd.DataFrame, method: str = "zscore", z_threshold: float = 2.5) -> Dict[str, Any]:
        """
        Describes how detect() treats this dataset for the given controls. It mirrors detect()'s selection
        rules for reporting only and does not influence any detection result.
        """
        effective_method = "iqr" if method == "iqr" else "zscore"

        try:
            requested_threshold = float(z_threshold)
        except (TypeError, ValueError):
            requested_threshold = 2.5

        if requested_threshold != requested_threshold or requested_threshold in (float("inf"), float("-inf")):
            requested_threshold = 2.5

        threshold = max(1.5, min(5.0, requested_threshold))
        iqr_scale = max(1.0, threshold - 1.0)
        category_z = threshold * 0.6

        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        evaluated = []
        skipped_few = []
        skipped_constant = []

        for col in numeric_cols:
            series = df[col].dropna()
            if len(series) < 4:
                skipped_few.append(col)
                continue

            if effective_method == "zscore":
                std = series.std()
                if std == 0 or pd.isna(std):
                    skipped_constant.append(col)
                    continue

            evaluated.append(col)

        row_count = len(df)
        categorical_cols = df.select_dtypes(exclude="number").columns.tolist()

        group_column = None
        for candidate in categorical_cols:
            if ChartEngine.is_identifier_name(candidate):
                continue
            distinct = df[candidate].nunique(dropna=True)
            if 2 <= distinct <= 50 and row_count and distinct / row_count <= 0.5:
                group_column = candidate
                break

        non_id_numeric = [c for c in numeric_cols if not ChartEngine.is_identifier_name(c)]
        value_column = non_id_numeric[0] if non_id_numeric else (numeric_cols[0] if numeric_cols else None)

        if effective_method == "zscore":
            numeric_rule = f"A value is flagged when |value - column mean| / column standard deviation >= {threshold}."
            category_rule = (
                f"A group is flagged when |group mean - mean of group means| / standard deviation of group means >= {round(category_z, 3)}."
            )
        else:
            numeric_rule = (
                f"A value is flagged when it lies more than {iqr_scale} x IQR below the first quartile or above the third quartile. "
                "The reported score is the distance to the nearest bound divided by the IQR (1 if the IQR is 0)."
            )
            category_rule = (
                f"A group is flagged when its mean lies more than {iqr_scale} x IQR (of the group means) beyond the quartiles of the group means."
            )

        return {
            "method": effective_method,
            "requested_threshold": requested_threshold,
            "applied_threshold": threshold,
            "threshold_note": "The requested threshold is limited to the range 1.5 to 5.0.",
            "sensitivity": {
                "numeric_zscore_threshold": threshold,
                "numeric_iqr_scale": iqr_scale,
                "category_zscore_threshold": round(category_z, 3),
                "category_iqr_scale": iqr_scale,
                "category_threshold_note": "Group-mean z-scores are bounded by the number of groups, so the numeric threshold is scaled by 0.6 for category checks.",
            },
            "numeric_outliers": {
                "rule": numeric_rule,
                "columns_evaluated": evaluated,
                "columns_skipped_fewer_than_4_values": skipped_few,
                "columns_skipped_constant_values": skipped_constant,
                "identifier_columns": "not excluded; ID-like numeric columns are evaluated like any other numeric column",
            },
            "category_anomalies": {
                "rule": category_rule,
                "grouping_column": group_column,
                "value_column": value_column,
                "grouping_rule": "First non-identifier text column with 2 to 50 distinct values and at most 50% distinct values per row.",
                "group_statistic": "mean of the value column per group (unweighted by group size)",
                "minimum_groups": 2,
            },
            "missing_value_handling": "Missing values are ignored in every statistic and are never imputed.",
            "outlier_handling": "Detected outliers are only reported; no values are changed or removed.",
            "limitations": [
                "Statistical outliers are not necessarily errors; review them in context.",
                "Z-score detection assumes a roughly bell-shaped distribution; the IQR method is more robust for skewed data.",
                "Category checks use only one automatically chosen grouping column and one value column.",
            ],
        }

    @staticmethod
    def detect_all(df: pd.DataFrame) -> Dict[str, Any]:
        return {
            "numeric_outliers": AnomalyDetector.detect_numeric_outliers(df),
            "category_anomalies": AnomalyDetector.detect_category_anomalies(df),
        }