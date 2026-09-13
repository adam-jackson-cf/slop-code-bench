import dash
import dash_bootstrap_components as dbc
from dash import Input
from dash import Output
from dash import State
from dash import callback
from dash import dcc
from dash import html

from slop_code.dashboard.components import loading_graph
from slop_code.dashboard.graphs.comparison import build_problem_comparison_chart
from slop_code.dashboard.page_context import build_context
from slop_code.dashboard.page_context import empty_figure

dash.register_page(__name__, path="/problem_comparison")

layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H3(
                    "Problem Comparison",
                    className="display-6 fw-bold text-primary mb-4",
                )
            )
        ),
        dbc.Card(
            [
                dbc.CardHeader(
                    [
                        html.Label("Select Problem:", className="fw-bold me-2"),
                        html.Div(
                            dcc.Dropdown(
                                id="problem-selector",
                                placeholder="Select a problem...",
                                style={"color": "#000"},
                            ),
                            style={"flexGrow": 1},
                        ),
                    ],
                    className="d-flex align-items-center bg-light",
                ),
                dbc.CardBody(
                    loading_graph("problem-comparison-graph", height="80vh")
                ),
            ],
            className="shadow-sm border-0",
        ),
    ],
    fluid=True,
    className="py-3",
)


def _build_problem_context(selected_paths, filter_settings):
    filter_settings = filter_settings or {}
    return build_context(
        selected_paths,
        use_generic_colors=bool(filter_settings.get("disable_colors", [])),
        group_runs=bool(filter_settings.get("group_runs", False)),
        common_problems_only=bool(
            filter_settings.get("common_problems_only", False)
        ),
    )


@callback(
    [
        Output("problem-selector", "options"),
        Output("problem-selector", "value"),
    ],
    [
        Input("selected-runs-store", "data"),
        Input("filter-settings-store", "data"),
    ],
    State("problem-selector", "value"),
)
def update_problem_options(selected_paths, filter_settings, selected_problem):
    context = _build_problem_context(selected_paths, filter_settings)
    if context is None or context.checkpoints.empty:
        return [], None
    if "problem" not in context.checkpoints.columns:
        return [], None

    problems = sorted(context.checkpoints["problem"].dropna().unique())
    options = [{"label": problem, "value": problem} for problem in problems]
    value = selected_problem if selected_problem in problems else None
    return options, value


@callback(
    Output("problem-comparison-graph", "figure"),
    [
        Input("selected-runs-store", "data"),
        Input("problem-selector", "value"),
        Input("filter-settings-store", "data"),
    ],
)
def update_graph(selected_paths, selected_problem, filter_settings):
    if not selected_problem:
        return empty_figure()

    context = _build_problem_context(selected_paths, filter_settings)
    if context is None:
        return empty_figure()
    return build_problem_comparison_chart(context, selected_problem)
