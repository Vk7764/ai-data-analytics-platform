# backend/data/cleaner.py
import re
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from backend.visualization.charts import ChartEngine


class DataCleaner:
    """
    Detects data quality issues (missing values, duplicates, outliers,
    inconsistent text values, mixed date formats, numbers stored as text,
    key-based duplicates, invalid emails, invalid negatives, etc.) and
    applies cleaning actions ONLY after user approval.
    """

    @staticmethod
    def detect_issues(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Scan the DataFrame and report all detected issues.
        Does NOT modify the data — just reports what it found.
        """
        issues = {
            "duplicate_rows": DataCleaner._detect_duplicates(df),
            "key_duplicates": DataCleaner._detect_key_duplicates(df),
            "missing_values": DataCleaner._detect_missing(df),
            "outliers": DataCleaner._detect_outliers(df),
            "negative_values": DataCleaner._detect_negative_value_issues(df),
            "inconsistent_values": DataCleaner._detect_inconsistent_values(df),
            "fuzzy_category_issues": DataCleaner._detect_fuzzy_category_issues(df),
            "date_format_issues": DataCleaner._detect_date_format_issues(df),
            "numeric_format_issues": DataCleaner._detect_numeric_formatting_issues(df),
            "email_format_issues": DataCleaner._detect_email_format_issues(df),
        }
        return issues

    # ---------- Detection ----------

    @staticmethod
    def _detect_duplicates(df: pd.DataFrame) -> Dict[str, Any]:
        dup_count = int(df.duplicated().sum())
        return {
            "count": dup_count,
            "message": f"Found {dup_count} duplicate rows." if dup_count > 0
                       else "No duplicate rows found.",
            "action_available": dup_count > 0,
        }

    @staticmethod
    def _detect_key_duplicates(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Detects columns that look like identifiers (EmpID, OrderID, CustomerCode...)
        where the SAME id value appears more than once. This catches "logical"
        duplicate records even when other columns differ slightly (e.g. one copy
        has a missing value that the other doesn't) — something a plain
        whole-row duplicate check misses entirely.
        """
        result = []
        for col in df.columns:
            looks_like_id = ChartEngine.is_identifier_name(col)
            if not looks_like_id:
                continue

            series = df[col].dropna()
            series = series[series.astype(str).str.strip() != ""]
            if series.empty:
                continue

            counts = series.value_counts()
            non_null_count = int(len(series))
            unique_count = int(len(counts))

            # Only treat a column as a record key when its values behave like a
            # near-unique identifier. Repeated business codes such as CustomerID,
            # Country Code, or Product Code are left for manual review.
            if non_null_count < 5 or unique_count / non_null_count < 0.95:
                continue

            dup_keys = counts[counts > 1]
            if dup_keys.empty:
                continue

            extra_row_count = int((dup_keys - 1).sum())
            if extra_row_count > max(1, int(non_null_count * 0.05)):
                continue

            result.append({
                "column": col,
                "duplicate_key_count": int(len(dup_keys)),
                "extra_row_count": extra_row_count,
                "example_keys": [str(k) for k in dup_keys.head(5).index.tolist()],
            })
        return result

    @staticmethod
    def _detect_missing(df: pd.DataFrame) -> List[Dict[str, Any]]:
        result = []
        for col in df.columns:
            missing_count = int(df[col].isna().sum())
            if missing_count > 0:
                result.append({
                    "column": col,
                    "missing_count": missing_count,
                    "missing_percent": round((missing_count / len(df)) * 100, 2),
                    "suggested_action": "fill_or_drop",
                    "is_numeric": bool(pd.api.types.is_numeric_dtype(df[col])),
                })
        return result

    @staticmethod
    def _detect_outliers(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Uses the IQR method to detect outliers in numeric columns.
        """
        result = []
        numeric_df = df.select_dtypes(include="number")

        for col in numeric_df.columns:
            series = numeric_df[col].dropna()
            if len(series) < 4:
                continue

            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr

            outlier_count = int(((series < lower_bound) | (series > upper_bound)).sum())

            if outlier_count > 0:
                display_lower = lower_bound
                if series.min() >= 0 and lower_bound < 0:
                    display_lower = 0

                result.append({
                    "column": col,
                    "outlier_count": outlier_count,
                    "lower_bound": round(float(display_lower), 2),
                    "upper_bound": round(float(upper_bound), 2),
                })
        return result

    @staticmethod
    def _detect_negative_value_issues(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Flags numeric columns that are almost always non-negative (e.g. Salary,
        Age, Price, Quantity) but contain a few negative values — these are
        very likely data-entry errors, called out explicitly rather than
        just being buried inside the generic outlier list.
        """
        result = []
        numeric_cols = df.select_dtypes(include="number").columns.tolist()

        for col in numeric_cols:
            series = df[col].dropna()
            if series.empty:
                continue

            negative_count = int((series < 0).sum())
            if negative_count == 0:
                continue

            non_negative_ratio = (series >= 0).mean()
            if non_negative_ratio < 0.9:
                continue  # this column can legitimately go negative (e.g. profit/loss)

            result.append({
                "column": col,
                "negative_count": negative_count,
                "example_values": [float(v) for v in series[series < 0].head(3).tolist()],
            })
        return result

    @staticmethod
    def _detect_inconsistent_values(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Detects categorical columns where the same logical value appears as
        multiple different-looking entries due to whitespace or casing
        differences only (e.g. 'West', ' west ', 'WEST').
        """
        result = []
        categorical_cols = df.select_dtypes(exclude="number").columns.tolist()

        for col in categorical_cols:
            series = df[col].dropna().astype(str)
            if series.empty:
                continue

            raw_unique_count = series.nunique()
            normalized = series.str.strip().str.lower()
            normalized_unique_count = normalized.nunique()

            if normalized_unique_count < raw_unique_count:
                groups = {}
                for raw_val, norm_val in zip(series, normalized):
                    groups.setdefault(norm_val, set()).add(raw_val)

                variant_groups = [
                    {"normalized": norm_val, "variants": sorted(list(variants))}
                    for norm_val, variants in groups.items()
                    if len(variants) > 1
                ]

                result.append({
                    "column": col,
                    "raw_unique_count": raw_unique_count,
                    "normalized_unique_count": normalized_unique_count,
                    "affected_groups": variant_groups[:5],
                })

        return result

    @staticmethod
    def _fuzzy_normalize_key(value: str) -> str:
        """
        A more aggressive normalization than simple strip+lowercase: strips
        common noise words ('dept', 'department'), removes periods, and
        removes ALL internal whitespace. This catches cases like
        'I.T.' / 'IT' / ' S a l e s ' / 'HR Dept' all meaning the same thing —
        but because it's a more aggressive transform, it's reported as a
        SEPARATE, lower-confidence issue that the user should visually
        review before approving (unlike the exact whitespace/case check).
        """
        v = value.strip().lower()
        v = re.sub(r"\bdepartment\b", "", v)
        v = re.sub(r"\bdept\b", "", v)
        v = v.replace(".", "")
        v = re.sub(r"\s+", "", v)
        return v

    @staticmethod
    def _detect_fuzzy_category_issues(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Secondary, heuristic pass for categorical columns: groups values that
        collapse to the same key under aggressive normalization (see
        _fuzzy_normalize_key), but were NOT already caught by the exact
        whitespace/case check. Flagged separately because this is a fuzzier
        match and carries a higher chance of an incorrect grouping, so the
        user should look at the examples before approving.
        """
        result = []
        categorical_cols = df.select_dtypes(exclude="number").columns.tolist()

        for col in categorical_cols:
            if ChartEngine.is_identifier_name(col):
                continue  # Aggressive normalization would merge distinct identifiers.

            series = df[col].dropna().astype(str)
            if series.empty:
                continue

            exact_normalized = series.str.strip().str.lower()
            if exact_normalized.nunique() < series.nunique():
                continue  # already handled by the exact check, skip here

            fuzzy_keys = series.apply(DataCleaner._fuzzy_normalize_key)

            groups = {}
            for raw_val, fuzzy_val in zip(series, fuzzy_keys):
                if not fuzzy_val:
                    continue
                groups.setdefault(fuzzy_val, set()).add(raw_val)

            variant_groups = [
                {"normalized": key, "variants": sorted(list(variants))}
                for key, variants in groups.items()
                if len(variants) > 1
            ]

            if variant_groups:
                result.append({
                    "column": col,
                    "raw_unique_count": series.nunique(),
                    "affected_groups": variant_groups[:5],
                })

        return result

    @staticmethod
    def _parse_dates_mixed(series: pd.Series, dayfirst: bool = False) -> pd.Series:
        try:
            return pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=dayfirst)
        except (TypeError, ValueError):
            return pd.to_datetime(series, errors="coerce", dayfirst=dayfirst)

    @staticmethod
    def _infer_dayfirst(series: pd.Series) -> bool:
        """
        True only when the data itself proves a day-first layout: some value has a first
        field above 12 and no value has a second field above 12. Otherwise month-first is kept.
        """
        pattern = re.compile(r"^\s*(\d{1,2})[/\-.](\d{1,2})[/\-.]\d{2,4}")
        first_above_12 = False
        second_above_12 = False
        for value in series.dropna().astype(str):
            match = pattern.match(value)
            if not match:
                continue
            if int(match.group(1)) > 12:
                first_above_12 = True
            if int(match.group(2)) > 12:
                second_above_12 = True
        return first_above_12 and not second_above_12

    @staticmethod
    def _date_format_signature(value: str) -> Optional[Tuple[str, Tuple[str, ...]]]:
        """
        Builds a structural "shape" for a date string, independent of the
        actual date value — e.g. '16-4-2021' -> ('-', ('n', 'n', 'Y')),
        '2024-07-12' -> ('-', ('Y', 'n', 'n')), '15/08/2020' -> ('/', ('n', 'n', 'Y')),
        '16-Jun-2024' -> ('-', ('n', 'A', 'Y')).
        Two dates with different signatures are in different formats, even
        if they use the same separator (e.g. year-first vs day-first) or
        the same field order but a different separator.
        """
        s = value.strip()
        sep = None
        for candidate in ("-", "/"):
            if candidate in s:
                sep = candidate
                break
        if sep is None:
            return None

        parts = s.split(sep)
        if len(parts) != 3:
            return None

        kinds = []
        for p in parts:
            if p.isalpha():
                kinds.append("A")  # month name, e.g. "Jun"
            elif p.isdigit():
                if len(p) == 4:
                    if not 1900 <= int(p) <= 2100:
                        return None  # implausible year
                    kinds.append("Y")
                elif len(p) <= 2:
                    kinds.append("n")  # day or month
                else:
                    return None  # 3 or 5+ digit segment is not a date field
            else:
                return None

        return (sep, tuple(kinds))

    @staticmethod
    def _detect_date_format_issues(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Detects text columns that contain dates written in more than one
        structural format (different separators and/or field arrangements),
        using a generic shape-signature comparison instead of a fixed list
        of known formats — this catches formats like 'D-M-YYYY' (no leading
        zeros) that a hardcoded pattern list would otherwise miss.
        """
        result = []
        categorical_cols = df.select_dtypes(exclude="number").columns.tolist()

        for col in categorical_cols:
            series = df[col].dropna().astype(str)
            if series.empty:
                continue

            parsed = DataCleaner._parse_dates_mixed(series)
            valid_ratio = parsed.notna().mean()
            if valid_ratio < 0.5:
                continue  # doesn't look like a date column at all

            valid_values = series[parsed.notna()]
            signature_counts: Dict[str, int] = {}
            for val in valid_values:
                sig = DataCleaner._date_format_signature(val)
                if sig is None:
                    continue
                label = f"separator '{sig[0]}', shape {'-'.join(sig[1])}"
                signature_counts[label] = signature_counts.get(label, 0) + 1

            if len(signature_counts) > 1:
                result.append({
                    "column": col,
                    "formats_found": signature_counts,
                    "valid_date_ratio": round(float(valid_ratio), 2),
                })

        return result

    @staticmethod
    def _detect_numeric_formatting_issues(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Detects text columns that are actually numbers, either because they
        carry currency/percent formatting or because a handful of stray
        non-numeric entries forced an otherwise-numeric column to be text.
        """
        result = []
        categorical_cols = df.select_dtypes(exclude="number").columns.tolist()

        for col in categorical_cols:
            series = df[col].dropna().astype(str)
            if series.empty:
                continue

            # Skip columns that look like codes/IDs with meaningful leading
            # zeros (e.g. '0006', '0042') — converting these to numbers
            # would silently destroy the leading zeros, corrupting the data.
            # A real formatted number ('$1,234.56') never has this shape,
            # so this is a safe, low-risk exclusion.
            leading_zero_ratio = series.str.match(r"^0\d+$").mean()
            if leading_zero_ratio > 0.3:
                continue

            has_symbols = series.str.contains(r"[\$,%]").any()

            numeric_parsed = series.apply(DataCleaner._smart_parse_number)
            valid_ratio = numeric_parsed.notna().mean()

            threshold = 0.5 if has_symbols else 0.9
            if valid_ratio < threshold:
                continue

            symbols_found = []
            if has_symbols:
                symbols_found = sorted(set("".join(series.str.findall(r"[\$,%]").sum())))

            if symbols_found:
                description = (
                    f"{round(valid_ratio * 100)}% of values look numeric but contain "
                    f"formatting characters ({' '.join(symbols_found)})"
                )
            else:
                description = (
                    f"{round(valid_ratio * 100)}% of values look numeric, but the column is "
                    f"stored as text — likely due to a few stray non-numeric entries"
                )

            result.append({
                "column": col,
                "valid_numeric_ratio": round(float(valid_ratio), 2),
                "symbols_found": symbols_found,
                "description": description,
            })

        return result

    @staticmethod
    def _detect_email_format_issues(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Finds columns that look like email addresses (by name, or by content)
        and checks each value against a basic email shape. Reports two kinds
        of problems separately: malformed addresses (e.g. missing '@', which
        cannot be safely auto-corrected) and inconsistent capitalization
        (which CAN be safely auto-fixed by lowercasing).
        """
        result = []
        email_pattern = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

        for col in df.select_dtypes(exclude="number").columns:
            series = df[col].dropna().astype(str)
            if series.empty:
                continue

            name_hint = "email" in col.lower()
            contains_at = series.str.contains("@").mean()
            if not name_hint and contains_at < 0.3:
                continue  # doesn't look like an email column at all

            is_valid = series.apply(lambda v: bool(email_pattern.match(v)))
            invalid_count = int((~is_valid).sum())

            valid_values = series[is_valid]
            has_case_issue = bool((valid_values != valid_values.str.lower()).any())

            if invalid_count == 0 and not has_case_issue:
                continue

            result.append({
                "column": col,
                "invalid_count": invalid_count,
                "has_case_issue": has_case_issue,
                "example_invalid": series[~is_valid].head(3).tolist(),
            })

        return result

    # ---------- Cleaning actions (only run after approval) ----------

    @staticmethod
    def remove_duplicates(df: pd.DataFrame) -> pd.DataFrame:
        return df.drop_duplicates().reset_index(drop=True)

    @staticmethod
    def resolve_key_duplicates(df: pd.DataFrame, column: str) -> pd.DataFrame:
        """
        Keeps only the first occurrence of each value in an identifier
        column (e.g. EmpID), dropping subsequent rows that share the same
        id — these represent the same real-world record duplicated,
        even if other columns don't match exactly.
        """
        # Rows with a missing or blank key are never treated as duplicates of each other.
        blank_key = df[column].isna() | (df[column].astype(str).str.strip() == "")
        duplicate_key = df.duplicated(subset=[column], keep="first") & ~blank_key
        return df[~duplicate_key].reset_index(drop=True)

    @staticmethod
    def fill_missing(df: pd.DataFrame, column: str, strategy: str = "mean") -> pd.DataFrame:
        df = df.copy()

        if strategy in ("mean", "median"):
            if not pd.api.types.is_numeric_dtype(df[column]):
                raise ValueError(
                    f"Cannot compute {strategy} for '{column}' because it is not a numeric column "
                    f"(it may contain text, symbols, or mixed formats). "
                    f"Try 'mode' or clean the column's format first."
                )
            fill_value = df[column].mean() if strategy == "mean" else df[column].median()
            df[column] = df[column].fillna(fill_value)

        elif strategy == "mode":
            mode_values = df[column].mode()
            if not mode_values.empty:
                df[column] = df[column].fillna(mode_values[0])

        else:
            df[column] = df[column].fillna(strategy)

        return df

    @staticmethod
    def drop_missing(df: pd.DataFrame, column: str) -> pd.DataFrame:
        return df.dropna(subset=[column]).reset_index(drop=True)

    @staticmethod
    def mark_negative_as_missing(df: pd.DataFrame, column: str) -> pd.DataFrame:
        """
        Converts negative values in a column that should always be
        non-negative (e.g. Salary, Age) into missing values, so they can
        then be handled via the normal fill/drop workflow instead of
        silently keeping an invalid negative number.
        """
        df = df.copy()
        df.loc[df[column] < 0, column] = np.nan
        return df

    @staticmethod
    def normalize_text(df: pd.DataFrame, column: str) -> pd.DataFrame:
        df = df.copy()
        series = df[column].astype(str)
        normalized_key = series.str.strip().str.lower()

        variant_counts = series.groupby(normalized_key).agg(lambda x: x.value_counts().idxmax())
        mapping = variant_counts.to_dict()

        canonical = normalized_key.map(mapping)
        df[column] = canonical.where(df[column].notna(), np.nan)
        return df

    @staticmethod
    def normalize_text_aggressive(df: pd.DataFrame, column: str) -> pd.DataFrame:
        """
        Applies the fuzzy normalization (see _fuzzy_normalize_key) to merge
        values like 'I.T.' / 'IT' / 'HR Dept' into a single canonical form
        — the most frequently occurring raw variant within each fuzzy group.
        """
        df = df.copy()
        series = df[column].astype(str)
        fuzzy_key = series.apply(DataCleaner._fuzzy_normalize_key)

        variant_counts = series.groupby(fuzzy_key).agg(lambda x: x.value_counts().idxmax())
        mapping = variant_counts.to_dict()

        canonical = fuzzy_key.map(mapping).fillna(series)
        df[column] = canonical.where(df[column].notna(), np.nan)
        return df

    @staticmethod
    def lowercase_column(df: pd.DataFrame, column: str) -> pd.DataFrame:
        """Generic action: lowercases every value in a text column (e.g. to fix email capitalization)."""
        df = df.copy()
        df[column] = df[column].astype(str).str.lower()
        return df

    @staticmethod
    def flag_invalid_email_as_missing(df: pd.DataFrame, column: str) -> pd.DataFrame:
        """
        Converts malformed email addresses (that don't match a basic
        'user@domain.tld' shape) into missing values, since they can't be
        safely auto-corrected — the user can then fill/drop them manually.
        """
        df = df.copy()
        email_pattern = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
        mask = df[column].notna() & ~df[column].astype(str).apply(lambda v: bool(email_pattern.match(v)))
        df.loc[mask, column] = np.nan
        return df

    @staticmethod
    def auto_clean_safe(df: pd.DataFrame) -> pd.DataFrame:
        working = df.copy().drop_duplicates().reset_index(drop=True)
        for col in working.columns:
            if pd.api.types.is_object_dtype(working[col]) or pd.api.types.is_string_dtype(working[col]):
                working[col] = working[col].where(working[col].isna(), working[col].astype(str).str.strip())
                working[col] = working[col].replace("", np.nan)
            elif pd.api.types.is_numeric_dtype(working[col]):
                if ChartEngine.is_identifier_name(col):
                    continue  # Do not impute identifier-like columns.
                if working[col].isna().any() and not working[col].isna().all():
                    working[col] = working[col].fillna(working[col].median())
        return working

    @staticmethod
    def sort_dataset(df: pd.DataFrame, column: str, ascending: bool = True) -> pd.DataFrame:
        if column not in df.columns:
            raise ValueError(f"Column '{column}' does not exist.")
        return df.sort_values(by=column, ascending=ascending, na_position="last").reset_index(drop=True)

    @staticmethod
    def sample_rows(df: pd.DataFrame, count: int) -> pd.DataFrame:
        count = int(count)
        if not (1 <= count < len(df)):
            raise ValueError(f"Sample size must be between 1 and {len(df) - 1}.")
        return df.sample(n=count, random_state=42).reset_index(drop=True)

    @staticmethod
    def drop_column(df: pd.DataFrame, column: str) -> pd.DataFrame:
        if column not in df.columns:
            raise ValueError(f"Column '{column}' does not exist.")
        if len(df.columns) <= 1:
            raise ValueError("Cannot drop the only remaining column.")
        return df.drop(columns=[column])

    @staticmethod
    def rename_column(df: pd.DataFrame, column: str, new_name: str) -> pd.DataFrame:
        new_name = (new_name or "").strip()
        if column not in df.columns:
            raise ValueError(f"Column '{column}' does not exist.")
        if not new_name:
            raise ValueError("New column name cannot be empty.")
        if new_name in df.columns and new_name != column:
            raise ValueError(f"A column named '{new_name}' already exists.")
        return df.rename(columns={column: new_name})

    @staticmethod
    def add_calculated_column(df: pd.DataFrame, new_name: str, col_a: str, operator: str, col_b: str) -> pd.DataFrame:
        new_name = (new_name or "").strip()
        if not new_name:
            raise ValueError("New column name cannot be empty.")
        if new_name in df.columns:
            raise ValueError(f"A column named '{new_name}' already exists.")
        if col_a not in df.columns:
            raise ValueError(f"Column '{col_a}' does not exist.")
        if col_b not in df.columns:
            raise ValueError(f"Column '{col_b}' does not exist.")
        if operator not in ("+", "-", "*", "/"):
            raise ValueError("Operator must be one of +, -, *, /.")

        df = df.copy()
        a = pd.to_numeric(df[col_a], errors="coerce")
        b = pd.to_numeric(df[col_b], errors="coerce")

        if operator == "+":
            result = a + b
        elif operator == "-":
            result = a - b
        elif operator == "*":
            result = a * b
        else:
            result = a / b.replace(0, np.nan)

        df[new_name] = result.round(4)
        return df

    @staticmethod
    def filter_rows(df: pd.DataFrame, column: str, operator: str, value: str) -> pd.DataFrame:
        if column not in df.columns:
            raise ValueError(f"Column '{column}' does not exist.")
        if operator not in ("==", "!=", ">", "<", ">=", "<=", "contains"):
            raise ValueError("Operator must be one of ==, !=, >, <, >=, <=, contains.")

        if operator in (">", "<", ">=", "<="):
            try:
                target = float(value)
            except (TypeError, ValueError):
                raise ValueError("Filter value must be a number for this comparison.")
            numeric = pd.to_numeric(df[column], errors="coerce")
            if operator == ">":
                mask = numeric > target
            elif operator == "<":
                mask = numeric < target
            elif operator == ">=":
                mask = numeric >= target
            else:
                mask = numeric <= target
        elif operator in ("==", "!="):
            text_value = str(value).strip().lower()
            if pd.api.types.is_numeric_dtype(df[column]):
                try:
                    equal = df[column] == float(value)
                except (TypeError, ValueError):
                    equal = df[column].astype(str).str.strip().str.lower() == text_value
            else:
                equal = df[column].astype(str).str.strip().str.lower() == text_value
            mask = equal if operator == "==" else ~equal
        else:
            mask = df[column].astype(str).str.contains(str(value).strip(), case=False, na=False, regex=False)

        filtered = df[mask]
        if filtered.empty:
            raise ValueError("That filter would remove all rows. No changes were made.")
        return filtered.reset_index(drop=True)

    @staticmethod
    def find_and_replace(df: pd.DataFrame, column: str, find_val: str, replace_val: str) -> pd.DataFrame:
        if column not in df.columns:
            raise ValueError(f"Column '{column}' does not exist.")
        if find_val is None or str(find_val) == "":
            raise ValueError("Find value cannot be empty.")

        df = df.copy()
        series = df[column]
        find_str = str(find_val).strip()
        replace_str = "" if replace_val is None else str(replace_val).strip()

        if pd.api.types.is_numeric_dtype(series):
            if replace_str == "":
                new_val = np.nan
            else:
                try:
                    new_val = float(replace_str)
                    if pd.api.types.is_integer_dtype(series) and new_val.is_integer():
                        new_val = int(new_val)
                except ValueError:
                    raise ValueError(f"Replacement value must be a number for numeric column '{column}'.")

            try:
                target_num = float(find_str)
                mask = series == target_num
            except ValueError:
                mask = series.astype(str).str.strip().str.lower() == find_str.lower()

            if not mask.any():
                raise ValueError(f"No matching values '{find_str}' found in '{column}'.")
            df.loc[mask, column] = new_val
        else:
            mask = series.astype(str).str.strip().str.lower() == find_str.lower()
            if not mask.any():
                raise ValueError(f"No matching values '{find_str}' found in '{column}'.")
            df.loc[mask, column] = np.nan if replace_str == "" else replace_str

        return df

    @staticmethod
    def _cell_text_matches(current_text: str, expected_text: str) -> bool:
        """Exact text match, or numeric equality (so '100' matches pandas' '100.0')."""
        if current_text == expected_text:
            return True
        try:
            return float(current_text) == float(expected_text)
        except (TypeError, ValueError, OverflowError):
            return False

    @staticmethod
    def update_cell(
        df: pd.DataFrame,
        row_index: int,
        column: str,
        value: Optional[str],
        expected_old: Optional[str] = None,
    ) -> pd.DataFrame:
        if column not in df.columns:
            raise ValueError(f"Column '{column}' does not exist.")
        if row_index is None or not (0 <= int(row_index) < len(df)):
            raise ValueError("Row index is out of range. Please refresh the table and try again.")

        idx = int(row_index)
        col_loc = df.columns.get_loc(column)
        current_raw = df.iloc[idx, col_loc]
        current_str = "" if pd.isna(current_raw) else str(current_raw)

        if expected_old is not None and not DataCleaner._cell_text_matches(current_str, str(expected_old)):
            raise ValueError("Row position changed after a recent edit. Table refreshed—please try again.")

        df = df.copy()
        text_val = "" if value is None else str(value).strip()

        if text_val == "":
            df.iloc[idx, col_loc] = np.nan
        elif pd.api.types.is_numeric_dtype(df[column]):
            try:
                num_val = float(text_val)
                if pd.api.types.is_integer_dtype(df[column]) and num_val.is_integer():
                    df.iloc[idx, col_loc] = int(num_val)
                else:
                    df.iloc[idx, col_loc] = num_val
            except ValueError:
                raise ValueError(f"Value must be a valid number for numeric column '{column}'.")
        else:
            df.iloc[idx, col_loc] = text_val

        return df

    @staticmethod
    def clip_outliers(df: pd.DataFrame, column: str) -> pd.DataFrame:
        """
        Caps values outside the IQR range to the nearest expected bound,
        instead of removing the rows.
        """
        df = df.copy()
        series = pd.to_numeric(df[column], errors="coerce").dropna()
        if series.empty:
            return df
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        if series.min() >= 0 and lower_bound < 0:
            lower_bound = 0
        df[column] = pd.to_numeric(df[column], errors="coerce").clip(lower=lower_bound, upper=upper_bound)
        return df

    @staticmethod
    def normalize_date_format(df: pd.DataFrame, column: str) -> pd.DataFrame:
        df = df.copy()
        original = df[column]
        dayfirst = DataCleaner._infer_dayfirst(original)
        parsed = DataCleaner._parse_dates_mixed(original.astype(str), dayfirst=dayfirst)
        # Values that cannot be parsed keep their original content instead of being blanked.
        df[column] = parsed.dt.strftime("%Y-%m-%d").where(parsed.notna(), original)
        return df

    @staticmethod
    def _smart_parse_number(value, period_is_thousands: bool = False) -> float:
        """
        Parses a numeric string that may use either the US convention
        (comma = thousands separator, period = decimal — e.g. '4,267.83')
        or the European convention (period = thousands separator,
        comma = decimal — e.g. '4.267,83'). Naively stripping commas
        would silently corrupt European-formatted numbers (turning
        '4.267,83' into 4.26783 instead of 4267.83), so the two are told
        apart using the standard heuristic: whichever separator appears
        LAST in the string is the actual decimal point.

        Handles non-string inputs gracefully: missing values (NaN) stay
        missing, and values that are already numeric are returned as-is,
        since a mixed-type column can contain both real numbers and
        formatted-text numbers in different cells.
        """
        if pd.isna(value):
            return np.nan
        if isinstance(value, (int, float)):
            return float(value)

        s = re.sub(r"[\$%\s]", "", str(value).strip())
        if not s:
            return np.nan

        has_comma = "," in s
        has_period = "." in s

        if has_comma and has_period:
            if s.rfind(",") > s.rfind("."):
                # comma is the decimal separator (European): '4.267,83' -> '4267.83'
                s = s.replace(".", "").replace(",", ".")
            else:
                # period is the decimal separator (US): '4,267.83' -> '4267.83'
                s = s.replace(",", "")
        elif has_comma:
            # Only a comma present — ambiguous. Treat it as a decimal separator
            # only if it looks like one decimal comma with exactly 2 digits after
            # it (e.g. '267,83'); otherwise treat it as a thousands separator
            # (e.g. '4,267').
            if re.search(r",\d{2}$", s) and not re.search(r",\d{3}\b", s):
                s = s.replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "." in s:
            # Several period-separated groups (for example 1.234.567) can only be thousands separators.
            if re.fullmatch(r"-?\d{1,3}(?:\.\d{3}){2,}", s):
                s = s.replace(".", "")
            # A single 1.234 is ambiguous. Treat it as thousands only when the whole column shows
            # European formatting; otherwise preserve it as a normal decimal value.
            elif period_is_thousands and re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", s):
                s = s.replace(".", "")

        try:
            return float(s)
        except ValueError:
            return np.nan

    @staticmethod
    def clean_numeric_format(df: pd.DataFrame, column: str) -> pd.DataFrame:
        """
        Converts a text column that represents numbers — whether formatted
        with currency symbols, percent signs, US-style thousands separators
        ('4,267.83'), or European-style separators ('4.267,83') — into a
        proper numeric column, without misinterpreting which separator is
        the decimal point.
        """
        df = df.copy()
        original = df[column]
        # Column-level evidence decides how a lone 1.234 is read: European formatting is assumed
        # only when European patterns are present and no US-style pattern contradicts them.
        evidence_texts = original.dropna().astype(str).str.replace(r"[\$%\s]", "", regex=True)
        european_evidence = evidence_texts.str.contains(
            r"^-?\d{1,3}(?:\.\d{3})+,\d+$|^-?\d+,\d{1,2}$|^-?\d{1,3}(?:\.\d{3}){2,}$", regex=True
        ).any()
        us_evidence = evidence_texts.str.contains(
            r"^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$|^-?\d*\.\d{1,2}$|^-?\d*\.\d{4,}$", regex=True
        ).any()
        period_is_thousands = bool(european_evidence and not us_evidence)
        parsed = original.astype(str).apply(
            lambda v: DataCleaner._smart_parse_number(v, period_is_thousands)
        )
        # Entries that cannot be parsed keep their original content instead of being blanked.
        df[column] = parsed.where(parsed.notna() | original.isna(), original)
        return df

    @staticmethod
    def auto_clean_all(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
        """
        Applies every SAFE, high-confidence cleaning fix in one shot:
        remove exact duplicates, drop key-based duplicates, fix numeric/date
        formatting, normalize obvious text inconsistencies, and fill missing
        values (numeric columns with mean, text columns with mode).

        Deliberately SKIPPED (require human judgment, so left for manual review):
        - Outliers (could be genuine extreme values, not errors)
        - Negative-value flags (could be legitimate in some contexts)
        - Fuzzy category merges (higher chance of an incorrect grouping)
        - Malformed emails (can't be auto-corrected, only flagged)

        Returns the cleaned dataframe and a list of human-readable labels
        describing what was done, for the audit log / undo snapshot.
        """
        actions_applied = []

        if df.duplicated().sum() > 0:
            df = DataCleaner.remove_duplicates(df)
            actions_applied.append("Removed exact duplicate rows")

        # Key-based duplicate removal is intentionally excluded from Clean All: repeated
        # id/code values can be legitimate and must be reviewed and approved manually.
        for issue in DataCleaner._detect_numeric_formatting_issues(df):
            df = DataCleaner.clean_numeric_format(df, issue["column"])
            actions_applied.append(f"Converted '{issue['column']}' to numeric")

        for issue in DataCleaner._detect_date_format_issues(df):
            df = DataCleaner.normalize_date_format(df, issue["column"])
            actions_applied.append(f"Standardized date format in '{issue['column']}'")

        for issue in DataCleaner._detect_inconsistent_values(df):
            df = DataCleaner.normalize_text(df, issue["column"])
            actions_applied.append(f"Normalized text in '{issue['column']}'")

        for issue in DataCleaner._detect_missing(df):
            col = issue["column"]
            if ChartEngine.is_identifier_name(col):
                continue  # Never impute identifier columns.
            if pd.api.types.is_numeric_dtype(df[col]):
                df = DataCleaner.fill_missing(df, col, "median")
                actions_applied.append(f"Filled missing '{col}' with median")
            else:
                df = DataCleaner.fill_missing(df, col, "mode")
                actions_applied.append(f"Filled missing '{col}' with most common value")

        return df, actions_applied