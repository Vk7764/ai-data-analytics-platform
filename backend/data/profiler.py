# backend/data/profiler.py
import pandas as pd
from typing import Dict, Any


class DataProfiler:
    """
    Automatically analyzes a DataFrame's structure:
    columns, data types, row count, categorical/numeric/date columns, etc.
    """

    @staticmethod
    def profile(df: pd.DataFrame) -> Dict[str, Any]:
        num_rows, num_cols = df.shape

        column_info = []
        numeric_cols = []
        categorical_cols = []
        date_cols = []

        for col in df.columns:
            col_data = df[col]
            dtype = str(col_data.dtype)
            missing = int(col_data.isna().sum())
            unique_count = int(col_data.nunique())

            inferred_type = DataProfiler._infer_type(col_data)

            if inferred_type == "numeric":
                numeric_cols.append(col)
            elif inferred_type == "date":
                date_cols.append(col)
            else:
                categorical_cols.append(col)

            column_info.append({
                "name": col,
                "dtype": dtype,
                "inferred_type": inferred_type,
                "missing_values": missing,
                "missing_percent": round((missing / num_rows) * 100, 2) if num_rows else 0,
                "unique_values": unique_count,
            })

        total_cells = num_rows * num_cols
        total_missing = sum(c["missing_values"] for c in column_info)
        dup_rows = int(df.duplicated().sum())
        missing_ratio = (total_missing / total_cells) if total_cells else 0.0
        dup_ratio = (dup_rows / num_rows) if num_rows else 0.0
        health_score = round(max(0.0, min(100.0, (1.0 - (0.7 * missing_ratio + 0.3 * dup_ratio)) * 100.0)), 1)

        return {
            "num_rows": num_rows,
            "num_columns": num_cols,
            "columns": column_info,
            "numeric_columns": numeric_cols,
            "categorical_columns": categorical_cols,
            "date_columns": date_cols,
            "duplicate_rows": dup_rows,
            "health_score": health_score,
        }

    @staticmethod
    def _infer_type(series: pd.Series) -> str:
        """Try to figure out the real semantic type of a column."""
        if pd.api.types.is_numeric_dtype(series):
            return "numeric"

        if pd.api.types.is_datetime64_any_dtype(series):
            return "date"

        # Try to parse as date if it's an object/string column (pandas 3 uses a dedicated string dtype)
        if series.dtype == "object" or pd.api.types.is_string_dtype(series):
            sample = series.dropna().head(20)
            if len(sample) > 0:
                try:
                    import warnings

                    with warnings.catch_warnings():
                        warnings.filterwarnings(
                            "ignore",
                            message=r"Could not infer format",
                            category=UserWarning,
                        )
                        pd.to_datetime(sample, errors="raise")
                    return "date"
                except Exception:
                    pass

        return "categorical"