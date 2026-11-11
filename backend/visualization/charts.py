# backend/visualization/charts.py
import re
import pandas as pd
from typing import Dict, Any, List, Optional

TIME_GRANULARITY_LEVELS = ["year", "month", "week", "day", "hour"]
ALLOWED_AGGREGATIONS = ("sum", "mean", "median", "count", "min", "max")


class ChartEngine:
    """
    Automatically selects an appropriate chart type for a given question/columns
    and returns chart-ready JSON data (not an image).
    """

    @staticmethod
    def is_identifier_name(name: str) -> bool:
        """
        True only for real identifier names: exact id/code/key/uuid/pk,
        separator-delimited suffixes (emp_id, order-id, customer code), or
        camelCase suffixes (EmpID, OrderId, CustomerCode). Plain substrings
        such as 'paid', 'valid', 'grid' or 'bid' do not match.
        """
        if not name:
            return False
        lowered = name.lower()
        if lowered in ("id", "code", "key", "uuid", "pk"):
            return True
        if re.search(r"[_\- ](id|code|key|uuid|pk)$", lowered):
            return True
        if re.search(r"[a-z0-9](ID|Id|Code|Key|UUID|Uuid|PK|Pk)$", name):
            return True
        return False

    @staticmethod
    def _is_identifier_column(df: pd.DataFrame, column: str) -> bool:
        """
        Heuristic: a column is likely an identifier (not a useful metric)
        if its name looks like an id/code/key column.
        Uniqueness alone is NOT used, since small datasets can have
        legitimate numeric metrics where every value happens to be unique.
        """
        return ChartEngine.is_identifier_name(column)

    @staticmethod
    def suggest_chart(
        df: pd.DataFrame,
        x_column: Optional[str] = None,
        y_column: Optional[str] = None,
        agg: str = "sum",
    ) -> Dict[str, Any]:
        """
        Suggests a chart type based on the data types of the given columns.
        If no columns are given, tries to auto-pick sensible defaults.
        """
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        categorical_cols = df.select_dtypes(exclude="number").columns.tolist()

        date_col = None
        for col in categorical_cols:
            try:
                pd.to_datetime(df[col].dropna().head(20), errors="raise")
                date_col = col
                break
            except Exception:
                continue

        if not x_column:
            x_column = date_col or (categorical_cols[0] if categorical_cols else None)

        if not y_column:
            candidates = [c for c in numeric_cols if c != x_column]
            non_id_candidates = [c for c in candidates if not ChartEngine._is_identifier_column(df, c)]
            if non_id_candidates:
                y_column = non_id_candidates[0]
            elif candidates:
                y_column = candidates[0]
            else:
                y_column = numeric_cols[0] if numeric_cols else None

        if not x_column or not y_column:
            return ChartEngine._as_table(df)

        if x_column == date_col:
            chart_type = "line"
        elif x_column in categorical_cols and df[x_column].nunique() <= 15:
            chart_type = "bar"
        elif x_column in numeric_cols and y_column in numeric_cols:
            chart_type = "scatter"
        else:
            chart_type = "bar"

        return ChartEngine._build_chart(df, x_column, y_column, chart_type, is_date=(x_column == date_col), agg=agg)

    @staticmethod
    def _build_chart(df: pd.DataFrame, x_column: str, y_column: str, chart_type: str, is_date: bool = False, agg: str = "sum") -> Dict[str, Any]:
        agg = agg.lower() if agg and agg.lower() in ALLOWED_AGGREGATIONS else "sum"
        working_df = df

        if is_date:
            # A daily date axis with many distinct days (e.g. 2+ years of
            # data) is unreadable as one point per day. Once there are more
            # than ~40 distinct dates, roll them up into monthly buckets
            # instead — this keeps the trend readable both on the
            # interactive dashboard and in exported chart images.
            parsed_dates = pd.to_datetime(df[x_column], errors="coerce")
            if parsed_dates.nunique() > 40:
                working_df = df.copy()
                # Conservative yearly roll-up: only when monthly buckets would themselves be unreadable (more than 60).
                monthly_bucket_count = parsed_dates.dropna().dt.to_period("M").nunique()
                bucket_format = "%Y" if monthly_bucket_count > 60 else "%Y-%m"
                working_df[x_column] = parsed_dates.dt.strftime(bucket_format)

        if chart_type in ("bar", "line"):
            group = working_df.groupby(x_column)[y_column]
            if agg == "mean":
                aggregated = group.mean().round(2)
            elif agg == "median":
                aggregated = group.median().round(2)
            elif agg == "count":
                aggregated = group.count()
            elif agg == "min":
                aggregated = group.min()
            elif agg == "max":
                aggregated = group.max()
            else:
                aggregated = group.sum()
            grouped = aggregated.reset_index()
            if chart_type == "line":
                grouped = grouped.sort_values(x_column)
            grouped = grouped.astype(object).where(pd.notnull(grouped), None)
            data = grouped.to_dict(orient="records")
        else:
            data = working_df[[x_column, y_column]].dropna().to_dict(orient="records")

        return {
            "chart_type": chart_type,
            "x_column": x_column,
            "y_column": y_column,
            "agg": agg,
            "data": data,
        }

    @staticmethod
    def _as_table(df: pd.DataFrame) -> Dict[str, Any]:
        return {
            "chart_type": "table",
            "x_column": None,
            "y_column": None,
            "data": df.head(20).astype(object).where(pd.notnull(df.head(20)), None).to_dict(orient="records"),
        }

    @staticmethod
    def histogram(df: pd.DataFrame, column: str, bins: int = 10) -> Dict[str, Any]:
        series = df[column].dropna()
        counts, bin_edges = pd.cut(series, bins=bins, retbins=True)
        histogram_data = counts.value_counts().sort_index()

        data = [
            {"bin": str(interval), "count": int(count)}
            for interval, count in histogram_data.items()
        ]

        return {
            "chart_type": "histogram",
            "column": column,
            "data": data,
        }

    @staticmethod
    def kpi_cards(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Generates simple KPI summaries for all numeric columns (excluding
        identifier-like columns such as 'ID', since totals/averages of an
        ID column are not meaningful).
        """
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        cards = []
        for col in numeric_cols:
            if ChartEngine._is_identifier_column(df, col):
                continue
            series = df[col].dropna()
            if series.empty:
                continue
            cards.append({
                "column": col,
                "total": float(series.sum()),
                "average": round(float(series.mean()), 2),
                "median": round(float(series.median()), 2),
                "min": float(series.min()),
                "max": float(series.max()),
            })
        return cards

    @staticmethod
    def kpi_methodology(df: pd.DataFrame) -> Dict[str, Any]:
        """Describes how kpi_cards() computes its figures. Does not change any calculation."""
        included = []
        excluded_identifier = []
        excluded_all_missing = []
        missing_ignored = {}

        for col in df.select_dtypes(include="number").columns.tolist():
            if ChartEngine.is_identifier_name(col):
                excluded_identifier.append(col)
                continue
            if df[col].dropna().empty:
                excluded_all_missing.append(col)
                continue
            included.append(col)
            missing_ignored[col] = int(df[col].isna().sum())

        return {
            "scope": "All rows of the current dataset; no date range or other filter is applied.",
            "row_count": int(len(df)),
            "statistics": {
                "total": "sum of non-missing values",
                "average": "mean of non-missing values, rounded to 2 decimals",
                "median": "median of non-missing values, rounded to 2 decimals",
                "min": "smallest non-missing value",
                "max": "largest non-missing value",
            },
            "columns_included": included,
            "columns_excluded_identifier_like": excluded_identifier,
            "columns_excluded_all_missing": excluded_all_missing,
            "missing_values_ignored": missing_ignored,
            "missing_value_handling": "Missing values are excluded from every statistic and are never imputed.",
            "outlier_handling": "none; outliers are included in every statistic",
            "date_grain": None,
            "smoothing": {"applied": False, "moving_average_window": None},
        }

    @staticmethod
    def correlation_matrix(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Computes the Pearson correlation coefficient between every pair of
        numeric columns (excluding identifier-like columns), returned as a
        matrix ready for a heatmap. Values range from -1 (strong negative
        relationship) to +1 (strong positive relationship).
        """
        numeric_cols = [
            c for c in df.select_dtypes(include="number").columns
            if not ChartEngine._is_identifier_column(df, c)
        ]

        if len(numeric_cols) < 2:
            return {"columns": numeric_cols, "matrix": []}

        corr_df = df[numeric_cols].corr().round(3)
        # Undefined correlations (constant or empty columns) become null: NaN is not valid JSON.
        matrix = [[None if pd.isna(v) else float(v) for v in row] for row in corr_df.values.tolist()]

        return {
            "columns": numeric_cols,
            "matrix": matrix,
        }

    @staticmethod
    def pivot_summary(
        df: pd.DataFrame,
        group_by: str,
        value_column: str,
        agg: str = "sum",
        split_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        if group_by not in df.columns:
            raise ValueError(f"Column '{group_by}' does not exist.")
        if value_column not in df.columns:
            raise ValueError(f"Column '{value_column}' does not exist.")
        if group_by == value_column:
            raise ValueError("Group By and Value must be different columns.")
        if split_by and split_by != group_by and split_by not in df.columns:
            raise ValueError(f"Column '{split_by}' does not exist.")

        agg = agg.lower() if agg and agg.lower() in ALLOWED_AGGREGATIONS else "sum"

        working = df.copy()
        working[value_column] = pd.to_numeric(working[value_column], errors="coerce")
        if working[value_column].isna().all():
            raise ValueError(f"Column '{value_column}' does not contain numeric values.")
        working = working.dropna(subset=[value_column])

        if split_by and split_by != group_by:
            pivoted = pd.pivot_table(
                working,
                index=group_by,
                columns=split_by,
                values=value_column,
                aggfunc=agg,
                fill_value=0,
            ).round(2).reset_index()
            pivoted.columns = [str(c) for c in pivoted.columns]
            return {
                "columns": [str(c) for c in pivoted.columns],
                "rows": pivoted.to_dict(orient="records"),
            }

        group = working.groupby(group_by)[value_column]
        grouped = pd.DataFrame({
            "count": group.count(),
            "sum": group.sum().round(2),
            "mean": group.mean().round(2),
            "median": group.median().round(2),
            "min": group.min().round(2),
            "max": group.max().round(2),
        })
        grouped = grouped.sort_values(by=agg, ascending=False).reset_index()
        return {
            "columns": [group_by, "count", "sum", "mean", "median", "min", "max"],
            "rows": grouped.to_dict(orient="records"),
        }

    @staticmethod
    def time_series_chart(
        df: pd.DataFrame,
        date_column: str,
        value_column: str,
        granularity: str = None,
        start: str = None,
        end: str = None,
    ) -> Dict[str, Any]:
        """
        Builds a drill-down-ready time series: aggregates the value column
        by year, month, week, day, or hour. If granularity isn't given, it's
        auto-picked based on how wide the date range is — e.g. 3 years of
        data starts at yearly buckets, a single month starts at daily
        buckets. 'start'/'end' optionally restrict to a sub-range (used
        when the user clicks into a bucket to see it at finer detail).
        """
        total_input_rows = int(len(df))
        working = df[[date_column, value_column]].dropna().copy()
        rows_dropped_missing = total_input_rows - int(len(working))
        try:
            working[date_column] = pd.to_datetime(working[date_column], errors="coerce", format="mixed")
        except (TypeError, ValueError):
            working[date_column] = pd.to_datetime(working[date_column], errors="coerce")
        rows_before_date_filter = len(working)
        working = working.dropna(subset=[date_column])
        skipped_invalid_dates = rows_before_date_filter - len(working)

        if working.empty:
            raise ValueError("No valid date values found in this column.")

        rows_before_range_filter = int(len(working))
        if start:
            working = working[working[date_column] >= pd.to_datetime(start)]
        if end:
            end_ts = pd.to_datetime(end)
            if len(str(end).strip()) <= 10:
                # Date-only end bound: include every timestamp on that last day.
                working = working[working[date_column] < end_ts + pd.Timedelta(days=1)]
            else:
                working = working[working[date_column] <= end_ts]
        if working.empty:
            raise ValueError("No data falls within that date range.")

        has_time_component = bool(
            (working[date_column].dt.hour != 0).any() or (working[date_column].dt.minute != 0).any()
        )

        granularity_was_auto = not granularity
        if not granularity:
            span_days = (working[date_column].max() - working[date_column].min()).days
            if span_days > 730:
                granularity = "year"
            elif span_days > 120:
                granularity = "month"
            elif span_days > 30:
                granularity = "week"
            elif span_days > 2:
                granularity = "day"
            else:
                granularity = "hour" if has_time_component else "day"

        if granularity == "hour" and not has_time_component:
            granularity = "day"  # hourly buckets are meaningless if every timestamp is midnight

        if granularity == "year":
            bucket = working[date_column].dt.strftime("%Y")
        elif granularity == "month":
            bucket = working[date_column].dt.strftime("%Y-%m")
        elif granularity == "week":
            week_start = working[date_column] - pd.to_timedelta(working[date_column].dt.weekday, unit="D")
            bucket = week_start.dt.strftime("%Y-%m-%d")
        elif granularity == "day":
            bucket = working[date_column].dt.strftime("%Y-%m-%d")
        elif granularity == "hour":
            bucket = working[date_column].dt.strftime("%Y-%m-%d %H:00")
        else:
            raise ValueError(f"Unknown granularity: {granularity}")

        grouped = (
            working.assign(_bucket=bucket)
            .groupby("_bucket")[value_column]
            .sum()
            .reset_index()
            .sort_values("_bucket")
            .rename(columns={"_bucket": date_column})
        )

        level_index = TIME_GRANULARITY_LEVELS.index(granularity)
        can_drill_down = False
        if level_index < len(TIME_GRANULARITY_LEVELS) - 1:
            next_level = TIME_GRANULARITY_LEVELS[level_index + 1]
            if next_level != "hour" or has_time_component:
                can_drill_down = True

        return {
            "chart_type": "bar",
            "x_column": date_column,
            "y_column": value_column,
            "granularity": granularity,
            "can_drill_down": can_drill_down,
            "skipped_invalid_dates": int(skipped_invalid_dates),
            "methodology": {
                "date_column": date_column,
                "value_column": value_column,
                "date_grain": granularity,
                "date_grain_source": "auto" if granularity_was_auto else "requested",
                "rollup": (
                    f"Values are grouped into {granularity} buckets"
                    + (" (weeks start on Monday)" if granularity == "week" else "")
                    + "."
                ),
                "aggregation": "sum",
                "date_range_filter": {
                    "start": start,
                    "end": end,
                    "end_covers_full_day": bool(end and len(str(end).strip()) <= 10),
                },
                "data_range": {
                    "first": str(working[date_column].min()),
                    "last": str(working[date_column].max()),
                },
                "rows": {
                    "total_in_dataset": total_input_rows,
                    "used_in_chart": int(len(working)),
                    "excluded_by_date_range": rows_before_range_filter - int(len(working)),
                },
                "missing_value_handling": {
                    "rows_dropped_missing_date_or_value": int(rows_dropped_missing),
                    "rows_dropped_unreadable_date": int(skipped_invalid_dates),
                    "imputation": "none",
                },
                "outlier_handling": "none; outliers are included in the sums",
                "smoothing": {
                    "applied": False,
                    "moving_average_window": None,
                    "note": "Returned data is unsmoothed. Moving averages (3 or 7 periods) are optional overlays added by the viewer or exports.",
                },
            },
            "data": grouped.to_dict(orient="records"),
        }