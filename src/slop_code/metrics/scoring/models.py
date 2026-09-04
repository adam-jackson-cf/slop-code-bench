"""Canonical typed evidence, eligibility, and score artifacts."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN
from decimal import Decimal
from decimal import localcontext
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_serializer
from pydantic import field_validator
from pydantic import model_validator

DECIMAL_PLACES = Decimal("0.000000000001")
SCORE_PLACES = Decimal("0.000001")
ZERO = Decimal("0")
ONE = Decimal("1")
ELIGIBILITY_CODES = frozenset(
    {
        "canonical_artifact_invalid",
        "canonical_provenance_unavailable",
        "canonical_test_denominator_zero",
        "configured_problem_too_short",
        "coverage_parity_failed",
        "coverage_parity_unavailable",
        "measurement_environment_mismatch",
        "production_language_unsupported",
        "production_source_loc_zero",
        "production_symbol_evidence_invalid",
        "score_evidence_invalid",
        "score_formula_invalid",
    }
)


def canonical_decimal(
    value: Decimal, places: Decimal = DECIMAL_PLACES
) -> Decimal:
    """Return a finite decimal quantized at the artifact boundary."""
    if not value.is_finite():
        raise ValueError("decimal must be finite")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        return value.quantize(places)


class ScoringModel(BaseModel):
    """Frozen base for every persisted canonical scoring artifact."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, ser_json_inf_nan="strings"
    )

    @field_serializer("*", when_used="json", check_fields=False)
    def serialize_decimals(self, value: object) -> object:
        return format(value, "f") if isinstance(value, Decimal) else value


UnitDecimal = Annotated[Decimal, Field(ge=ZERO, le=ONE)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=ZERO)]


class FileRole(StrEnum):
    GENERATED = "generated"
    TEST = "test"
    PRODUCTION = "production"
    IGNORED = "ignored"


class ProducerStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class PublicationState(StrEnum):
    PENDING = "pending"
    INELIGIBLE = "ineligible"
    PUBLISHED = "published"


class InventoryFile(ScoringModel):
    path: str = Field(min_length=1)
    role: FileRole
    source_hash: str | None = None
    recognized_extension: str | None = None
    matched_rules: tuple[str, ...] = ()
    ignored_reason: str | None = None
    is_symlink: bool = False
    resolved_path: str | None = None
    lexical_path: str | None = None
    symlink_target: str | None = None


class InterpreterEvidence(ScoringModel):
    executable: str = Field(min_length=1)
    implementation: str = Field(min_length=1)
    version: str = Field(min_length=1)


class RuffDiagnostic(ScoringModel):
    code: str = Field(min_length=1)
    path: str = Field(min_length=1)
    line: int = Field(ge=1)
    column: int = Field(ge=1)


class RuffEvidence(ScoringModel):
    version: str = Field(min_length=1)
    selected_rules: tuple[str, ...]
    diagnostics: tuple[RuffDiagnostic, ...]


class CloneEvidence(ScoringModel):
    detector: str = Field(min_length=1)
    detector_version: str = Field(min_length=1)
    clone_id: str = Field(min_length=1)
    paths: tuple[str, ...] = Field(min_length=2)
    lines: tuple[int, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_lines(self) -> CloneEvidence:
        if any(line < 1 for line in self.lines):
            raise ValueError("clone lines must be positive")
        return self


class SymbolMassEvidence(ScoringModel):
    identity: str = Field(min_length=1)
    path: str = Field(min_length=1)
    owned_lines: int = Field(ge=0)
    mass: NonNegativeDecimal


class ProductionQualityEvidence(ScoringModel):
    checkpoint_id: str = Field(min_length=1)
    interpreter: InterpreterEvidence
    ruff: RuffEvidence
    clones: tuple[CloneEvidence, ...]
    symbol_mass: tuple[SymbolMassEvidence, ...]
    source_loc_numerator: int = Field(ge=0)
    source_loc_denominator: int = Field(gt=0)
    verbosity_lines: tuple[int, ...]
    clone_lines: tuple[int, ...]
    erosion_numerator: NonNegativeDecimal
    erosion_denominator: NonNegativeDecimal
    verbosity: UnitDecimal
    erosion: UnitDecimal


class QualityInterpreterEvidence(ScoringModel):
    executable: str = Field(min_length=1)
    implementation: str = Field(min_length=1)
    version: str = Field(min_length=1)
    cache_tag: str = Field(min_length=1)
    executable_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ast_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tokenize_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class QualityFileEvidence(ScoringModel):
    path: str = Field(min_length=1)
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_lines: tuple[int, ...]


class QualityRuffDiagnosticEvidence(ScoringModel):
    code: str = Field(min_length=1)
    path: str = Field(min_length=1)
    start: tuple[int, int]
    end: tuple[int, int]


class QualityRuffEvidence(ScoringModel):
    version: str = Field(min_length=1)
    invocation: tuple[str, ...]
    rules: tuple[str, ...]
    diagnostics: tuple[QualityRuffDiagnosticEvidence, ...]


class QualityCloneGroupEvidence(ScoringModel):
    vector: tuple[str, ...] = Field(min_length=1)
    occurrences: tuple[tuple[str, int, int], ...] = Field(min_length=2)


class EligibleSymbolEvidence(ScoringModel):
    identity: tuple[str, str, Literal["function", "method"], int, int]
    cc: NonNegativeDecimal
    sloc: int = Field(gt=0)
    mass: NonNegativeDecimal
    high_complexity: bool


class SymbolExclusionReason(StrEnum):
    KIND_INELIGIBLE = "symbol_kind_ineligible"
    PATH_NOT_PRODUCTION = "symbol_path_not_production"


class ExcludedSymbolEvidence(ScoringModel):
    reason: SymbolExclusionReason
    kind: str
    path: str


class QualityDecimalContextEvidence(ScoringModel):
    precision: int = Field(gt=0)
    rounding: Literal["ROUND_HALF_EVEN"]


class ProductionQualityRawEvidence(ScoringModel):
    """Complete, ordered raw inputs required to recompute V and E."""

    checkpoint_id: str = Field(min_length=1)
    interpreter: QualityInterpreterEvidence
    parser_tokenizer_schema_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_tokenizer_probe: str = Field(min_length=1)
    files: tuple[QualityFileEvidence, ...]
    ruff: QualityRuffEvidence
    clones: tuple[QualityCloneGroupEvidence, ...]
    verbosity_lines: tuple[tuple[str, int], ...]
    clone_lines: tuple[tuple[str, int], ...]
    union_numerator: int = Field(ge=0)
    source_loc_denominator: int = Field(gt=0)
    eligible_symbols: tuple[EligibleSymbolEvidence, ...]
    excluded_symbols: tuple[ExcludedSymbolEvidence, ...]
    erosion_numerator: NonNegativeDecimal
    erosion_denominator: NonNegativeDecimal
    decimal_context: QualityDecimalContextEvidence
    verbosity: UnitDecimal
    erosion: UnitDecimal

    @model_validator(mode="after")
    def validate_quality_counts(self) -> ProductionQualityRawEvidence:
        if self.union_numerator > self.source_loc_denominator:
            raise ValueError("verbosity numerator cannot exceed source LOC")
        if self.erosion_numerator > self.erosion_denominator:
            raise ValueError("erosion numerator cannot exceed denominator")
        if (
            tuple(sorted(self.files, key=lambda row: row.path.encode("utf-8")))
            != self.files
        ):
            raise ValueError("quality files must be ordered")
        if (
            tuple(sorted(self.verbosity_lines)) != self.verbosity_lines
            or tuple(sorted(self.clone_lines)) != self.clone_lines
        ):
            raise ValueError("quality line evidence must be ordered")
        if (
            tuple(
                sorted(
                    self.ruff.diagnostics,
                    key=lambda row: (row.path, row.start, row.end, row.code),
                )
            )
            != self.ruff.diagnostics
        ):
            raise ValueError("Ruff diagnostics must be ordered")
        if (
            tuple(
                sorted(
                    self.clones,
                    key=lambda row: (row.vector, row.occurrences),
                )
            )
            != self.clones
        ):
            raise ValueError("clone groups must be ordered")
        if (
            tuple(sorted(self.eligible_symbols, key=lambda row: row.identity))
            != self.eligible_symbols
        ):
            raise ValueError("eligible symbols must be ordered")
        if (
            tuple(
                sorted(
                    self.excluded_symbols,
                    key=lambda row: (
                        row.reason.value,
                        row.path.encode("utf-8"),
                        row.kind.encode("utf-8"),
                    ),
                )
            )
            != self.excluded_symbols
        ):
            raise ValueError("excluded symbols must be ordered")
        return self


class GraphNode(ScoringModel):
    identity: str = Field(min_length=1)
    path: str = Field(min_length=1)


class GraphEdge(ScoringModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    weight: NonNegativeDecimal
    source_role: FileRole = FileRole.PRODUCTION
    target_role: FileRole = FileRole.PRODUCTION
    cyclic: bool = False
    self_loop: bool = False


class GraphSccEvidence(ScoringModel):
    members: tuple[str, ...] = Field(min_length=1)
    mass: NonNegativeDecimal
    cyclic: bool = False
    self_loop: bool = False

    @model_validator(mode="after")
    def validate_members(self) -> GraphSccEvidence:
        if (
            tuple(
                sorted(
                    set(self.members), key=lambda value: value.encode("utf-8")
                )
            )
            != self.members
        ):
            raise ValueError("SCC members must be unique UTF-8 byte order")
        return self


class ProductionGraphEvidence(ScoringModel):
    checkpoint_id: str = Field(min_length=1)
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    sccs: tuple[GraphSccEvidence, ...]
    cyclic_mass: NonNegativeDecimal
    total_mass: NonNegativeDecimal
    architecture: UnitDecimal
    cross_role_edges: tuple[GraphEdge, ...] = ()

    @model_validator(mode="after")
    def validate_masses(self) -> ProductionGraphEvidence:
        if self.cyclic_mass > self.total_mass:
            raise ValueError("cyclic mass cannot exceed total mass")
        if sum((edge.weight for edge in self.edges), ZERO) != self.total_mass:
            raise ValueError("total mass must equal production edge weights")
        cyclic_scc_mass = sum(
            (scc.mass for scc in self.sccs if scc.cyclic), ZERO
        )
        if cyclic_scc_mass != self.cyclic_mass:
            raise ValueError("cyclic mass must equal cyclic SCC mass")
        return self


class SymbolIdentity(ScoringModel):
    """Canonical identity and immutable content fingerprints for one symbol."""

    path: str = Field(min_length=1)
    qualified_name: str = Field(min_length=1)
    kind: Literal["function", "method"]
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    language: str = "python"
    parent_qualified_name: str = ""
    body_sha256: str = ""
    structure_sha256: str = ""
    signature_sha256: str = ""

    @model_validator(mode="after")
    def validate_span(self) -> SymbolIdentity:
        if self.end_line < self.start_line:
            raise ValueError("end line precedes start line")
        for value in (
            self.body_sha256,
            self.structure_sha256,
            self.signature_sha256,
        ):
            if value and (
                len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise ValueError(
                    "symbol hashes must be lowercase SHA-256 digests"
                )
        return self

    @property
    def exact_identity(self) -> tuple[str, str, str, str, str]:
        return (
            self.language,
            self.kind,
            self.parent_qualified_name,
            self.qualified_name,
            self.path,
        )

    @property
    def stable_identity(self) -> tuple[str, str, str, str, str, int, int]:
        return (*self.exact_identity, self.start_line, self.end_line)


class LineageCandidate(ScoringModel):
    """One complete-bipartite candidate edge between checkpoint symbols."""

    prior: SymbolIdentity
    current: SymbolIdentity
    body_hash_equal: bool
    structure_hash_equal: bool
    signature_hash_equal: bool
    accepted: bool
    ambiguous_set_id: str | None
    match: Literal["exact", "hash", "none"] = "exact"

    @model_validator(mode="after")
    def validate_candidate(self) -> LineageCandidate:
        if self.accepted and self.ambiguous_set_id is not None:
            raise ValueError("accepted lineage cannot have an ambiguous set")
        if self.accepted and self.match == "none":
            raise ValueError("accepted lineage requires a match kind")
        if (
            self.match == "exact"
            and self.prior.exact_identity != self.current.exact_identity
        ):
            raise ValueError("exact lineage must have equal exact identities")
        if self.match == "hash" and not (
            self.body_hash_equal and self.structure_hash_equal
        ):
            raise ValueError(
                "hash lineage requires body and structure equality"
            )
        return self


class SymbolDegreeEvidence(ScoringModel):
    symbol: SymbolIdentity
    inbound: int = Field(ge=0)
    outbound: int = Field(ge=0)


class LineageComponentEvidence(ScoringModel):
    component_id: str = Field(min_length=64, max_length=64)
    priors: tuple[SymbolIdentity, ...]
    currents: tuple[SymbolIdentity, ...]
    ambiguous: bool

    @model_validator(mode="after")
    def validate_component(self) -> LineageComponentEvidence:
        if not self.priors or not self.currents:
            raise ValueError("lineage component requires both endpoint sets")
        return self


class OwnedLineEvidence(ScoringModel):
    symbol: SymbolIdentity
    lines: tuple[int, ...]

    @model_validator(mode="after")
    def validate_lines(self) -> OwnedLineEvidence:
        if tuple(sorted(set(self.lines))) != self.lines:
            raise ValueError("owned lines must be unique and ordered")
        if any(
            line < self.symbol.start_line or line > self.symbol.end_line
            for line in self.lines
        ):
            raise ValueError("owned lines must be within the symbol span")
        return self


class PhysicalLineEvidence(ScoringModel):
    path: str = Field(min_length=1)
    line: int = Field(ge=1)
    side: Literal["added", "removed"]
    owner: SymbolIdentity | None = None


class LineageLedgerEntry(ScoringModel):
    candidate: LineageCandidate
    disposition: Literal["accepted", "rejected"]
    reason: str = Field(min_length=1)
    prior_modified_before: bool = False
    current_modified_before: bool = False

    @model_validator(mode="after")
    def validate_disposition(self) -> LineageLedgerEntry:
        if self.candidate.accepted != (self.disposition == "accepted"):
            raise ValueError("lineage ledger disposition must match candidate")
        return self


class LedgerTransitionEvidence(ScoringModel):
    prior: SymbolIdentity
    current: SymbolIdentity
    input_modified_before: bool
    mapped_changed: bool
    output_modified_before: bool
    reset: bool = False


class TransitionReworkEvidence(ScoringModel):
    changed_physical_lines: tuple[PhysicalLineEvidence, ...]
    lineage_candidates: tuple[LineageCandidate, ...]
    symbol_degrees: tuple[SymbolDegreeEvidence, ...]
    lineage_components: tuple[LineageComponentEvidence, ...]
    owned_lines: tuple[OwnedLineEvidence, ...]
    lineage_ledger: tuple[LineageLedgerEntry, ...]
    ledger_transitions: tuple[LedgerTransitionEvidence, ...]
    changed_lines: int = Field(ge=0)
    repeated_lines: int = Field(ge=0)
    rework: UnitDecimal

    @model_validator(mode="after")
    def validate_counts(self) -> TransitionReworkEvidence:
        if self.repeated_lines > self.changed_lines:
            raise ValueError("repeated lines cannot exceed changed lines")
        if (
            tuple(entry.candidate for entry in self.lineage_ledger)
            != self.lineage_candidates
        ):
            raise ValueError(
                "lineage ledger must be ordered by lineage candidates"
            )
        return self


class TransitionScoreEvidence(ScoringModel):
    prior_checkpoint_id: str = Field(min_length=1)
    current_checkpoint_id: str = Field(min_length=1)
    changed_lines: int = Field(ge=0)
    repeated_lines: int = Field(ge=0)
    lineage_candidates: tuple[LineageCandidate, ...]
    symbol_degrees: tuple[SymbolDegreeEvidence, ...]
    owned_lines: tuple[OwnedLineEvidence, ...]
    lineage_ledger: tuple[LineageLedgerEntry, ...]
    rework: UnitDecimal

    @model_validator(mode="after")
    def validate_counts(self) -> TransitionScoreEvidence:
        if self.repeated_lines > self.changed_lines:
            raise ValueError("repeated lines cannot exceed changed lines")
        if (
            tuple(entry.candidate for entry in self.lineage_ledger)
            != self.lineage_candidates
        ):
            raise ValueError(
                "lineage ledger must be ordered by lineage candidates"
            )
        return self


class ReworkCheckpointInput(ScoringModel):
    """One configured checkpoint; ``symbols=None`` is an explicit gap."""

    checkpoint_id: str = Field(min_length=1)
    symbols: tuple[SymbolIdentity, ...] | None
    removed_lines: tuple[PhysicalLineEvidence, ...] = ()
    added_lines: tuple[PhysicalLineEvidence, ...] = ()


class ProblemReworkEvidence(ScoringModel):
    """Ordered transition evidence and ledger state for one configured problem."""

    checkpoint_ids: tuple[str, ...] = Field(min_length=2)
    transitions: tuple[TransitionReworkEvidence, ...]
    final_ledger: tuple[LedgerTransitionEvidence, ...]

    @model_validator(mode="after")
    def validate_transitions(self) -> ProblemReworkEvidence:
        if len(self.transitions) != len(self.checkpoint_ids) - 1:
            raise ValueError(
                "rework transitions must cover adjacent checkpoints"
            )
        return self


class RegressionPhase(StrEnum):
    COLLECTION = "collection"
    SETUP = "setup"
    CALL = "call"
    TEARDOWN = "teardown"


class RegressionOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class CorpusEvidence(ScoringModel):
    corpus_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvaluatorEnvironmentEvidence(ScoringModel):
    environment_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    platform_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plugin_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    interpreter_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RegressionInvocationEvidence(ScoringModel):
    argv: tuple[str, ...] = Field(min_length=1)
    cwd: str = Field(min_length=1)


class RegressionOutcomeEvidence(ScoringModel):
    node_id: str = Field(min_length=1)
    group_type: str = Field(min_length=1)
    phase: RegressionPhase
    outcome: RegressionOutcome


class RegressionLedgerEvidence(ScoringModel):
    node_id: str = Field(min_length=1)
    phase: RegressionPhase
    outcome: RegressionOutcome


class CoverageContextEvidence(ScoringModel):
    node_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    executed_lines: tuple[int, ...]

    @model_validator(mode="after")
    def validate_lines(self) -> CoverageContextEvidence:
        if tuple(sorted(set(self.executed_lines))) != self.executed_lines:
            raise ValueError("coverage lines must be unique and ordered")
        if any(line < 1 for line in self.executed_lines):
            raise ValueError("coverage lines must be positive")
        return self


class ProcessAuditEvent(ScoringModel):
    node_id: str = Field(min_length=1)
    phase: RegressionPhase
    event: Literal[
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.fork",
        "pty.spawn",
    ]


class RegressionRunEvidence(ScoringModel):
    environment: EvaluatorEnvironmentEvidence
    corpus: CorpusEvidence
    invocation: RegressionInvocationEvidence
    outcomes: tuple[RegressionOutcomeEvidence, ...]
    ledger: tuple[RegressionLedgerEvidence, ...]
    coverage: tuple[CoverageContextEvidence, ...]
    process_events: tuple[ProcessAuditEvent, ...] = ()


class RegressionBreadthInput(ScoringModel):
    transition_id: str = Field(min_length=1)
    baseline: RegressionRunEvidence
    produced: RegressionRunEvidence
    changed_symbols: tuple[SymbolIdentity, ...]


class RegressionSymbolAttribution(ScoringModel):
    node_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    line: int = Field(ge=1)
    symbol: SymbolIdentity


class RegressionAttribution(ScoringModel):
    """Persisted input, exact attribution, and eligibility for transition G."""

    input: RegressionBreadthInput
    attributions: tuple[RegressionSymbolAttribution, ...]
    eligibility: Eligibility
    regression: UnitDecimal | None

    @model_validator(mode="after")
    def validate_regression(self) -> RegressionAttribution:
        if self.eligibility.eligible != (self.regression is not None):
            raise ValueError("eligible regression attribution requires a score")
        if not self.eligibility.eligible and self.attributions:
            raise ValueError(
                "ineligible regression attribution cannot attribute"
            )
        return self


class CheckpointCorrectnessEvidence(ScoringModel):
    checkpoint_id: str = Field(min_length=1)
    produced: bool = True
    passed: int = Field(ge=0)
    total: int = Field(ge=0)
    rate: UnitDecimal

    @model_validator(mode="after")
    def validate_rate(self) -> CheckpointCorrectnessEvidence:
        if not self.produced:
            if self.passed or self.total or self.rate != ZERO:
                raise ValueError(
                    "unproduced correctness must be the declared zero"
                )
        elif self.total <= 0:
            raise ValueError(
                "produced correctness requires a positive denominator"
            )
        elif self.rate != Decimal(self.passed) / Decimal(self.total):
            raise ValueError("correctness rate must equal passed / total")
        return self


class ComponentScores(ScoringModel):
    correctness: UnitDecimal
    verbosity: UnitDecimal
    erosion: UnitDecimal
    architecture: UnitDecimal
    rework: UnitDecimal
    regression: UnitDecimal
    inertia: UnitDecimal


class ProblemScore(ScoringModel):
    problem_id: str = Field(min_length=1)
    configured_checkpoints: int = Field(ge=2)
    checkpoint_correctness: tuple[CheckpointCorrectnessEvidence, ...]
    components: ComponentScores
    score: Annotated[Decimal, Field(ge=ZERO, le=Decimal("100"))]

    @model_validator(mode="after")
    def validate_checkpoints(self) -> ProblemScore:
        if len(self.checkpoint_correctness) != self.configured_checkpoints:
            raise ValueError(
                "correctness evidence must cover configured checkpoints"
            )
        if len(
            {item.checkpoint_id for item in self.checkpoint_correctness}
        ) != len(self.checkpoint_correctness):
            raise ValueError(
                "correctness checkpoint identifiers must be unique"
            )
        return self


class ProblemCostEvidence(ScoringModel):
    problem_id: str = Field(min_length=1)
    checkpoints: tuple[CheckpointCostEvidence, ...]


class CheckpointCostEvidence(ScoringModel):
    checkpoint_id: str = Field(min_length=1)
    produced: bool
    cost: Decimal | None

    @model_validator(mode="after")
    def validate_cost(self) -> CheckpointCostEvidence:
        if not self.produced and self.cost is not None:
            raise ValueError("unproduced checkpoints cannot carry a cost")
        return self


class ProblemScoreInput(ScoringModel):
    """Complete ordered, raw formula inputs for one configured problem."""

    problem_id: str = Field(min_length=1)
    checkpoint_ids: tuple[str, ...] = Field(min_length=2)
    checkpoint_correctness: tuple[CheckpointCorrectnessEvidence, ...]
    verbosity: tuple[UnitDecimal, ...]
    erosion: tuple[UnitDecimal, ...]
    architecture: tuple[UnitDecimal, ...]
    rework: tuple[UnitDecimal, ...]
    regression: tuple[UnitDecimal, ...]

    @model_validator(mode="after")
    def validate_formula_inputs(self) -> ProblemScoreInput:
        count = len(self.checkpoint_ids)
        if len(set(self.checkpoint_ids)) != count:
            raise ValueError("configured checkpoint identifiers must be unique")
        if (
            tuple(item.checkpoint_id for item in self.checkpoint_correctness)
            != self.checkpoint_ids
        ):
            raise ValueError(
                "correctness evidence must match configured checkpoint order"
            )
        if any(
            len(values) != count
            for values in (self.verbosity, self.erosion, self.architecture)
        ):
            raise ValueError(
                "checkpoint components must cover configured checkpoints"
            )
        if any(
            len(values) != count - 1
            for values in (self.rework, self.regression)
        ):
            raise ValueError(
                "transition components must cover adjacent checkpoints"
            )
        return self


class BenchmarkScoreInput(ScoringModel):
    """Complete ordered, raw formula inputs for benchmark aggregation."""

    configured_problem_ids: tuple[str, ...] = Field(min_length=1)
    configured_checkpoint_counts: tuple[int, ...]
    costs: tuple[ProblemCostEvidence, ...]
    run_identity: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_formula_inputs(self) -> BenchmarkScoreInput:
        if len(self.configured_problem_ids) != len(
            self.configured_checkpoint_counts
        ):
            raise ValueError("configured problem inputs must have equal length")
        if len(set(self.configured_problem_ids)) != len(
            self.configured_problem_ids
        ):
            raise ValueError("configured problem identities must be unique")
        if any(count < 2 for count in self.configured_checkpoint_counts):
            raise ValueError(
                "configured problems require at least two checkpoints"
            )
        if (
            tuple(cost.problem_id for cost in self.costs)
            != self.configured_problem_ids
        ):
            raise ValueError(
                "cost evidence must match configured problem order"
            )
        if len(self.costs) != len(self.configured_problem_ids):
            raise ValueError("cost evidence must cover configured problems")
        return self


class ScoreEvidenceIndex(ScoringModel):
    """All score sidecars, with configured identities fixed before calculation."""

    parser_tokenizer_schema_id: str = Field(pattern=r"^[0-9a-f]{64}$")

    problems: tuple[ProblemScoreInput, ...]
    benchmark: BenchmarkScoreInput

    @model_validator(mode="after")
    def validate_problem_coverage(self) -> ScoreEvidenceIndex:
        if (
            tuple(problem.problem_id for problem in self.problems)
            != self.benchmark.configured_problem_ids
        ):
            raise ValueError(
                "problem sidecars must match configured problem order"
            )
        return self


class BenchmarkScore(ScoringModel):
    problems: tuple[ProblemScore, ...]
    benchmark_score: Annotated[Decimal, Field(ge=ZERO, le=Decimal("100"))]
    correctness: UnitDecimal
    inertia: UnitDecimal
    cost_per_configured_checkpoint: NonNegativeDecimal | None
    run_identity: str = Field(min_length=1)


class EvidenceIndexEntry(ScoringModel):
    path: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    byte_length: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    producer: str = Field(min_length=1)
    status: ProducerStatus = ProducerStatus.COMPLETE


class OracleCheckpointProjection(ScoringModel):
    checkpoint_id: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_rows: tuple[tuple[str, ...], ...]


class OracleArtifact(ScoringModel):
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes_base64: str
    projections: tuple[OracleCheckpointProjection, ...]

    @model_validator(mode="after")
    def validate_projections(self) -> OracleArtifact:
        if tuple(item.ordinal for item in self.projections) != tuple(
            range(len(self.projections))
        ):
            raise ValueError(
                "oracle projections must have contiguous ordered ordinals"
            )
        return self


class OracleBaseline(ScoringModel):
    name: str = Field(min_length=1)
    artifacts: tuple[OracleArtifact, ...]


class OracleBundle(ScoringModel):
    baselines: tuple[OracleBaseline, ...]


class Eligibility(ScoringModel):
    eligible: bool
    reasons: tuple[str, ...] = ()

    @field_validator("reasons")
    @classmethod
    def validate_reasons(cls, reasons: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(reasons))) != reasons:
            raise ValueError(
                "eligibility reasons must be deduplicated ASCII-sorted"
            )
        if unknown := set(reasons) - ELIGIBILITY_CODES:
            raise ValueError(f"unknown eligibility codes: {sorted(unknown)}")
        return reasons

    @model_validator(mode="after")
    def validate_state(self) -> Eligibility:
        if self.eligible != (not self.reasons):
            raise ValueError(
                "eligible requires no reasons and ineligible requires reasons"
            )
        return self


class ProductionEvidence(ScoringModel):
    """Typed V/E/H payloads and their complete eligibility decision."""

    eligibility: Eligibility
    production_quality: ProductionQualityRawEvidence | None = None
    production_graph: ProductionGraphEvidence | None = None

    @model_validator(mode="after")
    def validate_complete_eligible_evidence(self) -> ProductionEvidence:
        if self.eligibility.eligible and (
            self.production_quality is None or self.production_graph is None
        ):
            raise ValueError(
                "eligible production evidence requires V/E/H payloads"
            )
        return self


class CheckpointReportAddition(ScoringModel):
    problem_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    problem_name: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    checkpoint_index: int = Field(ge=0)
    correctness: UnitDecimal
    verbosity: UnitDecimal
    erosion: UnitDecimal
    architecture: UnitDecimal
    rework: UnitDecimal | None
    regression: UnitDecimal | None
    problem_components: ComponentScores
    problem_score: Annotated[Decimal, Field(ge=ZERO, le=Decimal("100"))]


class GenerationManifest(ScoringModel):
    kind: Literal["benchmark_score_generation"]
    schema_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    formula_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_tokenizer_schema_id: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    entries: tuple[EvidenceIndexEntry, ...]
    eligibility: Eligibility
    publication_state: PublicationState
    evidence_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    producer_status_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligibility_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    benchmark: BenchmarkScore | None = None
    ranking_position: int | None = Field(default=None, ge=1)
    report_additions: tuple[CheckpointReportAddition, ...] = ()

    @model_validator(mode="after")
    def validate_publication(self) -> GenerationManifest:
        has_publication = (
            self.benchmark is not None
            or self.ranking_position is not None
            or bool(self.report_additions)
        )
        if self.eligibility.eligible:
            if self.publication_state is PublicationState.INELIGIBLE:
                raise ValueError(
                    "eligible generation cannot be marked ineligible"
                )
        elif (
            self.publication_state is not PublicationState.INELIGIBLE
            or has_publication
        ):
            raise ValueError(
                "ineligible generation cannot carry scores, ranking, or report additions"
            )
        if (
            self.publication_state is PublicationState.PUBLISHED
            and self.benchmark is None
        ):
            raise ValueError("published generation requires a benchmark score")
        return self
