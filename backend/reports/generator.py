# backend/reports/generator.py
import io
import os
import re
import contextvars
import pandas as pd
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from typing import Dict, Any, Optional

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

from backend.data.profiler import DataProfiler
from backend.data.cleaner import DataCleaner
from backend.visualization.charts import ChartEngine

# Folder where generated report files will be temporarily saved
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Generated files are removed once they are older than this window. Anything younger may still be
# streaming to a client or being read for delivery, so it is never touched.
REPORT_RETENTION_SECONDS = 3600
_CLEANUP_EXTENSIONS = (".pdf", ".xlsx", ".pptx", ".json", ".sql", ".csv", ".png", ".tmp")


def cleanup_old_reports(max_age_seconds: int = REPORT_RETENTION_SECONDS) -> int:
    """
    Deletes generated report/export files (and leftover temporary files) older than max_age_seconds.
    Never raises: a file that is locked, already gone or unreadable is skipped and retried on the next sweep.
    Returns the number of files removed.
    """
    import time

    removed = 0
    cutoff = time.time() - max(1, int(max_age_seconds))
    try:
        names = os.listdir(OUTPUT_DIR)
    except OSError:
        return 0

    for name in names:
        if not name.lower().endswith(_CLEANUP_EXTENSIONS):
            continue
        path = os.path.join(OUTPUT_DIR, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            continue
    return removed


# Common Unicode characters (often produced by LLMs) that the base PDF font
# (Helvetica, latin-1 only) cannot render. Map them to safe ASCII equivalents.
UNICODE_REPLACEMENTS = {
    "\u2014": "-",   # em dash —
    "\u2013": "-",   # en dash –
    "\u2018": "'",   # left single quote '
    "\u2019": "'",   # right single quote '
    "\u201c": '"',   # left double quote "
    "\u201d": '"',   # right double quote "
    "\u2026": "...", # ellipsis …
    "\u2022": "-",   # bullet •
    "\u00a0": " ",   # non-breaking space
}

AI_DISCLAIMER = "AI-generated text. Verify important figures and conclusions against the source data."


def _reset_pdf_x(pdf):
    """Moves the PDF cursor back to the left margin after multi_cell calls."""
    left_margin = getattr(pdf, "l_margin", getattr(pdf, "lMargin", 10))
    pdf.set_x(left_margin)


def _methodology_lines(df, profile, issues):
    lines = []

    try:
        rows = int(profile.get("num_rows", len(df)))
    except Exception:
        rows = int(len(df))

    try:
        cols = int(profile.get("num_columns", len(df.columns)))
    except Exception:
        cols = int(len(df.columns))

    lines.append(f"Dataset lineage: {rows} rows and {cols} columns were used for deterministic statistics.")
    lines.append("Key metrics are computed from the current dataset without imputation; missing values are excluded from each statistic.")
    lines.append("Identifier-like numeric columns are excluded from KPI cards when detected by the chart engine.")

    try:
        kpi_method = ChartEngine.kpi_methodology(df)

        excluded = kpi_method.get("columns_excluded_identifier_like") or []
        if excluded:
            shown = ", ".join(str(c) for c in list(excluded)[:8])
            suffix = ", ..." if len(excluded) > 8 else ""
            lines.append(f"Identifier-like columns excluded from KPIs: {shown}{suffix}.")

        all_missing = kpi_method.get("columns_excluded_all_missing") or []
        if all_missing:
            shown = ", ".join(str(c) for c in list(all_missing)[:8])
            suffix = ", ..." if len(all_missing) > 8 else ""
            lines.append(f"All-missing columns excluded from KPIs: {shown}{suffix}.")

        missing = kpi_method.get("missing_values_ignored") or {}
        if missing:
            items = list(missing.items())[:8]
            shown = ", ".join(f"{c}={n}" for c, n in items)
            suffix = ", ..." if len(missing) > 8 else ""
            lines.append(f"Missing values ignored in KPI statistics: {shown}{suffix}.")
    except Exception:
        pass

    if isinstance(issues, dict):
        dup = issues.get("duplicate_rows") or {}
        if isinstance(dup, dict) and dup.get("message"):
            lines.append(f"Duplicate-row check: {dup['message']}")

        missing_list = issues.get("missing_values") or []
        if missing_list:
            lines.append(f"Missing-value issues were reported for {len(missing_list)} column(s).")
        else:
            lines.append("No missing-value issues were reported by the data-quality check.")

        outlier_list = issues.get("outliers") or []
        if outlier_list:
            lines.append(f"Outlier issues were reported for {len(outlier_list)} column(s); outliers remain in deterministic metrics unless cleaned.")
        else:
            lines.append("No outlier issues were reported by the data-quality check.")

    lines.append("AI-written report sections are labeled separately. Deterministic sections are calculated from the dataset and are not generated by an AI model.")
    return lines


# True while a PDF is being built with a registered Unicode font (so non-Latin text can be kept).
_PDF_UNICODE_FONT = contextvars.ContextVar("pdf_unicode_font", default=False)


def sanitize_text(text: str, allow_unicode: bool = False) -> str:
    """
    Replaces Unicode characters that the base PDF font can't render,
    and strips markdown bold/italic markers (**text**) since the base
    font doesn't support them either. Any remaining unsupported character
    is dropped instead of crashing the PDF generation.
    """
    if not text:
        return ""

    for unicode_char, replacement in UNICODE_REPLACEMENTS.items():
        text = text.replace(unicode_char, replacement)

    # Remove markdown bold/italic markers like **word** or *word*
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)

    # Unicode-capable targets (PPTX, or a PDF with a registered Unicode font) keep the text as is.
    if allow_unicode or _PDF_UNICODE_FONT.get():
        return text

    # The base PDF font is latin-1 only: mark unsupported characters visibly instead of dropping them silently.
    return text.encode("latin-1", errors="replace").decode("latin-1")


# Fonts that cover non-Latin scripts such as Devanagari. Set REPORT_UNICODE_FONT to a .ttf path to override.
_UNICODE_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\Nirmala.ttf",
    r"C:\Windows\Fonts\arialuni.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]


def _find_unicode_font() -> Optional[str]:
    candidates = [os.environ.get("REPORT_UNICODE_FONT", "").strip()] + _UNICODE_FONT_CANDIDATES
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


class _ReportPDF(FPDF):
    """FPDF that transparently swaps the built-in Helvetica for a registered Unicode font when one is available."""

    unicode_family = None

    def set_font(self, family=None, style="", size=0):
        if self.unicode_family and family and str(family).lower() == "helvetica":
            family = self.unicode_family
            style = "B" if "B" in str(style).upper() else ""
        return super().set_font(family, style, size)


class ReportGenerator:
    """
    Combines the outputs of all other agents (profiler, cleaner, KPIs, insights)
    into a downloadable Excel or PDF report.
    """

    @staticmethod
    def _safe_filename(dataset_id: str) -> str:
        # Remove characters that are unsafe for filenames
        return "".join(c if c.isalnum() or c in "._-" else "_" for c in dataset_id)

    @staticmethod
    def generate_excel(df: pd.DataFrame, dataset_id: str) -> str:
        """
        Builds a multi-sheet Excel workbook: cleaned data, KPI summary,
        and column profile. Returns the file path of the generated .xlsx file.
        """
        profile = DataProfiler.profile(df)
        kpis = ChartEngine.kpi_cards(df)

        safe_name = ReportGenerator._safe_filename(dataset_id)
        file_path = os.path.join(OUTPUT_DIR, f"{safe_name}_report.xlsx")

        kpi_df = (
            pd.DataFrame(kpis)
            if kpis
            else pd.DataFrame(columns=["column", "total", "average", "median", "min", "max"])
        )

        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Cleaned_Data", index=False)
            kpi_df.to_excel(writer, sheet_name="Summary_KPIs", index=False)
            pd.DataFrame(profile["columns"]).to_excel(writer, sheet_name="Column_Profile", index=False)

        return file_path

    @staticmethod
    def generate_excel_legacy(df: pd.DataFrame, dataset_id: str) -> str:
        """
        Builds a multi-sheet Excel report: raw data, column profile, KPIs, and data quality issues.
        Returns the file path of the generated .xlsx file.
        """
        profile = DataProfiler.profile(df)
        kpis = ChartEngine.kpi_cards(df)
        issues = DataCleaner.detect_issues(df)

        safe_name = ReportGenerator._safe_filename(dataset_id)
        file_path = os.path.join(OUTPUT_DIR, f"{safe_name}_report.xlsx")

        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Data", index=False)

            pd.DataFrame(profile["columns"]).to_excel(writer, sheet_name="Column Profile", index=False)

            if kpis:
                pd.DataFrame(kpis).to_excel(writer, sheet_name="KPIs", index=False)

            issue_rows = [{"Issue": "Duplicate Rows", "Details": issues["duplicate_rows"]["message"]}]
            for m in issues["missing_values"]:
                issue_rows.append({
                    "Issue": f"Missing values in '{m['column']}'",
                    "Details": f"{m['missing_count']} missing ({m['missing_percent']}%)",
                })
            for o in issues["outliers"]:
                issue_rows.append({
                    "Issue": f"Outliers in '{o['column']}'",
                    "Details": f"{o['outlier_count']} outlier(s), expected range {o['lower_bound']} to {o['upper_bound']}",
                })
            pd.DataFrame(issue_rows).to_excel(writer, sheet_name="Data Quality", index=False)

        return file_path

    @staticmethod
    def generate_pdf(
        df: pd.DataFrame,
        dataset_id: str,
        executive_summary: Optional[str] = None,
        anomaly_summary: Optional[str] = None,
        forecast_summary: Optional[str] = None,
        chart_image_bytes: Optional[bytes] = None,
        logo_bytes: Optional[bytes] = None,
        accent_color: Optional[str] = None,
        recommendations: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> str:
        """
        Builds a text-based PDF report summarizing the dataset.
        chart_image_bytes / logo_bytes / accent_color are optional premium
        additions: an embedded chart picture, a custom company/college logo
        in the header, and a brand color used for section headings instead
        of the default.
        """
        profile = DataProfiler.profile(df)
        kpis = ChartEngine.kpi_cards(df)
        issues = DataCleaner.detect_issues(df)

        def hex_to_rgb(hex_color: str, fallback=(27, 36, 48)):
            try:
                hex_color = hex_color.lstrip("#")
                return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
            except Exception:
                return fallback

        heading_color = hex_to_rgb(accent_color) if accent_color else (27, 36, 48)

        pdf = _ReportPDF()
        unicode_token = None
        font_path = _find_unicode_font()
        if font_path:
            try:
                pdf.add_font("ReportUnicode", "", font_path)
                pdf.add_font("ReportUnicode", "B", font_path)
                pdf.unicode_family = "ReportUnicode"
                unicode_token = _PDF_UNICODE_FONT.set(True)
            except Exception:
                pdf.unicode_family = None
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # ---- Header: logo (if provided) + title ----
        if logo_bytes:
            try:
                pdf.image(io.BytesIO(logo_bytes), x=10, y=8, h=15)
                pdf.ln(18)
            except Exception:
                pass  # A corrupt logo must never break report generation.

        pdf.set_font("Helvetica", "B", 18)
        pdf.set_text_color(*heading_color)
        pdf.cell(0, 12, "Data Analytics Report", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 8, sanitize_text(f"Dataset: {display_name or dataset_id}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

        # ---- Executive Summary ----
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(*heading_color)
        pdf.cell(0, 10, "Executive Summary", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)

        if executive_summary:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(110, 110, 110)
            pdf.multi_cell(0, 5, sanitize_text(AI_DISCLAIMER))
            _reset_pdf_x(pdf)
            pdf.set_text_color(0, 0, 0)

        pdf.set_font("Helvetica", "", 11)
        summary_text = sanitize_text(executive_summary or "No summary available.")
        pdf.multi_cell(0, 7, summary_text)
        _reset_pdf_x(pdf)
        pdf.ln(3)

        # ---- Chart (premium only) ----
        if chart_image_bytes:
            try:
                pdf.set_font("Helvetica", "B", 14)
                pdf.set_text_color(*heading_color)
                pdf.cell(0, 10, "Key Trend", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_text_color(0, 0, 0)
                page_width = pdf.w - 20
                pdf.image(io.BytesIO(chart_image_bytes), x=10, w=page_width)
                pdf.ln(5)
            except Exception:
                pdf.set_text_color(0, 0, 0)  # An unreadable chart image must never break report generation.

        # ---- Key Metrics ----
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(*heading_color)
        pdf.cell(0, 10, "Key Metrics", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 7, f"Rows: {profile['num_rows']}   Columns: {profile['num_columns']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        for kpi in kpis:
            pdf.cell(
                0, 7,
                sanitize_text(
                    f"- {kpi['column']}: total={kpi['total']}, average={kpi['average']}, "
                    f"median={kpi.get('median', 'n/a')}, min={kpi['min']}, max={kpi['max']}"
                ),
                new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )
        pdf.ln(3)

        # ---- Data Quality Notes ----
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(*heading_color)
        pdf.cell(0, 10, "Data Quality Notes", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 7, sanitize_text(issues["duplicate_rows"]["message"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if issues["missing_values"]:
            for m in issues["missing_values"]:
                pdf.cell(0, 7, sanitize_text(f"- '{m['column']}': {m['missing_count']} missing values ({m['missing_percent']}%)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        else:
            pdf.cell(0, 7, "No missing values detected.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if issues["outliers"]:
            for o in issues["outliers"]:
                pdf.cell(0, 7, sanitize_text(f"- '{o['column']}': {o['outlier_count']} outlier(s) detected"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)

        # ---- Methodology & Data Lineage ----
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(*heading_color)
        pdf.cell(0, 10, "Methodology & Data Lineage", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 10)
        for line in _methodology_lines(df, profile, issues):
            pdf.multi_cell(0, 6, sanitize_text(f"- {line}"))
            _reset_pdf_x(pdf)
        pdf.ln(3)

        # ---- Recommendations (optional) ----
        if recommendations:
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(*heading_color)
            pdf.cell(0, 10, "Recommendations", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0)

            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(110, 110, 110)
            pdf.multi_cell(0, 5, sanitize_text(AI_DISCLAIMER))
            _reset_pdf_x(pdf)
            pdf.set_text_color(0, 0, 0)

            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 7, sanitize_text(recommendations))
            _reset_pdf_x(pdf)
            pdf.ln(3)

        # ---- Anomalies (optional) ----
        if anomaly_summary:
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(*heading_color)
            pdf.cell(0, 10, "Anomalies", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0)

            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(110, 110, 110)
            pdf.multi_cell(0, 5, sanitize_text(AI_DISCLAIMER))
            _reset_pdf_x(pdf)
            pdf.set_text_color(0, 0, 0)

            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 7, sanitize_text(anomaly_summary))
            _reset_pdf_x(pdf)
            pdf.ln(3)

        # ---- Forecast (optional) ----
        if forecast_summary:
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(*heading_color)
            pdf.cell(0, 10, "Forecast", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 7, sanitize_text(forecast_summary))
            _reset_pdf_x(pdf)
            pdf.ln(3)

        safe_name = ReportGenerator._safe_filename(dataset_id)
        file_path = os.path.join(OUTPUT_DIR, f"{safe_name}_report.pdf")
        pdf.output(file_path)
        if unicode_token is not None:
            _PDF_UNICODE_FONT.reset(unicode_token)

        return file_path

    @staticmethod
    def generate_pptx(
        df: pd.DataFrame,
        dataset_id: str,
        executive_summary: str = None,
        recommendations: Optional[str] = None,
        anomaly_summary: Optional[str] = None,
        forecast_summary: Optional[str] = None,
        chart_image_bytes: Optional[bytes] = None,
        logo_bytes: Optional[bytes] = None,
        accent_color: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> str:
        """
        Builds a slide-deck report: title slide (with optional logo), key metrics, data quality,
        executive summary, optional chart, recommendations, anomalies and forecast slides.
        """
        profile = DataProfiler.profile(df)
        kpis = ChartEngine.kpi_cards(df)
        issues = DataCleaner.detect_issues(df)

        prs = Presentation()

        def _accent_rgb(hex_color):
            try:
                h = hex_color.lstrip("#")
                return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            except Exception:
                return None

        accent_rgb = _accent_rgb(accent_color) if accent_color else None

        def _style_title(slide_obj):
            if accent_rgb is None:
                return
            for paragraph in slide_obj.shapes.title.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.color.rgb = accent_rgb

        # Slide 1: Title
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = "Data Analytics Report"
        slide.placeholders[1].text = sanitize_text(f"Dataset: {display_name or dataset_id}", allow_unicode=True)
        if logo_bytes:
            try:
                slide.shapes.add_picture(io.BytesIO(logo_bytes), Inches(0.4), Inches(0.3), height=Inches(0.9))
            except Exception:
                pass  # A corrupt logo must never break report generation.

        # Slide 2: Key Metrics
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "Key Metrics"
        body = slide.placeholders[1].text_frame
        body.text = f"Rows: {profile['num_rows']}   Columns: {profile['num_columns']}"
        for kpi in kpis:
            p = body.add_paragraph()
            p.text = f"{kpi['column']}: avg={kpi['average']}, median={kpi['median']}, min={kpi['min']}, max={kpi['max']}"
            p.level = 1

        # Slide 3: Data Quality
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "Data Quality"
        body = slide.placeholders[1].text_frame
        body.text = sanitize_text(issues["duplicate_rows"]["message"])
        for m in issues["missing_values"]:
            p = body.add_paragraph()
            p.text = f"Missing in '{m['column']}': {m['missing_count']} ({m['missing_percent']}%)"
            p.level = 1

        def add_text_slide(title_text, body_text, disclaimer=None):
            text_slide = prs.slides.add_slide(prs.slide_layouts[1])
            text_slide.shapes.title.text = title_text
            frame = text_slide.placeholders[1].text_frame
            frame.text = sanitize_text(body_text, allow_unicode=True)
            frame.word_wrap = True
            for paragraph in frame.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(16)

            if disclaimer:
                note = frame.add_paragraph()
                note.text = sanitize_text(disclaimer, allow_unicode=True)
                note.level = 0
                for run in note.runs:
                    run.font.size = Pt(10)
                    run.font.italic = True
                    run.font.color.rgb = RGBColor(100, 100, 100)

        methodology_text = "\n".join(f"• {line}" for line in _methodology_lines(df, profile, issues))
        add_text_slide("Methodology & Data Lineage", methodology_text)

        # Slide 4: Executive Summary
        if executive_summary:
            add_text_slide("Executive Summary", executive_summary, AI_DISCLAIMER)

        if chart_image_bytes:
            try:
                chart_slide = prs.slides.add_slide(prs.slide_layouts[5])
                chart_slide.shapes.title.text = "Key Trend"
                chart_slide.shapes.add_picture(
                    io.BytesIO(chart_image_bytes),
                    Inches(0.5),
                    Inches(1.5),
                    width=prs.slide_width - Inches(1.0),
                )
            except Exception:
                pass  # An unreadable chart image must never break report generation.

        if recommendations:
            add_text_slide("Recommendations", recommendations, AI_DISCLAIMER)

        if anomaly_summary:
            add_text_slide("Anomalies", anomaly_summary, AI_DISCLAIMER)

        if forecast_summary:
            add_text_slide("Forecast", forecast_summary)

        for styled_slide in prs.slides:
            if styled_slide.shapes.title is not None:
                _style_title(styled_slide)

        safe_name = ReportGenerator._safe_filename(dataset_id)
        file_path = os.path.join(OUTPUT_DIR, f"{safe_name}_report.pptx")
        prs.save(file_path)

        return file_path

    @staticmethod
    def generate_csv(df: pd.DataFrame, dataset_id: str) -> str:
        """Exports the cleaned dataset as a CSV file."""
        safe_name = ReportGenerator._safe_filename(dataset_id)
        file_path = os.path.join(OUTPUT_DIR, f"{safe_name}_data.csv")
        df.to_csv(file_path, index=False)
        return file_path

    @staticmethod
    def generate_json(df: pd.DataFrame, dataset_id: str) -> str:
        """Exports the cleaned dataset as a JSON file (list of records)."""
        safe_name = ReportGenerator._safe_filename(dataset_id)
        file_path = os.path.join(OUTPUT_DIR, f"{safe_name}_data.json")
        df.to_json(file_path, orient="records", indent=2, date_format="iso")
        return file_path

    @staticmethod
    def generate_sql_script(df: pd.DataFrame, dataset_id: str, table_name: str = "data") -> str:
        """
        Exports the cleaned dataset as a plain SQL script (CREATE TABLE +
        INSERT statements) that can be run against MySQL, PostgreSQL,
        SQLite, or most other SQL databases.
        """
        safe_name = ReportGenerator._safe_filename(dataset_id)
        file_path = os.path.join(OUTPUT_DIR, f"{safe_name}_data.sql")

        def sql_type(dtype) -> str:
            if pd.api.types.is_integer_dtype(dtype):
                return "INTEGER"
            if pd.api.types.is_float_dtype(dtype):
                return "REAL"
            return "TEXT"

        def sql_value(v) -> str:
            if pd.isna(v):
                return "NULL"
            if isinstance(v, (int, float)):
                return str(v)
            return "'" + str(v).replace("'", "''") + "'"

        safe_table = "".join(c if c.isalnum() or c == "_" else "_" for c in table_name) or "data"
        # ANSI double-quoted identifiers (SQLite/PostgreSQL); sanitized names are made unique.
        used_names = set()
        safe_columns = []
        for original_name in df.columns:
            base = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(original_name)) or "column"
            candidate = base
            suffix = 2
            while candidate.lower() in used_names:
                candidate = f"{base}_{suffix}"
                suffix += 1
            used_names.add(candidate.lower())
            safe_columns.append('"' + candidate + '"')

        lines = [f"CREATE TABLE {safe_table} ("]
        col_defs = [f"  {safe_columns[i]} {sql_type(df.iloc[:, i].dtype)}" for i in range(len(df.columns))]
        lines.append(",\n".join(col_defs))
        lines.append(");\n")

        for _, row in df.iterrows():
            values = ", ".join(sql_value(v) for v in row.tolist())
            lines.append(f"INSERT INTO {safe_table} ({', '.join(safe_columns)}) VALUES ({values});")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return file_path