# backend/analytics/statistics.py
import pandas as pd
from typing import List, Dict, Any, Optional
from backend.visualization.charts import ChartEngine


class VarianceAnalyzer:
    """
    Analyzes how much each categorical dimension (e.g. Region, Product, Month)
    explains the variation in a numeric metric (e.g. Sales).
    This is the core engine behind Root Cause Analysis.
    """

    @staticmethod
    def _is_identifier_column(df: pd.DataFrame, column: str) -> bool:
        return ChartEngine.is_identifier_name(column)

    @staticmethod
    def describe_methodology(
        df: pd.DataFrame,
        metric_column: str,
        dimension_columns: Optional[List[str]] = None,
        exclude_columns: Optional[List[str]] = None,
        top_n: int = 3,
    ) -> Dict[str, Any]:
        """
        Describes which dimensions analyze_dimensions() evaluates or skips, and how. It mirrors that
        method's selection rules for reporting only and does not influence any result.
        """
        metric = pd.to_numeric(df[metric_column], errors="coerce")
        auto_selected = not dimension_columns

        if auto_selected:
            candidates = df.select_dtypes(exclude="number").columns.tolist()
        else:
            candidates = list(dimension_columns)

        excluded = set(exclude_columns or [])
        evaluated = []
        skipped = []

        for dim in candidates:
            if dim in excluded:
                skipped.append({"dimension": dim, "reason": "excluded by the user"})
                continue

            if dim not in df.columns:
                skipped.append({"dimension": dim, "reason": "column not found"})
                continue

            combined = pd.DataFrame({"d": df[dim], "m": metric}).dropna()
            groups = int(combined["d"].nunique()) if not combined.empty else 0

            if groups < 2:
                skipped.append({"dimension": dim, "reason": "fewer than 2 groups with data"})
            elif auto_selected and (groups > 50 or groups / len(combined) > 0.5):
                skipped.append({
                    "dimension": dim,
                    "reason": "near-unique values (more than 50 groups or more than half of the rows)",
                })
            else:
                evaluated.append(dim)

        return {
            "metric_column": metric_column,
            "method": "Share of the metric's variation explained by each dimension (eta-squared style: between-group variation divided by total variation)",
            "rows": {
                "total_in_dataset": int(len(df)),
                "used_with_numeric_metric": int(metric.notna().sum()),
            },
            "dimension_selection": {
                "mode": "automatic" if auto_selected else "user-selected",
                "automatic_rule": "All non-numeric columns; near-unique columns are skipped during automatic selection.",
                "requested_dimensions": None if auto_selected else list(dimension_columns),
                "excluded_by_user": sorted(excluded),
                "dimensions_evaluated": evaluated,
                "dimensions_skipped": skipped,
                "near_unique_rule_applies_to": "automatic selection only",
            },
            "grouping_rule": "Rows are grouped by each dimension's distinct values; groups are compared by their mean metric value.",
            "highest_lowest_group_rule": "By mean metric value within the dimension.",
            "ranking": f"Dimensions are ranked by variance explained and only the top {top_n} are returned.",
            "missing_value_handling": "Rows with a missing or non-numeric metric (or a missing dimension value) are excluded; nothing is imputed.",
            "outlier_handling": "none; outliers are included in the means and variances",
            "date_grain": None,
            "aggregation": "mean per group",
            "limitations": [
                "Correlation is not causation: a dimension that explains variation is a probable cause, not a proven one.",
                "Dimensions are analyzed one at a time; overlapping dimensions can explain the same variation twice.",
                "Dimensions with many small groups tend to look more explanatory than they are.",
            ],
        }

    @staticmethod
    def describe_methodology(
        df: pd.DataFrame,
        metric_column: str,
        dimension_columns: Optional[List[str]] = None,
        exclude_columns: Optional[List[str]] = None,
        top_n: int = 3,
    ) -> Dict[str, Any]:
        """
        Describes which dimensions analyze_dimensions() evaluates or skips, and how. It mirrors that
        method's selection rules for reporting only and does not influence any result.
        """
        metric = pd.to_numeric(df[metric_column], errors="coerce")
        auto_selected = not dimension_columns

        if auto_selected:
            candidates = [
                c for c in df.select_dtypes(exclude="number").columns.tolist()
                if not VarianceAnalyzer._is_identifier_column(df, c)
            ]
        else:
            candidates = list(dimension_columns)

        excluded = set(exclude_columns or [])
        evaluated = []
        skipped = []

        for dim in candidates:
            if dim in excluded:
                skipped.append({"dimension": dim, "reason": "excluded by the user"})
                continue

            if dim not in df.columns:
                skipped.append({"dimension": dim, "reason": "column not found"})
                continue

            combined = pd.DataFrame({"d": df[dim], "m": metric}).dropna()
            groups = int(combined["d"].nunique()) if not combined.empty else 0

            if groups < 2:
                skipped.append({"dimension": dim, "reason": "fewer than 2 groups with data"})
            elif auto_selected and (groups > 50 or groups / len(combined) > 0.5):
                skipped.append({
                    "dimension": dim,
                    "reason": "near-unique values (more than 50 groups or more than half of the rows)",
                })
            else:
                evaluated.append(dim)

        return {
            "metric_column": metric_column,
            "method": "Share of the metric's variation explained by each dimension (eta-squared style: between-group variation divided by total variation)",
            "rows": {
                "total_in_dataset": int(len(df)),
                "used_with_numeric_metric": int(metric.notna().sum()),
            },
            "dimension_selection": {
                "mode": "automatic" if auto_selected else "user-selected",
                "automatic_rule": "All non-numeric, non-identifier columns; near-unique columns are skipped.",
                "requested_dimensions": None if auto_selected else list(dimension_columns),
                "excluded_by_user": sorted(excluded),
                "dimensions_evaluated": evaluated,
                "dimensions_skipped": skipped,
                "near_unique_rule_applies_to": "automatic selection only",
            },
            "grouping_rule": "Rows are grouped by each dimension's distinct values; groups are compared by their mean metric value.",
            "highest_lowest_group_rule": "By mean metric value within the dimension.",
            "ranking": f"Dimensions are ranked by variance explained and only the top {top_n} are returned.",
            "missing_value_handling": "Rows with a missing or non-numeric metric (or a missing dimension value) are excluded; nothing is imputed.",
            "outlier_handling": "none; outliers are included in the means and variances",
            "date_grain": None,
            "aggregation": "mean per group",
            "limitations": [
                "Correlation is not causation: a dimension that explains variation is a probable cause, not a proven one.",
                "Dimensions are analyzed one at a time; overlapping dimensions can explain the same variation twice.",
                "Dimensions with many small groups tend to look more explanatory than they are.",
            ],
        }

    @staticmethod
    def analyze_dimensions(
        df: pd.DataFrame,
        metric_column: str,
        dimension_columns: Optional[List[str]] = None,
        top_n: int = 3,
        exclude_columns: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        For each dimension column, computes how much of the metric's variation
        is explained by that dimension (similar to eta-squared in ANOVA),
        and identifies the highest/lowest performing groups within it.
        Returns dimensions ranked by explanatory power (most impactful first).
        """
        working_df = df[[metric_column]].copy()
        working_df[metric_column] = pd.to_numeric(df[metric_column], errors="coerce")
        working_df = working_df.dropna()

        if len(working_df) < 3:
            raise ValueError("Not enough valid numeric data points to analyze.")

        auto_selected_dimensions = dimension_columns is None
        if dimension_columns is None:
            categorical_cols = df.select_dtypes(exclude="number").columns.tolist()
            dimension_columns = [
                c for c in categorical_cols
                if not VarianceAnalyzer._is_identifier_column(df, c)
            ]

        # User-excluded dimensions are removed whether the list was chosen manually or selected automatically.
        if exclude_columns:
            excluded = set(exclude_columns)
            candidate_dimensions = dimension_columns
            if candidate_dimensions is None:
                candidate_dimensions = locals().get("categorical_cols", [])
            dimension_columns = [
                column for column in candidate_dimensions
                if column in working_df.columns and column not in excluded
            ]
            if not dimension_columns:
                return []

        overall_mean = working_df[metric_column].mean()
        total_variance = working_df[metric_column].var()

        results = []

        for dim in dimension_columns:
            if dim not in df.columns:
                continue

            combined = pd.DataFrame({
                dim: df[dim],
                metric_column: pd.to_numeric(df[metric_column], errors="coerce"),
            }).dropna()

            if combined.empty:
                continue

            grouped = combined.groupby(dim)[metric_column]
            group_counts = grouped.size()

            if len(group_counts) < 2:
                continue  # need at least 2 groups to compare

            # Auto-selected near-unique columns (names, dates, free text) trivially "explain" all variance.
            if auto_selected_dimensions and (
                len(group_counts) > 50 or len(group_counts) / len(combined) > 0.5
            ):
                continue

            group_means = grouped.mean()

            n_total = len(combined)
            between_group_variance = sum(
                group_counts[g] * (group_means[g] - overall_mean) ** 2
                for g in group_means.index
            ) / (n_total - 1) if n_total > 1 else 0

            variance_explained = (
                between_group_variance / total_variance if total_variance and total_variance > 0 else 0
            )

            sorted_means = group_means.sort_values(ascending=False)

            results.append({
                "dimension": dim,
                "variance_explained": round(float(variance_explained), 3),
                "highest_group": {
                    "value": str(sorted_means.index[0]),
                    "average": round(float(sorted_means.iloc[0]), 2),
                },
                "lowest_group": {
                    "value": str(sorted_means.index[-1]),
                    "average": round(float(sorted_means.iloc[-1]), 2),
                },
            })

        results.sort(key=lambda r: r["variance_explained"], reverse=True)
        return results[:top_n]