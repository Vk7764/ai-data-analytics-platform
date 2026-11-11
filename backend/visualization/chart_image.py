# backend/visualization/chart_image.py
import matplotlib
matplotlib.use("Agg")  # no GUI needed — safe for a server environment
from matplotlib.figure import Figure
import pandas as pd
import io
from typing import Literal, Optional

from backend.visualization.charts import ChartEngine

TEAL = "#0e7c66"


class ChartImageExporter:
    """
    Renders static, print-quality chart images (PNG, SVG, or PDF) from a
    dataset — separate from ChartEngine's JSON output (which only feeds
    the interactive frontend charts, though both share the same underlying
    aggregation logic). Used for the "download as image" premium feature
    and for embedding charts into PDF reports.
    """

    @staticmethod
    def _style_axes(ax, x_col: str, y_col: str, title: str) -> None:
        ax.set_xlabel(x_col, fontsize=11)
        ax.set_ylabel(y_col, fontsize=11)
        ax.set_title(title, fontsize=14, fontweight="medium", pad=14)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#d7dbd3")
        ax.spines["bottom"].set_color("#d7dbd3")
        ax.grid(axis="y", linestyle="--", alpha=0.3, linewidth=0.7)
        ax.set_axisbelow(True)

    @staticmethod
    def _limit_xticks(ax, total_points: int, max_labels: int = 20) -> None:
        if total_points <= max_labels:
            return
        step = max(1, total_points // max_labels)
        ticks = ax.get_xticks()
        ax.set_xticks(ticks[::step])

    @staticmethod
    def _rotate_xticks(ax) -> None:
        ax.tick_params(axis="x", labelrotation=35)
        for label in ax.get_xticklabels():
            label.set_horizontalalignment("right")

    @staticmethod
    def render(
        df: pd.DataFrame,
        x_column: str = None,
        y_column: str = None,
        fmt: Literal["png", "svg", "pdf"] = "png",
        dpi: int = 200,
        agg: str = "sum",
        note: Optional[str] = None,
    ) -> bytes:
        chart = ChartEngine.suggest_chart(df, x_column, y_column, agg=agg)

        if chart["chart_type"] == "table" or not chart["data"]:
            raise ValueError("Not enough data to generate a chart for this dataset.")

        chart_type = chart["chart_type"]
        x_col = chart["x_column"]
        y_col = chart["y_column"]
        data = pd.DataFrame(chart["data"])

        # A private Figure instance keeps rendering independent of matplotlib's global pyplot state.
        fig = Figure(figsize=(9, 5.5))
        ax = fig.subplots()

        if chart_type == "bar":
            ax.bar(data[x_col].astype(str), data[y_col], color=TEAL, width=0.65)
            ChartImageExporter._limit_xticks(ax, len(data))
            ChartImageExporter._rotate_xticks(ax)
        elif chart_type == "line":
            x_labels = data[x_col].astype(str)
            ax.plot(x_labels, data[y_col], color=TEAL, linewidth=2, marker="o", markersize=4)
            ax.fill_between(range(len(x_labels)), data[y_col], color=TEAL, alpha=0.12)
            ChartImageExporter._limit_xticks(ax, len(data))
            ChartImageExporter._rotate_xticks(ax)
        elif chart_type == "scatter":
            ax.scatter(data[x_col], data[y_col], color=TEAL, alpha=0.7, edgecolors="white", linewidths=0.5)
        else:
            raise ValueError(f"Unsupported chart type for image export: {chart_type}")

        title = f"{y_col} by {x_col}"
        if chart_type in ("bar", "line"):
            title = f"{title} ({chart.get('agg', 'sum')})"
        ChartImageExporter._style_axes(ax, x_col, y_col, title)
        if note:
            fig.text(0.5, 0.01, f"Note: {note[:140]}", ha="center", fontsize=8.5, color="#5c564e", style="italic")
        if note:
            fig.tight_layout(rect=(0, 0.04, 1, 1))
        else:
            fig.tight_layout()

        buffer = io.BytesIO()
        fig.savefig(buffer, format=fmt, dpi=dpi)
        buffer.seek(0)
        return buffer.getvalue()

    @staticmethod
    def render_timeseries(
        df: pd.DataFrame,
        date_column: str,
        value_column: str,
        granularity: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        fmt: Literal["png", "svg", "pdf"] = "png",
        dpi: int = 200,
        note: Optional[str] = None,
        ma_window: int = 0,
    ) -> bytes:
        """
        Renders exactly the drilled-down time-series view the user is
        currently looking at on screen (same granularity and date range),
        so the downloaded image matches what they explored interactively.
        """
        chart = ChartEngine.time_series_chart(df, date_column, value_column, granularity, start, end)
        data = pd.DataFrame(chart["data"])

        if data.empty:
            raise ValueError("No data to export for this view.")

        fig = Figure(figsize=(9, 5.5))
        ax = fig.subplots()

        ax.bar(data[date_column].astype(str), data[value_column], color=TEAL, width=0.65)
        ChartImageExporter._limit_xticks(ax, len(data))
        ChartImageExporter._rotate_xticks(ax)

        # Moving-average overlay, computed the same way as in the interactive explorer
        # (trailing window over the bucket values, undefined until the window is full).
        if ma_window and int(ma_window) > 1:
            window = int(ma_window)
            numeric_values = pd.to_numeric(data[value_column], errors="coerce")
            moving_avg = numeric_values.rolling(window=window, min_periods=window).mean().round(2)
            ax.plot(
                list(range(len(data))),
                moving_avg.tolist(),
                color="#c85a32",
                linewidth=2,
                linestyle="--",
                label=f"{window}-Period Avg",
            )
            ax.legend(frameon=False)

        title = f"{value_column} by {date_column} ({chart['granularity']})"
        ChartImageExporter._style_axes(ax, date_column, value_column, title)
        if note:
            fig.text(0.5, 0.01, f"Note: {note[:140]}", ha="center", fontsize=8.5, color="#5c564e", style="italic")
            fig.tight_layout(rect=(0, 0.04, 1, 1))
        else:
            fig.tight_layout()

        buffer = io.BytesIO()
        fig.savefig(buffer, format=fmt, dpi=dpi)
        buffer.seek(0)
        return buffer.getvalue()