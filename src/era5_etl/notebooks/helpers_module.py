"""Convenience helpers installed into every notebook kernel's namespace.

The kernel boot script calls :func:`install_helpers` to expose:

- ``con``: the DuckDB connection (already injected by the kernel boot).
- ``inmet_with_era5_land(station_id, start, end)``: pre-built join between
  INMET station data and the 4 surrounding ERA5-LAND grid cells. Returns a
  pandas DataFrame.
- ``plot_predictions(df_test, y_true, y_pred)``: standardised Plotly figure
  (actual vs predicted line + residuals).
- ``log_model_run(params, metrics, duration_s, notes="", model_name="xgboost")``:
  POSTs a model-run record back to the FastAPI server, which appends it to
  the notebook's ``runs[]`` list. The token is authenticated per-kernel via
  an env var so only this notebook's runs can be written.

All helpers are best-effort: if pandas/plotly/httpx are not installed the
helper raises a clear ``ModuleNotFoundError`` with the install command.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _require(mod: str) -> Any:
    """Import *mod* or raise a clear ``ModuleNotFoundError``."""
    try:
        return __import__(mod)
    except ImportError as exc:
        raise ModuleNotFoundError(
            f"Notebook helpers require '{mod}'. Install with: pip install -e ."
        ) from exc


def plot_learning_curves(
    sweep_df,
    expanding_rows,
    *,
    metric: str = "rmse",
    hours_per_month: int = 720,
):
    """Faceted learning curves: one panel per slide step + an expanding panel.

    Parameters
    ----------
    sweep_df:
        Output of ``summarize_sweep``. Must contain columns
        ``slide_step_days``, ``train_months``, ``{metric}_mean``,
        ``{metric}_std``.
    expanding_rows:
        List of dicts with keys ``n_train`` (hours) and ``{metric}``
        (scalar score for that training window size).
    metric:
        Column prefix to plot (default ``"rmse"``).
    hours_per_month:
        Divisor to convert ``n_train`` hours → months on the X axis
        (default 720 = 30 d × 24 h).

    Returns
    -------
    plotly.graph_objects.Figure
        One subplot per unique ``slide_step_days`` value, plus one final
        ``"expanding (treino cresce)"`` subplot. Subplots share the Y axis.
    """
    _require("pandas")
    go = _require("plotly").graph_objects  # type: ignore
    from plotly.subplots import make_subplots  # type: ignore

    steps = (
        sorted(sweep_df["slide_step_days"].unique().tolist())
        if len(sweep_df)
        else []
    )
    titles = [f"sliding: slide={s}d" for s in steps] + ["expanding (treino cresce)"]
    n = len(titles)
    fig = make_subplots(
        rows=1, cols=n, subplot_titles=titles, shared_yaxes=True
    )
    mean_col = f"{metric}_mean"
    std_col = f"{metric}_std"
    for col, step in enumerate(steps, start=1):
        sub = sweep_df[sweep_df["slide_step_days"] == step].sort_values(
            "train_months"
        )
        fig.add_trace(
            go.Scatter(
                x=sub["train_months"],
                y=sub[mean_col],
                error_y=dict(type="data", array=sub[std_col]),
                mode="lines+markers",
                name=f"slide={step}d",
                showlegend=False,
            ),
            row=1,
            col=col,
        )
    # Expanding panel: X axis = months of training (n_train hours → months).
    exp = sorted(expanding_rows, key=lambda r: r["n_train"])
    fig.add_trace(
        go.Scatter(
            x=[r["n_train"] / hours_per_month for r in exp],
            y=[r[metric] for r in exp],
            mode="lines+markers",
            name="expanding",
            showlegend=False,
            line=dict(color="#16a34a"),
        ),
        row=1,
        col=n,
    )
    fig.update_xaxes(title_text="meses de treino")
    fig.update_yaxes(title_text=metric.upper(), row=1, col=1)
    fig.update_layout(
        template="plotly_white",
        height=380,
        title=f"Curvas de aprendizado: {metric.upper()} x meses de treino",
        margin=dict(t=90, b=40),
    )
    return fig


def install_helpers(
    ns: dict[str, Any],
    *,
    data_dir: Path,
    notebook_id: str,
    runs_url: str,
    runs_token: str,
) -> None:
    """Populate ``ns`` with the standard helpers."""

    def _require(mod: str) -> Any:
        try:
            return __import__(mod)
        except ImportError as exc:
            raise ModuleNotFoundError(
                f"Notebook helpers require '{mod}'. Install with: "
                f"pip install -e ."
            ) from exc

    def inmet_with_era5_land(
        station_id: str,
        start: str,
        end: str,
    ):
        """Return a pandas DataFrame joining INMET + ERA5-LAND for a station.

        Columns include the INMET measurements, the lat/lon and haversine
        distance to the 4 neighbouring ERA5-LAND cells, and the temperature
        of each of those 4 cells at the same (date, hour_utc).

        Parameters
        ----------
        station_id : str
            INMET station code (e.g. ``"A001"``).
        start, end : str
            ``"YYYY-MM-DD"`` bounds (inclusive).
        """
        _require("pandas")
        con = ns["con"]
        sql = """
        WITH inmet_rows AS (
            SELECT *
            FROM inmet
            WHERE station_id = ?
              AND date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        )
        SELECT
            i.*,
            tl.temperature_2m AS era5_land_temp_tl,
            tr.temperature_2m AS era5_land_temp_tr,
            bl.temperature_2m AS era5_land_temp_bl,
            br.temperature_2m AS era5_land_temp_br
        FROM inmet_rows i
        LEFT JOIN era5_land tl
            ON tl.date = i.date
           AND tl.hour_utc = i.hour_utc
           AND abs(tl.latitude  - i.era5_land_lat_top)    < 1e-4
           AND abs(tl.longitude - i.era5_land_lon_left)   < 1e-4
        LEFT JOIN era5_land tr
            ON tr.date = i.date
           AND tr.hour_utc = i.hour_utc
           AND abs(tr.latitude  - i.era5_land_lat_top)    < 1e-4
           AND abs(tr.longitude - i.era5_land_lon_right)  < 1e-4
        LEFT JOIN era5_land bl
            ON bl.date = i.date
           AND bl.hour_utc = i.hour_utc
           AND abs(bl.latitude  - i.era5_land_lat_bottom) < 1e-4
           AND abs(bl.longitude - i.era5_land_lon_left)   < 1e-4
        LEFT JOIN era5_land br
            ON br.date = i.date
           AND br.hour_utc = i.hour_utc
           AND abs(br.latitude  - i.era5_land_lat_bottom) < 1e-4
           AND abs(br.longitude - i.era5_land_lon_right)  < 1e-4
        ORDER BY i.date, i.hour_utc
        """
        return con.execute(sql, [station_id, start, end]).df()

    def plot_predictions(df_test, y_true, y_pred):
        """Return a 2-row Plotly figure: predictions on top, residuals below."""
        _require("pandas")
        go = _require("plotly").graph_objects  # type: ignore
        from plotly.subplots import make_subplots  # type: ignore

        pd = __import__("pandas")
        # Build the x axis from df_test if it has date/hour; else range.
        if "date" in df_test.columns and "hour_utc" in df_test.columns:
            x = pd.to_datetime(df_test["date"]) + pd.to_timedelta(
                df_test["hour_utc"], unit="h"
            )
        elif "date" in df_test.columns:
            x = pd.to_datetime(df_test["date"])
        else:
            x = list(range(len(df_test)))
        # Pass a list of datetime objects so Plotly's date axis picks the tick
        # detail by zoom (dates when zoomed out, time when zoomed in).
        x = list(x)

        residuals = [a - b for a, b in zip(y_true, y_pred)]
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.06,
            row_heights=[0.7, 0.3],
            subplot_titles=("Actual vs predicted", "Residuals (actual − predicted)"),
        )
        fig.add_trace(
            go.Scatter(x=x, y=list(y_true), name="actual", mode="lines"),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(x=x, y=list(y_pred), name="predicted", mode="lines"),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(x=x, y=residuals, name="residual", mode="lines"),
            row=2,
            col=1,
        )
        # Date axis with no fixed tickformat: Plotly chooses the tick detail
        # by zoom level. hoverformat keeps the full timestamp in tooltips.
        fig.update_xaxes(type="date", hoverformat="%Y-%m-%d %H:%M")
        fig.update_layout(
            template="plotly_white",
            height=520,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=40, r=20, t=60, b=40),
        )
        return fig

    def log_model_run(
        params: dict[str, Any],
        metrics: dict[str, Any],
        duration_s: float,
        notes: str = "",
        model_name: str = "xgboost",
    ) -> dict[str, Any]:
        """POST a run record back to the server for persistence."""
        urllib_request = __import__("urllib.request", fromlist=["request"])
        import json as _json

        # Coerce non-JSON-serialisable values (numpy scalars etc.) to plain types.
        def _coerce(d: dict[str, Any]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for k, v in d.items():
                try:
                    _json.dumps(v)
                    out[str(k)] = v
                except TypeError:
                    out[str(k)] = repr(v) if not hasattr(v, "item") else v.item()
            return out

        body = _json.dumps(
            {
                "params": _coerce(params),
                "metrics": _coerce(metrics),
                "duration_s": float(duration_s),
                "notes": str(notes),
                "model_name": str(model_name),
            }
        ).encode("utf-8")
        req = urllib_request.Request(  # noqa: S310 — local server, header-auth
            runs_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Notebook-Token": runs_token,
            },
        )
        with urllib_request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return _json.loads(resp.read().decode("utf-8"))

    ns["inmet_with_era5_land"] = inmet_with_era5_land
    ns["plot_predictions"] = plot_predictions
    ns["log_model_run"] = log_model_run
    ns["plot_learning_curves"] = plot_learning_curves
