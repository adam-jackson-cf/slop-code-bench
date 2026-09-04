from decimal import Decimal
from itertools import combinations

import pytest

from slop_code.metrics.scoring import WEIGHTS
from slop_code.metrics.scoring import BenchmarkScore
from slop_code.metrics.scoring import CheckpointCorrectnessEvidence
from slop_code.metrics.scoring import calculate_problem_score
from slop_code.metrics.scoring import ranking_key
from slop_code.metrics.scoring.sensitivity import COMPONENT_NAMES
from slop_code.metrics.scoring.sensitivity import SensitivityError
from slop_code.metrics.scoring.sensitivity import component_correlations
from slop_code.metrics.scoring.sensitivity import controlled_fixture_scores
from slop_code.metrics.scoring.sensitivity import exact_score_delta
from slop_code.metrics.scoring.sensitivity import require_independent_components
from slop_code.metrics.scoring.sensitivity import weight_ablations

D = Decimal
FROZEN_WEIGHTS = {
    "verbosity": D("0.15"),
    "erosion": D("0.15"),
    "architecture": D("0.20"),
    "rework": D("0.30"),
    "regression": D("0.20"),
}


def benchmark(score):
    return BenchmarkScore(
        problems=(score,),
        benchmark_score=score.score,
        correctness=score.components.correctness,
        inertia=score.components.inertia,
        cost_per_configured_checkpoint=D("0"),
        run_identity=score.problem_id,
    )


def test_matched_correctness_single_component_fixtures_have_exact_score_losses():
    scores = controlled_fixture_scores()
    baseline = scores["baseline"]

    assert baseline.components.correctness == D("1.000000000000")
    for component in COMPONENT_NAMES:
        changed = scores[component]
        assert changed.components.correctness == baseline.components.correctness
        assert baseline.score - changed.score == exact_score_delta(
            component, D("1")
        )


def test_h_r_g_change_equal_correctness_ordering_and_minor_changes_are_continuous():
    scores = controlled_fixture_scores()
    baseline = scores["baseline"]
    for component in ("architecture", "rework", "regression"):
        assert ranking_key(benchmark(baseline)) < ranking_key(
            benchmark(scores[component])
        )
    assert ranking_key(benchmark(scores["architecture"])) < ranking_key(
        benchmark(scores["rework"])
    )

    small = controlled_fixture_scores(D("0.01"))
    for component in COMPONENT_NAMES:
        assert small["baseline"].score - small[
            component
        ].score == exact_score_delta(component, D("0.01"))


def test_ablations_are_order_independent_and_do_not_mutate_frozen_weights():
    scores = controlled_fixture_scores()
    ordered = tuple(scores.values())
    ablations = weight_ablations(ordered)

    assert WEIGHTS == FROZEN_WEIGHTS
    assert ablations == weight_ablations(reversed(ordered))
    assert (
        ablations["rework"] > ablations["architecture"] > ablations["verbosity"]
    )
    assert ablations["regression"] > ablations["erosion"]


def test_component_correlations_prove_independent_perturbations_and_reject_redundancy():
    scores = tuple(controlled_fixture_scores().values())
    correlations = component_correlations(reversed(scores))

    assert set(correlations) == set(combinations(COMPONENT_NAMES, 2))
    assert set(correlations.values()) == {D("-0.2")}
    require_independent_components(scores)

    correctness = tuple(
        CheckpointCorrectnessEvidence(
            checkpoint_id=f"c{index}", passed=1, total=1, rate=D("1")
        )
        for index in range(2)
    )
    redundant = tuple(
        calculate_problem_score(
            f"redundant-{value}",
            correctness,
            verbosity=(value, value),
            erosion=(value, value),
            architecture=(D("1"), D("1")),
            rework=(D("1"),),
            regression=(D("1"),),
        )
        for value in (D("0"), D("1"))
    )
    with pytest.raises(SensitivityError, match="functionally redundant"):
        require_independent_components(redundant)
