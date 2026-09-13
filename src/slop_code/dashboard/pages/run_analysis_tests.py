import dash
import dash_bootstrap_components as dbc
import numpy as np
import plotly.graph_objects as go
from dash import Input
from dash import Output
from dash import callback
from dash import html

from slop_code.dashboard.components import loading_graph
from slop_code.dashboard.page_context import build_context
from slop_code.dashboard.page_context import empty_figure

dash.register_page(__name__, path="/run-analysis/tests")

layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H3(
                    "Run Analysis: Test Suite",
                    className="display-6 fw-bold text-primary mb-4",
                )
            )
        ),
        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader(
                                "Overall Pass Rate by Category",
                                className="fw-bold",
                            ),
                            dbc.CardBody(
                                loading_graph("ra-test-bar", height="400px")
                            ),
                        ],
                        className="mb-4 shadow-sm border-0",
                    ),
                    md=6,
                ),
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader(
                                "Pass Rate Evolution (Normalized Progress)",
                                className="fw-bold",
                            ),
                            dbc.CardBody(
                                loading_graph(
                                    "ra-test-evolution", height="400px"
                                )
                            ),
                        ],
                        className="mb-4 shadow-sm border-0",
                    ),
                    md=6,
                ),
            ]
        ),
    ],
    fluid=True,
    className="py-3",
)


def normalize_and_bin(df, idx_col, num_bins=20):
    max_indices = df.groupby("problem")[idx_col].max()
    df = df.copy()
    df["total"] = df["problem"].map(max_indices)
    df["progress"] = df[idx_col] / df["total"].replace(0, 1) * 100
    df["bin"] = (df["progress"] / (100 / num_bins)).round() * (100 / num_bins)
    return df


@callback(
    [Output("ra-test-bar", "figure"), Output("ra-test-evolution", "figure")],
    Input("run-analysis-store", "data"),
)
def update_tests(run_path):
    if not run_path:
        return empty_figure(), empty_figure()

    context = build_context([run_path])
    if context is None or context.checkpoints.empty:
        return empty_figure(), empty_figure()

    df = context.checkpoints

    # Bar Chart
    cats = ["core", "functionality", "regression", "error"]
    avg_pass = []

    for cat in cats:
        passed_col = f"tests.{cat}.passed"
        total_col = f"tests.{cat}.total"
        if passed_col not in df.columns or total_col not in df.columns:
            avg_pass.append(None)
            continue
        measurements = df.loc[
            df[total_col].gt(0) & df[passed_col].notna(),
            [passed_col, total_col],
        ]
        total = measurements[total_col].sum()
        avg_pass.append(
            measurements[passed_col].sum() / total * 100 if total > 0 else None
        )

    bar_fig = go.Figure(
        go.Bar(
            x=cats,
            y=avg_pass,
            marker_color=["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"],
        )
    )
    bar_fig.update_layout(
        title="Pass Rate % (Avg over all checkpoints)",
        yaxis_title="Pass %",
        plot_bgcolor="white",
    )
    bar_fig.update_yaxes(range=[0, 105])

    # Evolution Line Chart
    idx_col = "idx" if "idx" in df.columns else "checkpoint"
    df_norm = normalize_and_bin(df, idx_col)

    bins = np.arange(0, 105, 5)
    evolution_fig = go.Figure()

    colors = {
        "core": "#1f77b4",
        "functionality": "#ff7f0e",
        "regression": "#2ca02c",
        "error": "#d62728",
    }

    for cat in cats:
        passed_col = f"tests.{cat}.passed"
        total_col = f"tests.{cat}.total"
        if passed_col not in df.columns or total_col not in df.columns:
            continue

        df_norm[f"_rate_{cat}"] = np.where(
            df_norm[total_col].gt(0) & df_norm[passed_col].notna(),
            df_norm[passed_col] / df_norm[total_col] * 100,
            np.nan,
        )

        # Keep bins with no measurement unavailable rather than imputing them.
        binned = df_norm.groupby("bin")[f"_rate_{cat}"].mean().reindex(bins)

        evolution_fig.add_trace(
            go.Scatter(
                x=binned.index,
                y=binned.values,
                mode="lines",
                name=cat.capitalize(),
                line=dict(color=colors[cat], width=2),
            )
        )

    evolution_fig.update_layout(
        title="Pass Rate vs Progress",
        xaxis_title="Problem Progress (%)",
        yaxis_title="Pass Rate (%)",
        plot_bgcolor="white",
        hovermode="x unified",
    )
    evolution_fig.update_yaxes(range=[0, 105])

    return bar_fig, evolution_fig
