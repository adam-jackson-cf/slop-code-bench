"""Bounded Phase 2 production evidence orchestration."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import networkx as nx

from .inventory import InventoryResult
from .models import ELIGIBILITY_CODES
from .models import Eligibility
from .models import ProductionEvidence
from .models import ProductionGraphEvidence
from .models import ProductionQualityRawEvidence
from .production_graph import ProductionGraphError
from .production_graph import produce_production_graph
from .production_quality import ProcessExecutor
from .production_quality import ProductionQualityError
from .production_quality import produce_production_quality

PRODUCTION_QUALITY_FILENAME = "production_quality.json"
PRODUCTION_GRAPH_FILENAME = "production_graph.json"


class ProductionEvidenceResult(ProductionEvidence):
    """The only Phase 2 producer result for one checkpoint snapshot."""

    @property
    def payloads(
        self,
    ) -> dict[str, ProductionQualityRawEvidence | ProductionGraphEvidence]:
        """Return canonical artifact names paired with typed payloads."""
        payloads: dict[
            str, ProductionQualityRawEvidence | ProductionGraphEvidence
        ] = {}
        if self.production_quality is not None:
            payloads[PRODUCTION_QUALITY_FILENAME] = self.production_quality
        if self.production_graph is not None:
            payloads[PRODUCTION_GRAPH_FILENAME] = self.production_graph
        return payloads


def _reason(error: Exception) -> str:
    message = str(error)
    candidate = message.split(":", maxsplit=1)[0]
    return (
        candidate
        if candidate in ELIGIBILITY_CODES
        else "score_evidence_invalid"
    )


def _inventory_reasons(inventory: InventoryResult) -> set[str]:
    return set(inventory.eligibility_codes)


def produce_production_evidence(
    checkpoint_id: str,
    root: Path,
    inventory: InventoryResult,
    file_rows: Iterable[object],
    symbol_rows: Iterable[object],
    graph_rows: nx.DiGraph,
    evaluator_executable: Path,
    *,
    executor: ProcessExecutor | None = None,
    expected_executable_sha256: str | None = None,
) -> ProductionEvidenceResult:
    """Produce typed V/E/H evidence from one immutable inventory snapshot.

    Quality and graph production are deliberately independent so every
    input-caused eligibility reason is reported in deterministic code order.
    This producer never reads or writes legacy all-source quality artifacts.
    """
    reasons = _inventory_reasons(inventory)
    quality: ProductionQualityRawEvidence | None = None
    graph: ProductionGraphEvidence | None = None

    try:
        quality_args = {}
        if executor is not None:
            quality_args["executor"] = executor
        if expected_executable_sha256 is not None:
            quality_args["expected_executable_sha256"] = (
                expected_executable_sha256
            )
        quality_result = produce_production_quality(
            checkpoint_id,
            root,
            inventory.files,
            file_rows,
            symbol_rows,
            evaluator_executable,
            **quality_args,
        )
        quality = quality_result.evidence
    except (ProductionQualityError, ValueError) as error:
        reasons.add(_reason(error))

    try:
        graph_result = produce_production_graph(
            checkpoint_id, inventory.files, graph_rows
        )
        graph = ProductionGraphEvidence.model_validate(graph_result.evidence)
    except (ProductionGraphError, ValueError) as error:
        reasons.add(_reason(error))

    eligibility = Eligibility(
        eligible=not reasons, reasons=tuple(sorted(reasons))
    )
    return ProductionEvidenceResult(
        eligibility=eligibility,
        production_quality=quality,
        production_graph=graph,
    )
