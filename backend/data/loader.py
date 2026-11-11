# backend/data/loader.py
import pandas as pd
import json
import io
import re
import sqlite3
from fastapi import UploadFile, HTTPException


class DataLoader:
    """
    Handles loading of .xlsx, .csv, .json, and .sql files into pandas DataFrames.
    """

    SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".json", ".sql"}

    @staticmethod
    def get_extension(filename: str) -> str:
        if "." not in filename:
            raise HTTPException(status_code=400, detail="File has no extension")
        return "." + filename.rsplit(".", 1)[-1].lower()

    @staticmethod
    def _find_leading_zero_columns(df_as_str: pd.DataFrame) -> list:
        """
        CSV and Excel files have no way to mark a value as "text" vs "number" —
        pandas has to guess the type from content alone. A column of pure
        digit-strings like '0006' or '0042' gets silently read as an integer,
        permanently losing the leading zero, BEFORE any of our cleaning logic
        ever sees it (this is standard behavior in pandas, and in Excel too).

        This scans a string-typed read of the file to find columns where a
        meaningful share of values start with '0' followed by more digits —
        the classic signature of a code/ID (product code, PIN code, employee
        code, etc.) rather than a genuine number — so they can be forced to
        stay as text on the real read.
        """
        leading_zero_cols = []
        for col in df_as_str.columns:
            series = df_as_str[col].dropna().astype(str)
            if series.empty:
                continue
            ratio = series.str.match(r"^0\d+$").mean()
            if ratio > 0.3:
                leading_zero_cols.append(col)
        return leading_zero_cols

    @staticmethod
    def _decode_text(content: bytes) -> str:
        """Decodes uploaded text, handling UTF-16 and UTF-8 BOMs and falling back to Windows-1252 / Latin-1."""
        if content.startswith((b"\xff\xfe", b"\xfe\xff")):
            return content.decode("utf-16")
        try:
            return content.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass
        try:
            return content.decode("cp1252")
        except UnicodeDecodeError:
            return content.decode("latin-1")

    @staticmethod
    def _detect_delimiter(text: str) -> str:
        """Picks the most frequent candidate delimiter on the header line (comma, semicolon, tab or pipe)."""
        header_line = next((line for line in text.splitlines() if line.strip()), "")
        counts = {sep: header_line.count(sep) for sep in (",", ";", "\t", "|")}
        best = max(counts, key=counts.get)
        return best if counts[best] > 0 else ","

    @staticmethod
    def _load_sql(content: bytes) -> pd.DataFrame:
        script = content.decode("utf-8", errors="ignore")

        # ATTACH/DETACH could let a crafted script create or open database files at arbitrary server paths.
        # VACUUM INTO can also write a database file to an arbitrary server path.
        if re.search(r"\b(ATTACH|DETACH|VACUUM)\b", script, flags=re.IGNORECASE):
            raise HTTPException(
                status_code=400,
                detail="ATTACH, DETACH and VACUUM statements are not permitted in uploaded .sql files.",
            )

        import time

        conn = sqlite3.connect(":memory:")
        script_deadline = time.monotonic() + 15
        # Abort scripts that run too long (for example unbounded recursive inserts).
        conn.set_progress_handler(lambda: 1 if time.monotonic() > script_deadline else 0, 10000)
        try:
            try:
                conn.executescript(script)
            except sqlite3.Error as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Could not execute SQL file (only SQLite-compatible syntax is supported): {e}",
                )

            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()

            if not tables:
                raise HTTPException(status_code=400, detail="No tables found in the SQL file.")

            best_table, best_count = None, -1
            for (table_name,) in tables:
                quoted_name = '"' + table_name.replace('"', '""') + '"'
                count = conn.execute(f"SELECT COUNT(*) FROM {quoted_name}").fetchone()[0]
                if count > best_count:
                    best_table, best_count = table_name, count

            quoted_best = '"' + best_table.replace('"', '""') + '"'
            return pd.read_sql(f"SELECT * FROM {quoted_best}", conn)
        finally:
            conn.close()

    @staticmethod
    async def load(file: UploadFile) -> pd.DataFrame:
        ext = DataLoader.get_extension(file.filename)

        if ext not in DataLoader.SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{ext}'. Supported: .csv, .xlsx, .json, .sql"
            )

        content = await file.read()

        try:
            if ext == ".csv":
                # First pass: read everything as text, to detect leading-zero
                # code columns before pandas gets a chance to convert them.
                csv_text = DataLoader._decode_text(content)
                csv_sep = DataLoader._detect_delimiter(csv_text)
                # Only a sample is needed to detect leading-zero code columns; the full file is parsed once below.
                raw_str_df = pd.read_csv(io.StringIO(csv_text), sep=csv_sep, dtype=str, nrows=5000)
                protected_cols = DataLoader._find_leading_zero_columns(raw_str_df)

                if protected_cols:
                    dtype_overrides = {col: str for col in protected_cols}
                    df = pd.read_csv(io.StringIO(csv_text), sep=csv_sep, dtype=dtype_overrides)
                else:
                    df = pd.read_csv(io.StringIO(csv_text), sep=csv_sep)

                # Release the decoded text and the raw upload bytes before the rest of the request runs.
                del csv_text
                content = b""

            elif ext == ".xlsx":
                excel_file = pd.ExcelFile(io.BytesIO(content))
                # Use the sheet with the most non-empty rows instead of blindly taking the first sheet.
                best_sheet, raw_str_df, best_rows = None, None, -1
                for sheet_name in excel_file.sheet_names:
                    # A bounded sample is enough to pick the busiest sheet and to detect leading-zero code columns.
                    candidate = excel_file.parse(sheet_name, dtype=str, nrows=5000)
                    candidate_rows = len(candidate.dropna(how="all"))
                    if candidate_rows > best_rows:
                        best_sheet, raw_str_df, best_rows = sheet_name, candidate, candidate_rows
                if raw_str_df is None:
                    raise ValueError("The Excel file contains no sheets")
                protected_cols = DataLoader._find_leading_zero_columns(raw_str_df)

                if protected_cols:
                    dtype_overrides = {col: str for col in protected_cols}
                    df = excel_file.parse(best_sheet, dtype=dtype_overrides)
                else:
                    df = excel_file.parse(best_sheet)

            elif ext == ".json":
                data = json.loads(DataLoader._decode_text(content))
                if isinstance(data, list):
                    df = pd.DataFrame(data)
                elif isinstance(data, dict):
                    # A wrapper object such as {"data": [ {...}, {...} ]} is unwrapped into one row per record.
                    record_lists = [
                        value for value in data.values()
                        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value)
                    ]
                    if len(record_lists) == 1:
                        df = pd.json_normalize(record_lists[0])
                    else:
                        df = pd.json_normalize(data)
                else:
                    raise ValueError("Unsupported JSON structure")

            elif ext == ".sql":
                df = DataLoader._load_sql(content)

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

        if df.empty:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        return df