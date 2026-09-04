"""Frozen canonical scoring formula, identity, and aggregation helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN
from decimal import Decimal
from decimal import localcontext

from pydantic import BaseModel

from . import models
from .contract import PRODUCTION_QUALITY_CONTRACT
from .models import SCORE_PLACES
from .models import ZERO
from .models import BenchmarkScore
from .models import BenchmarkScoreInput
from .models import CheckpointCorrectnessEvidence
from .models import ComponentScores
from .models import ProblemScore
from .models import ProblemScoreInput
from .models import canonical_decimal

DECIMAL_CONTEXT_PRECISION = 50
WEIGHTS = {
    "verbosity": Decimal("0.15"),
    "erosion": Decimal("0.15"),
    "architecture": Decimal("0.20"),
    "rework": Decimal("0.30"),
    "regression": Decimal("0.20"),
}
FORMULAS = {
    "correctness": "C_p=sum(C_p,k)/K_p",
    "inertia": "I_p=.15V_p+.15E_p+.20H_p+.30R_p+.20G_p",
    "problem": "S_p=100*C_p*(.70+.30*I_p)",
    "benchmark": "S_b=sum(S_p)/P;C_b=sum(C_p)/P;I_b=sum(I_p)/P",
}

LINEAGE_CONTRACT = {
    "exact_identity": (
        "language",
        "kind",
        "parent_qualified_name",
        "qualified_name",
        "project_relative_path",
    ),
    "candidate_edge": "same_language_and_kind_and_any_nonempty_equal_sha256",
    "hash_acceptance": "body_and_structure_equal_and_endpoint_degrees_one",
    "ambiguous_component_id": "sha256(sorted_prior_current_identities_and_flags)",
    "line_owner": "innermost_production_symbol_once_per_physical_diff_line",
    "rework": "1-L_repeat/L_changed;one_when_denominator_zero",
    "ledger": "accepted:prior_or_mapped;ambiguous:prior_union_or_set_union_mapped",
    "gap": "reset_at_problem_boundary_and_missing_checkpoint",
}
REGRESSION_CONTRACT = {
    "environment": "exact_environment_id_project_lock_plugin_interpreter_sha256",
    "parity": "exact_environment_corpus_invocation_node_phase_outcome_ledger",
    "coverage": "contexts_join_exact_parametrized_node_id",
    "attribution": "failing_canonical_regression_to_innermost_changed_symbol",
    "deduplication": "node_path_line_symbol_stable_identity",
    "process_audit": "failing_regression_process_event_is_parity_unavailable",
    "regression": "1-affected_changed_symbols/all_changed_symbols;one_when_none",
}
EVIDENCE_PROJECTION_CONTRACT = {
    "rework_symbols": "eligible_five_item_production_quality_identity",
    "regression_groups": (
        "exact_node_or_file_qualified_id_or_unique_ledger_suffix"
    ),
    "transition": "complete_rework_and_regression_evidence_required",
}


RANKING = {
    "fields": (
        "benchmark_score:desc",
        "correctness:desc",
        "inertia:desc",
        "cost:nulls_last_asc",
        "run_identity:asc",
    )
}
PRECISION = {
    "decimal_places": format(models.DECIMAL_PLACES, "f"),
    "score_places": format(SCORE_PLACES, "f"),
    "rounding": ROUND_HALF_EVEN,
    "context_precision": DECIMAL_CONTEXT_PRECISION,
}


def canonical_json_bytes(value: object) -> bytes:
    """Serialize exact canonical bytes, including fixed-point decimals."""

    def default(item: object) -> object:
        if isinstance(item, Decimal):
            if not item.is_finite():
                raise ValueError("decimal must be finite")
            return format(item, "f")
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        raise TypeError(f"unsupported canonical value: {type(item)!r}")

    return json.dumps(
        value,
        default=default,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _model_schemas() -> dict[str, object]:
    return {
        name: value.model_json_schema()
        for name, value in sorted(vars(models).items())
        if isinstance(value, type)
        and issubclass(value, models.ScoringModel)
        and value is not models.ScoringModel
    }


def scoring_schema_bytes() -> bytes:
    """Return the exact frozen contract bytes used by ``scoring_schema_id``."""
    return canonical_json_bytes(
        {
            "formulas": FORMULAS,
            "models": _model_schemas(),
            "lineage": LINEAGE_CONTRACT,
            "precision": PRECISION,
            "regression": REGRESSION_CONTRACT,
            "production_quality": PRODUCTION_QUALITY_CONTRACT,
            "ranking": RANKING,
            "weights": WEIGHTS,
        }
    )


def scoring_schema_id() -> str:
    """Hash all canonical models, formulae, weights, precision, and ranking."""
    return hashlib.sha256(scoring_schema_bytes()).hexdigest()


def generation_formula_id(
    parser_tokenizer_schema_id: str | None,
) -> str:
    """Bind scoring and evidence projection semantics to runtime parsing."""
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "evidence_projection": EVIDENCE_PROJECTION_CONTRACT,
                "parser_tokenizer_schema_id": parser_tokenizer_schema_id,
                "scoring_schema_id": scoring_schema_id(),
            }
        )
    ).hexdigest()


def problem_key(problem_name: str) -> str:
    """Return the canonical filesystem key for an exact problem name."""
    return hashlib.sha256(problem_name.encode("utf-8")).hexdigest()


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ValueError("cannot average empty sequence")
    with localcontext() as context:
        context.prec = DECIMAL_CONTEXT_PRECISION
        context.rounding = ROUND_HALF_EVEN
        return sum(values, ZERO) / Decimal(len(values))


def _unit(value: Decimal, name: str) -> Decimal:
    if not value.is_finite() or value < ZERO or value > Decimal("1"):
        raise ValueError(f"{name} must be a finite value in [0, 1]")
    return value


def _calculate_problem(
    problem_id: str,
    checkpoint_correctness: Sequence[CheckpointCorrectnessEvidence],
    verbosity: Sequence[Decimal],
    erosion: Sequence[Decimal],
    architecture: Sequence[Decimal],
    rework: Sequence[Decimal],
    regression: Sequence[Decimal],
) -> tuple[ProblemScore, Decimal, Decimal, Decimal]:
    checkpoint_count = len(checkpoint_correctness)
    if checkpoint_count < 2:
        raise ValueError(
            "configured problem must have at least two checkpoints"
        )
    if any(
        len(values) != checkpoint_count
        for values in (verbosity, erosion, architecture)
    ):
        raise ValueError(
            "checkpoint component count must match configured checkpoints"
        )
    if any(
        len(values) != checkpoint_count - 1 for values in (rework, regression)
    ):
        raise ValueError(
            "transition component count must be one less than checkpoints"
        )
    if (
        len({item.checkpoint_id for item in checkpoint_correctness})
        != checkpoint_count
    ):
        raise ValueError("correctness checkpoint identifiers must be unique")
    sequences = (
        (tuple(item.rate for item in checkpoint_correctness), "correctness"),
        (verbosity, "verbosity"),
        (erosion, "erosion"),
        (architecture, "architecture"),
        (rework, "rework"),
        (regression, "regression"),
    )
    for values, name in sequences:
        for value in values:
            _unit(value, name)
    with localcontext() as context:
        context.prec = DECIMAL_CONTEXT_PRECISION
        context.rounding = ROUND_HALF_EVEN
        correctness = _mean(tuple(item.rate for item in checkpoint_correctness))
        values = {
            "verbosity": _mean(verbosity),
            "erosion": _mean(erosion),
            "architecture": _mean(architecture),
            "rework": _mean(rework),
            "regression": _mean(regression),
        }
        inertia = sum(
            (WEIGHTS[name] * value for name, value in values.items()), ZERO
        )
        score = (
            Decimal("100")
            * correctness
            * (Decimal("0.70") + Decimal("0.30") * inertia)
        )
    persisted = ProblemScore(
        problem_id=problem_id,
        configured_checkpoints=checkpoint_count,
        checkpoint_correctness=tuple(checkpoint_correctness),
        components=ComponentScores(
            correctness=canonical_decimal(correctness),
            verbosity=canonical_decimal(values["verbosity"]),
            erosion=canonical_decimal(values["erosion"]),
            architecture=canonical_decimal(values["architecture"]),
            rework=canonical_decimal(values["rework"]),
            regression=canonical_decimal(values["regression"]),
            inertia=canonical_decimal(inertia),
        ),
        score=canonical_decimal(score, SCORE_PLACES),
    )
    return persisted, score, correctness, inertia


def calculate_problem_score(
    problem_id: str,
    checkpoint_correctness: Sequence[CheckpointCorrectnessEvidence],
    verbosity: Sequence[Decimal],
    erosion: Sequence[Decimal],
    architecture: Sequence[Decimal],
    rework: Sequence[Decimal],
    regression: Sequence[Decimal],
) -> ProblemScore:
    """Calculate one score from complete ordered checkpoint evidence."""
    return _calculate_problem(
        problem_id,
        checkpoint_correctness,
        verbosity,
        erosion,
        architecture,
        rework,
        regression,
    )[0]


def _cost_per_configured_checkpoint(
    benchmark_input: BenchmarkScoreInput,
) -> Decimal | None:
    """Validate and aggregate configured checkpoint costs without score inputs."""
    for cost, count in zip(
        benchmark_input.costs,
        benchmark_input.configured_checkpoint_counts,
        strict=True,
    ):
        if len(cost.checkpoints) != count:
            raise ValueError(
                "cost evidence must cover every configured checkpoint"
            )
        if len({item.checkpoint_id for item in cost.checkpoints}) != count:
            raise ValueError("cost checkpoint identifiers must be unique")
    invalid_cost = any(
        item.produced
        and (item.cost is None or not item.cost.is_finite() or item.cost < ZERO)
        for problem in benchmark_input.costs
        for item in problem.checkpoints
    )
    if invalid_cost:
        return None
    total_cost = sum(
        (
            item.cost if item.produced and item.cost is not None else ZERO
            for problem in benchmark_input.costs
            for item in problem.checkpoints
        ),
        ZERO,
    )
    return canonical_decimal(
        total_cost / Decimal(sum(benchmark_input.configured_checkpoint_counts))
    )


def calculate_scores(
    problem_inputs: Sequence[ProblemScoreInput],
    benchmark_input: BenchmarkScoreInput,
) -> tuple[tuple[ProblemScore, ...], BenchmarkScore]:
    """Calculate persisted scores while aggregating raw precision-50 values."""
    calculations = tuple(
        _calculate_problem(
            item.problem_id,
            item.checkpoint_correctness,
            item.verbosity,
            item.erosion,
            item.architecture,
            item.rework,
            item.regression,
        )
        for item in problem_inputs
    )
    problems = tuple(item[0] for item in calculations)
    problem_ids = tuple(item.problem_id for item in problem_inputs)
    if len(set(problem_ids)) != len(problem_ids) or set(problem_ids) - set(
        benchmark_input.configured_problem_ids
    ):
        raise ValueError("problem inputs must be unique and configured")
    cost_per_checkpoint = _cost_per_configured_checkpoint(benchmark_input)
    raw_by_problem = {
        problem.problem_id: calculation[1:]
        for problem, calculation in zip(
            problem_inputs, calculations, strict=True
        )
    }
    raw_scores = tuple(
        raw_by_problem[problem_id][0] if problem_id in raw_by_problem else ZERO
        for problem_id in benchmark_input.configured_problem_ids
    )
    raw_correctness = tuple(
        raw_by_problem[problem_id][1] if problem_id in raw_by_problem else ZERO
        for problem_id in benchmark_input.configured_problem_ids
    )
    raw_inertia = tuple(
        raw_by_problem[problem_id][2] if problem_id in raw_by_problem else ZERO
        for problem_id in benchmark_input.configured_problem_ids
    )
    benchmark = BenchmarkScore(
        problems=problems,
        benchmark_score=canonical_decimal(_mean(raw_scores), SCORE_PLACES),
        correctness=canonical_decimal(_mean(raw_correctness)),
        inertia=canonical_decimal(_mean(raw_inertia)),
        cost_per_configured_checkpoint=cost_per_checkpoint,
        run_identity=benchmark_input.run_identity,
    )
    return problems, benchmark


def ranking_key(
    score: BenchmarkScore,
) -> tuple[Decimal, Decimal, Decimal, bool, Decimal, str]:
    """Ascending key for the frozen leaderboard ordering."""
    return (
        -score.benchmark_score,
        -score.correctness,
        -score.inertia,
        score.cost_per_configured_checkpoint is None,
        score.cost_per_configured_checkpoint
        if score.cost_per_configured_checkpoint is not None
        else ZERO,
        score.run_identity,
    )
