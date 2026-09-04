"""Canonical scoring schemas and pure composite-score formulas."""

from slop_code.common.constants import BENCHMARK_SCORE_FILENAME
from slop_code.common.constants import CHECKPOINT_REPORT_ADDITIONS_FILENAME
from slop_code.common.constants import CURRENT_POINTER_FILENAME
from slop_code.common.constants import ELIGIBILITY_FILENAME
from slop_code.common.constants import EVALUATOR_ENVIRONMENTS_DIR
from slop_code.common.constants import EVALUATOR_LOCK_FILENAME
from slop_code.common.constants import EVALUATOR_READY_FILENAME
from slop_code.common.constants import EVIDENCE_INDEX_FILENAME
from slop_code.common.constants import FINALIZE_LOCK_FILENAME
from slop_code.common.constants import GENERATIONS_DIR
from slop_code.common.constants import HISTORICAL_PROVENANCE_DIR
from slop_code.common.constants import MANIFEST_FILENAME
from slop_code.common.constants import MEASUREMENT_ANALYSIS_DIR
from slop_code.common.constants import PENDING_ORACLES_DIR
from slop_code.common.constants import PROBLEM_SCORE_FILENAME
from slop_code.common.constants import PRODUCER_STATUS_FILENAME
from slop_code.common.constants import SCORING_DIR
from slop_code.common.constants import STAGING_DIR

from .contract import EXPECTED_INTERPRETER
from .contract import EXPECTED_INTERPRETER_CACHE_TAG
from .contract import EXPECTED_INTERPRETER_IMPLEMENTATION
from .contract import EXPECTED_INTERPRETER_VERSION
from .contract import EXPECTED_RUFF_VERSION
from .contract import FILE_BYTE_POLICY
from .contract import PARSER_TOKENIZER_ALGORITHM
from .contract import PARSER_TOKENIZER_PROBE
from .contract import PRODUCTION_QUALITY_CONTRACT
from .contract import RUFF_ARGUMENTS
from .contract import RUFF_RULES
from .finalization import finalize_benchmark_score
from .generation import PublicationBoundary
from .generation import PublicationFailureObserver
from .generation import ScoreEvidenceError
from .generation import aggregate_eligibility
from .generation import calculate_scores_from_evidence
from .generation import checkpoint_sidecar
from .generation import freeze_evidence_index
from .generation import load_verified_current_generation
from .generation import load_verified_current_generation_state
from .generation import publish_generation
from .generation import read_verified_evidence
from .generation import score_evidence_sidecar
from .generation import transition_sidecar
from .inventory import RECOGNIZED_EXTENSIONS
from .inventory import InventoryResult
from .inventory import build_inventory
from .lineage import calculate_problem_rework
from .lineage import calculate_transition_rework
from .models import BenchmarkScore
from .models import BenchmarkScoreInput
from .models import CheckpointCorrectnessEvidence
from .models import CheckpointCostEvidence
from .models import CloneEvidence
from .models import ComponentScores
from .models import CorpusEvidence
from .models import CoverageContextEvidence
from .models import Eligibility
from .models import EvaluatorEnvironmentEvidence
from .models import EvidenceIndexEntry
from .models import FileRole
from .models import GenerationManifest
from .models import GraphEdge
from .models import GraphNode
from .models import GraphSccEvidence
from .models import InventoryFile
from .models import LedgerTransitionEvidence
from .models import LineageCandidate
from .models import LineageComponentEvidence
from .models import LineageLedgerEntry
from .models import OracleArtifact
from .models import OracleBaseline
from .models import OracleBundle
from .models import OracleCheckpointProjection
from .models import OwnedLineEvidence
from .models import PhysicalLineEvidence
from .models import ProblemCostEvidence
from .models import ProblemReworkEvidence
from .models import ProblemScore
from .models import ProblemScoreInput
from .models import ProcessAuditEvent
from .models import ProducerStatus
from .models import ProductionEvidence
from .models import ProductionGraphEvidence
from .models import ProductionQualityEvidence
from .models import ProductionQualityRawEvidence
from .models import PublicationState
from .models import RegressionAttribution
from .models import RegressionBreadthInput
from .models import RegressionInvocationEvidence
from .models import RegressionLedgerEvidence
from .models import RegressionOutcome
from .models import RegressionOutcomeEvidence
from .models import RegressionPhase
from .models import RegressionRunEvidence
from .models import RegressionSymbolAttribution
from .models import ReworkCheckpointInput
from .models import RuffDiagnostic
from .models import RuffEvidence
from .models import ScoreEvidenceIndex
from .models import SymbolDegreeEvidence
from .models import SymbolIdentity
from .models import SymbolMassEvidence
from .models import TransitionReworkEvidence
from .models import TransitionScoreEvidence
from .production import PRODUCTION_GRAPH_FILENAME
from .production import PRODUCTION_QUALITY_FILENAME
from .production import ProductionEvidenceResult
from .production import produce_production_evidence
from .production_quality import ProductionQualityError
from .production_quality import ProductionQualityResult
from .production_quality import produce_production_quality
from .regression import calculate_regression_breadth
from .schema import FORMULAS
from .schema import LINEAGE_CONTRACT
from .schema import PRECISION
from .schema import RANKING
from .schema import REGRESSION_CONTRACT
from .schema import WEIGHTS
from .schema import calculate_problem_score
from .schema import canonical_json_bytes
from .schema import ranking_key
from .schema import scoring_schema_bytes
from .schema import scoring_schema_id

__all__ = [
    "BENCHMARK_SCORE_FILENAME",
    "CHECKPOINT_REPORT_ADDITIONS_FILENAME",
    "CURRENT_POINTER_FILENAME",
    "BenchmarkScore",
    "BenchmarkScoreInput",
    "checkpoint_sidecar",
    "CheckpointCorrectnessEvidence",
    "CheckpointCostEvidence",
    "CloneEvidence",
    "ComponentScores",
    "CorpusEvidence",
    "CoverageContextEvidence",
    "EXPECTED_INTERPRETER",
    "EXPECTED_INTERPRETER_CACHE_TAG",
    "EXPECTED_INTERPRETER_IMPLEMENTATION",
    "EXPECTED_INTERPRETER_VERSION",
    "EXPECTED_RUFF_VERSION",
    "FILE_BYTE_POLICY",
    "ELIGIBILITY_FILENAME",
    "EVALUATOR_ENVIRONMENTS_DIR",
    "EVALUATOR_LOCK_FILENAME",
    "EVALUATOR_READY_FILENAME",
    "EVIDENCE_INDEX_FILENAME",
    "Eligibility",
    "EvidenceIndexEntry",
    "FORMULAS",
    "FileRole",
    "aggregate_eligibility",
    "freeze_evidence_index",
    "finalize_benchmark_score",
    "calculate_scores_from_evidence",
    "EvaluatorEnvironmentEvidence",
    "FINALIZE_LOCK_FILENAME",
    "GENERATIONS_DIR",
    "GenerationManifest",
    "GraphEdge",
    "GraphNode",
    "GraphSccEvidence",
    "HISTORICAL_PROVENANCE_DIR",
    "InterpreterEvidence",
    "InventoryFile",
    "InventoryResult",
    "MANIFEST_FILENAME",
    "MEASUREMENT_ANALYSIS_DIR",
    "LineageCandidate",
    "LedgerTransitionEvidence",
    "LineageComponentEvidence",
    "LineageLedgerEntry",
    "OracleArtifact",
    "OracleBaseline",
    "OracleBundle",
    "OracleCheckpointProjection",
    "OwnedLineEvidence",
    "PhysicalLineEvidence",
    "ProblemReworkEvidence",
    "PENDING_ORACLES_DIR",
    "PRECISION",
    "PRODUCER_STATUS_FILENAME",
    "PARSER_TOKENIZER_ALGORITHM",
    "PARSER_TOKENIZER_PROBE",
    "PRODUCTION_QUALITY_CONTRACT",
    "PROBLEM_SCORE_FILENAME",
    "ProblemCostEvidence",
    "ProblemScore",
    "ProblemScoreInput",
    "ProcessAuditEvent",
    "ProducerStatus",
    "ProductionEvidence",
    "ProductionGraphEvidence",
    "PRODUCTION_GRAPH_FILENAME",
    "PRODUCTION_QUALITY_FILENAME",
    "ProductionEvidenceResult",
    "ProductionQualityEvidence",
    "ProductionQualityRawEvidence",
    "PublicationState",
    "RANKING",
    "REGRESSION_CONTRACT",
    "RegressionAttribution",
    "RegressionBreadthInput",
    "RegressionInvocationEvidence",
    "RegressionLedgerEvidence",
    "RegressionOutcome",
    "RegressionOutcomeEvidence",
    "RegressionPhase",
    "RegressionRunEvidence",
    "RegressionSymbolAttribution",
    "RuffDiagnostic",
    "RuffEvidence",
    "SCORING_DIR",
    "PublicationBoundary",
    "PublicationFailureObserver",
    "publish_generation",
    "load_verified_current_generation",
    "load_verified_current_generation_state",
    "read_verified_evidence",
    "RUFF_ARGUMENTS",
    "RUFF_RULES",
    "STAGING_DIR",
    "ScoreEvidenceIndex",
    "SymbolDegreeEvidence",
    "ScoreEvidenceError",
    "transition_sidecar",
    "score_evidence_sidecar",
    "ReworkCheckpointInput",
    "SymbolIdentity",
    "SymbolMassEvidence",
    "RECOGNIZED_EXTENSIONS",
    "TransitionScoreEvidence",
    "TransitionReworkEvidence",
    "calculate_problem_rework",
    "calculate_transition_rework",
    "ProductionQualityError",
    "ProductionQualityResult",
    "produce_production_quality",
    "LINEAGE_CONTRACT",
    "produce_production_evidence",
    "build_inventory",
    "WEIGHTS",
    "calculate_problem_score",
    "calculate_regression_breadth",
    "canonical_json_bytes",
    "ranking_key",
    "scoring_schema_bytes",
    "scoring_schema_id",
]
