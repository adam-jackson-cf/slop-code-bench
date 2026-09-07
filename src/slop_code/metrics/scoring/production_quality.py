"""Deterministic production-only verbosity and erosion evidence producers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN
from decimal import Decimal
from decimal import localcontext
from pathlib import Path
from typing import Any, Literal, Protocol, TypeGuard

from .contract import EXPECTED_INTERPRETER
from .contract import EXPECTED_RUFF_VERSION
from .contract import PARSER_TOKENIZER_PROBE
from .contract import RUFF_ARGUMENTS
from .contract import RUFF_RULES
from .models import EligibleSymbolEvidence
from .models import ExcludedSymbolEvidence
from .models import FileRole
from .models import InventoryFile
from .models import ProductionQualityRawEvidence
from .models import QualityCloneGroupEvidence
from .models import QualityDecimalContextEvidence
from .models import QualityFileEvidence
from .models import QualityInterpreterEvidence
from .models import QualityRuffDiagnosticEvidence
from .models import QualityRuffEvidence
from .models import SymbolExclusionReason


@dataclass(frozen=True)
class _ProcessResult:
    returncode: int
    stdout: str
    stderr: str


class ProcessExecutor(Protocol):
    """Execute one argv-only measurement process."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        stdin: str | None = None,
    ) -> _ProcessResult: ...


@dataclass(frozen=True)
class DockerProcessExecutor:
    """Execute measurement commands in the run's immutable Docker runtime."""

    image: str
    mount_root: Path
    binary: str = "docker"

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        stdin: str | None = None,
    ) -> _ProcessResult:
        mount_root = self.mount_root.resolve()
        executable = Path(argv[0])
        if not executable.is_absolute() or not executable.is_relative_to(
            mount_root
        ):
            raise ProductionQualityError(
                "measurement_environment_mismatch: evaluator executable "
                "is outside the mounted run"
            )
        command = [
            self.binary,
            "run",
            "--rm",
            "--interactive",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--tmpfs",
            "/run:rw,exec,nosuid,size=256m,mode=1777",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "RUFF_CACHE_DIR=/run/ruff-cache",
            "--mount",
            f"type=bind,source={mount_root},target={mount_root},readonly",
        ]
        if cwd is not None:
            working_directory = cwd.resolve()
            try:
                working_directory.relative_to(mount_root)
            except ValueError as error:
                raise ProductionQualityError(
                    "measurement_environment_mismatch: measurement working "
                    "directory is outside the mounted run"
                ) from error
            command.extend(("--workdir", str(working_directory)))
        command.extend((self.image, *argv))
        try:
            completed = _execute(command, stdin=stdin)
        except OSError as error:
            raise ProductionQualityError(
                "measurement_environment_mismatch: Docker runtime unavailable"
            ) from error
        if completed.returncode in {125, 126, 127}:
            raise ProductionQualityError(
                "measurement_environment_mismatch: Docker measurement failed"
            )
        return completed


def _execute(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    stdin: str | None = None,
) -> _ProcessResult:
    """Execute an argv-only process and collect UTF-8 standard streams."""

    async def communicate() -> _ProcessResult:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(
            stdin.encode("utf-8") if stdin is not None else None
        )
        returncode = process.returncode
        if returncode is None:
            raise RuntimeError("process did not terminate")
        return _ProcessResult(
            returncode=returncode,
            stdout=stdout.decode("utf-8"),
            stderr=stderr.decode("utf-8"),
        )

    return asyncio.run(communicate())


class ProductionQualityError(ValueError):
    """Evidence cannot be used to compute a production-quality component."""


@dataclass(frozen=True)
class ProductionQualityResult:
    """Components with their complete typed raw evidence."""

    verbosity: Decimal
    erosion: Decimal
    evidence: ProductionQualityRawEvidence


def _is_string_mapping(row: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(row, Mapping) and all(isinstance(key, str) for key in row)


def _validate_measurement_environment(
    payload: Mapping[str, object],
    *,
    expected_executable_sha256: str | None,
) -> None:
    """Reject evidence that was not measured under the frozen evaluator contract."""
    interpreter = payload.get("interpreter")
    schema_id = payload.get("parser_tokenizer_schema_id")
    probe = payload.get("parser_tokenizer_probe")
    if not _is_string_mapping(interpreter):
        raise ProductionQualityError("measurement_environment_mismatch")
    version = interpreter.get("version")
    if (
        interpreter.get("implementation")
        != EXPECTED_INTERPRETER["implementation"]
        or interpreter.get("cache_tag") != EXPECTED_INTERPRETER["cache_tag"]
        or not isinstance(version, str)
        or not version.startswith(f"{EXPECTED_INTERPRETER['version']}.")
        or (
            expected_executable_sha256 is not None
            and interpreter.get("executable_sha256")
            != expected_executable_sha256
        )
        or probe != PARSER_TOKENIZER_PROBE.hex()
        or not isinstance(schema_id, str)
        or len(schema_id) != 64
        or any(character not in "0123456789abcdef" for character in schema_id)
    ):
        raise ProductionQualityError("measurement_environment_mismatch")


def _value(row: object, *names: str) -> object:
    mapping: Mapping[str, object] | None = None
    if isinstance(row, Mapping):
        if not _is_string_mapping(row):
            raise ProductionQualityError(
                "score_evidence_invalid: evidence mapping keys must be strings"
            )
        mapping = row
    for name in names:
        if mapping is not None and name in mapping:
            return mapping[name]
        if hasattr(row, name):
            return getattr(row, name)
    return None


def _identity(file: InventoryFile | Mapping[str, Any] | object) -> str:
    path = _value(file, "path", "file_path")
    if (
        not isinstance(path, str)
        or not path
        or path.startswith("/")
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise ProductionQualityError(
            "score_evidence_invalid: invalid lexical file identity"
        )
    try:
        path.encode("utf-8", "strict")
    except UnicodeError as error:
        raise ProductionQualityError(
            "score_evidence_invalid: invalid lexical file identity"
        ) from error
    return path


def _production_files(
    inventory: Iterable[InventoryFile | Mapping[str, Any] | object],
) -> tuple[object, ...]:
    selected = [
        item
        for item in inventory
        if _value(item, "role") == FileRole.PRODUCTION
        or _value(item, "role") == "production"
    ]
    selected = [item for item in selected if _identity(item).endswith(".py")]
    paths = [_identity(item) for item in selected]
    if len(paths) != len(set(paths)):
        raise ProductionQualityError(
            "score_evidence_invalid: duplicate inventory identity"
        )
    return tuple(
        sorted(selected, key=lambda item: _identity(item).encode("utf-8"))
    )


def _verified_payload(
    executable: Path,
    sources: Mapping[str, bytes],
    *,
    executor: ProcessExecutor | None = None,
) -> dict[str, Any]:
    """Use the evaluator interpreter for token and AST semantics, never this host."""
    program = r"""import ast, hashlib, json, sys, tokenize
from io import BytesIO
payload=json.loads(sys.stdin.read())
def digest(path):
    return hashlib.sha256(open(path,'rb').read()).hexdigest()
probe=b"x = 1\nif x:\n    y = 'z'\n"
schema=hashlib.sha256((sys.implementation.name+'|'+sys.version+'|'+sys.implementation.cache_tag+'|'+digest(ast.__file__)+'|'+digest(tokenize.__file__)+'|'+probe.hex()+'|'+repr([(t.type,t.string,t.start,t.end) for t in tokenize.tokenize(BytesIO(probe).readline)])+'|'+ast.dump(ast.parse(probe),annotate_fields=True,include_attributes=False)).encode()).hexdigest()
def loc(data):
    lines=set()
    for token in tokenize.tokenize(BytesIO(data).readline):
        if tokenize.tok_name[token.type] not in {'ENCODING','ENDMARKER','NEWLINE','NL','INDENT','DEDENT','COMMENT'}:
            lines.update(range(token.start[0], token.end[0]+1))
    return sorted(line for line in lines if line > 0)
def stmt_lists(node):
    result=[]
    for parent in ast.walk(node):
        for field, value in ast.iter_fields(parent):
            if isinstance(value,list) and value and all(isinstance(x,ast.stmt) for x in value): result.append(value)
    return result
def vectors(path, data, source_lines):
    tree=ast.parse(data); result=[]
    source=set(source_lines)
    for statements in stmt_lists(tree):
        dumps=[ast.dump(s,annotate_fields=True,include_attributes=False) for s in statements]
        for start in range(len(statements)):
            for end in range(start+6,len(statements)+1):
                span=(statements[start].lineno, statements[end-1].end_lineno)
                if sum(line in source for line in range(span[0],span[1]+1)) >= 12:
                    result.append((tuple(dumps[start:end]),(path,*span)))
    return result
files=[]; candidates={}
for item in payload['files']:
    data=bytes.fromhex(item['bytes'])
    try:
        source_lines=loc(data)
        for vector, occurrence in vectors(item['path'],data,source_lines): candidates.setdefault(vector,[]).append(occurrence)
    except Exception as error:
        print(json.dumps({'error':str(error)})); raise SystemExit(2)
    files.append({'path':item['path'],'hash':hashlib.sha256(data).hexdigest(),'source_lines':source_lines})
accepted=[]
for vector, occurrences in candidates.items():
    chosen=[]
    for occurrence in sorted(occurrences):
        if all(occurrence[0] != old[0] or occurrence[2] < old[1] or old[2] < occurrence[1] for old in chosen): chosen.append(occurrence)
    if len(chosen)>=2: accepted.append((vector,tuple(chosen)))
maximal=[]
for vector, occurrences in accepted:
    if not any(len(other)>len(vector) and any(tuple(other[i:i+len(vector)])==vector for i in range(len(other)-len(vector)+1)) for other,_ in accepted): maximal.append((vector,occurrences))
groups=[{'vector':list(vector),'occurrences':[list(occurrence) for occurrence in occurrences]} for vector,occurrences in sorted(maximal,key=lambda pair:(pair[0],pair[1]))]
print(json.dumps({'interpreter':{'executable':sys.executable,'implementation':sys.implementation.name,'version':sys.version,'cache_tag':sys.implementation.cache_tag,'executable_sha256':digest(sys.executable),'ast_sha256':digest(ast.__file__),'tokenize_sha256':digest(tokenize.__file__)},'parser_tokenizer_probe':probe.hex(),'parser_tokenizer_schema_id':schema,'files':files,'clone_groups':groups},sort_keys=True,separators=(',',':')))"""
    process_executor = _execute if executor is None else executor
    completed = process_executor(
        [str(executable), "-c", program],
        stdin=json.dumps(
            {
                "files": [
                    {"path": path, "bytes": data.hex()}
                    for path, data in sources.items()
                ]
            }
        ),
    )
    if completed.returncode:
        raise ProductionQualityError(
            f"score_evidence_invalid: evaluator parser failed: {completed.stderr or completed.stdout}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ProductionQualityError(
            "score_evidence_invalid: evaluator emitted malformed evidence"
        ) from error


def _ruff(
    executable: Path,
    root: Path,
    paths: Sequence[str],
    *,
    executor: ProcessExecutor | None = None,
) -> tuple[str, tuple[dict[str, Any], ...], tuple[str, ...]]:
    process_executor = _execute if executor is None else executor
    try:
        version_result = process_executor(
            [str(executable), "-m", "ruff", "--version"]
        )
    except OSError as error:
        raise ProductionQualityError(
            "measurement_environment_mismatch: Ruff unavailable"
        ) from error
    version = version_result.stdout.strip()
    if (
        version_result.returncode != 0
        or version != f"ruff {EXPECTED_RUFF_VERSION}"
    ):
        raise ProductionQualityError(
            "measurement_environment_mismatch: Ruff version mismatch"
        )
    invocation = (str(executable), *RUFF_ARGUMENTS, *paths)
    try:
        done = process_executor(invocation, cwd=root)
    except OSError as error:
        raise ProductionQualityError(
            "measurement_environment_mismatch: Ruff unavailable"
        ) from error
    if done.returncode not in (0, 1):
        raise ProductionQualityError(
            "measurement_environment_mismatch: canonical Ruff rule unavailable"
        )
    try:
        diagnostics = json.loads(done.stdout)
    except json.JSONDecodeError as error:
        raise ProductionQualityError(
            "score_evidence_invalid: Ruff emitted malformed JSON"
        ) from error
    if not isinstance(diagnostics, list):
        raise ProductionQualityError(
            "score_evidence_invalid: Ruff diagnostics are not a list"
        )
    normalized = []
    for item in diagnostics:
        code = item.get("code")
        location = item.get("location")
        end = item.get("end_location")
        filename = item.get("filename")
        if (
            not isinstance(location, Mapping)
            or not isinstance(end, Mapping)
            or not isinstance(filename, str)
        ):
            raise ProductionQualityError(
                "score_evidence_invalid: unexpected Ruff diagnostic"
            )
        reported_path = Path(filename)
        try:
            lexical_path = (
                reported_path.relative_to(root).as_posix()
                if reported_path.is_absolute()
                else reported_path.as_posix()
            )
        except ValueError as error:
            raise ProductionQualityError(
                "score_evidence_invalid: Ruff path is outside production inventory"
            ) from error
        if lexical_path not in paths:
            raise ProductionQualityError(
                "score_evidence_invalid: Ruff path is outside production inventory"
            )
        try:
            (root / lexical_path).resolve().relative_to(root.resolve())
        except ValueError as error:
            raise ProductionQualityError(
                "score_evidence_invalid: Ruff path is outside production inventory"
            ) from error
        try:
            start = (int(location["row"]), int(location["column"]))
            finish = (int(end["row"]), int(end["column"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ProductionQualityError(
                "score_evidence_invalid: malformed Ruff range"
            ) from error
        if start < (1, 1) or finish <= start:
            raise ProductionQualityError(
                "score_evidence_invalid: invalid Ruff range"
            )
        if code is None:
            message = item.get("message")
            if not isinstance(message, str) or not message.startswith(
                "SyntaxError:"
            ):
                raise ProductionQualityError(
                    "score_evidence_invalid: unexpected Ruff diagnostic"
                )
            continue
        if code not in RUFF_RULES:
            raise ProductionQualityError(
                "score_evidence_invalid: unexpected Ruff diagnostic"
            )
        normalized.append(
            {
                "code": code,
                "path": lexical_path,
                "start": start,
                "end": finish,
            }
        )
    return (
        version,
        tuple(
            sorted(
                normalized,
                key=lambda item: (
                    item["path"].encode(),
                    item["start"],
                    item["end"],
                    item["code"],
                ),
            )
        ),
        invocation,
    )


def produce_production_quality(
    checkpoint_id: str,
    root: Path,
    inventory: Iterable[object],
    file_rows: Iterable[object],
    symbol_rows: Iterable[object],
    evaluator_executable: Path,
    *,
    executor: ProcessExecutor | None = None,
    expected_executable_sha256: str | None = None,
) -> ProductionQualityResult:
    """Produce V/E from canonical inventory and existing successful metric rows."""
    if not checkpoint_id:
        raise ProductionQualityError(
            "score_evidence_invalid: checkpoint identity missing"
        )
    root = root.resolve()
    files = _production_files(inventory)
    paths = tuple(_identity(item) for item in files)
    joined = {}
    for row in file_rows:
        path = _value(row, "path", "file_path")
        if isinstance(path, str):
            if path in joined:
                raise ProductionQualityError(
                    "score_evidence_invalid: duplicate file row"
                )
            joined[path] = row
    if set(joined) & set(paths) != set(paths):
        raise ProductionQualityError(
            "score_evidence_invalid: missing production file row"
        )
    if any(_value(joined[path], "success") is not True for path in paths):
        raise ProductionQualityError(
            "score_evidence_invalid: unsuccessful file row"
        )
    sources = {}
    for path in paths:
        target = (root / path).resolve()
        try:
            target.relative_to(root)
            data = target.read_bytes()
        except (OSError, ValueError) as error:
            raise ProductionQualityError(
                "score_evidence_invalid: production source unreadable"
            ) from error
        sources[path] = data
    payload = (
        _verified_payload(Path(evaluator_executable), sources)
        if executor is None
        else _verified_payload(
            Path(evaluator_executable), sources, executor=executor
        )
    )
    _validate_measurement_environment(
        payload,
        expected_executable_sha256=expected_executable_sha256,
    )
    source_by_path = {
        item["path"]: set(item["source_lines"]) for item in payload["files"]
    }
    denominator = sum(len(lines) for lines in source_by_path.values())
    if not denominator:
        raise ProductionQualityError("production_source_loc_zero")
    quality_arguments = (Path(evaluator_executable), root, paths)
    version, diagnostics, invocation = (
        _ruff(*quality_arguments)
        if executor is None
        else _ruff(*quality_arguments, executor=executor)
    )
    verbosity = set()
    clone_lines = set()
    clone_groups = []
    for diagnostic in diagnostics:
        eligible = source_by_path.get(diagnostic["path"])
        if eligible is None:
            raise ProductionQualityError(
                "score_evidence_invalid: Ruff path is outside production inventory"
            )
        verbosity.update(
            (diagnostic["path"], line)
            for line in range(
                diagnostic["start"][0],
                diagnostic["end"][0] + (diagnostic["end"][1] > 1),
            )
            if line in eligible
        )
    for group in payload["clone_groups"]:
        clone_groups.append(group)
        for path, start, end in group["occurrences"]:
            clone_lines.update(
                (path, line)
                for line in range(start, end + 1)
                if line in source_by_path[path]
            )
    numerator = len(verbosity | clone_lines)
    if numerator > denominator:
        raise ProductionQualityError(
            "score_evidence_invalid: verbosity numerator exceeds source LOC"
        )
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        verbosity_component = Decimal(1) - Decimal(numerator) / Decimal(
            denominator
        )
        symbols: list[EligibleSymbolEvidence] = []
        excluded_symbols: list[ExcludedSymbolEvidence] = []
        identities = set()
        total = Decimal(0)
        erosion_mass = Decimal(0)
        for row in symbol_rows:
            kind = _value(row, "kind", "type")
            path = _value(row, "path", "file_path")
            if kind not in {"function", "method"}:
                excluded_symbols.append(
                    ExcludedSymbolEvidence(
                        reason=SymbolExclusionReason.KIND_INELIGIBLE,
                        kind=kind if isinstance(kind, str) else "",
                        path=path if isinstance(path, str) else "",
                    )
                )
                continue
            eligible_kind: Literal["function", "method"] = (
                "function" if kind == "function" else "method"
            )
            if not isinstance(path, str) or path not in paths:
                excluded_symbols.append(
                    ExcludedSymbolEvidence(
                        reason=SymbolExclusionReason.PATH_NOT_PRODUCTION,
                        kind=eligible_kind,
                        path=path if isinstance(path, str) else "",
                    )
                )
                continue
            eligible_kind: Literal["function", "method"] = (
                "function" if kind == "function" else "method"
            )
            qualified = _value(row, "qualified_name", "name")
            start = _value(row, "start_line", "start")
            end = _value(row, "end_line", "end")
            if (
                not isinstance(qualified, str)
                or not qualified
                or isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, int)
                or not isinstance(end, int)
                or start <= 0
                or end <= 0
            ):
                raise ProductionQualityError(
                    "production_symbol_evidence_invalid"
                )
            identity = (path, qualified, eligible_kind, start, end)
            if end < start or identity in identities:
                raise ProductionQualityError(
                    "production_symbol_evidence_invalid"
                )
            identities.add(identity)
            raw_cc = _value(row, "cc", "complexity")
            raw_loc = _value(row, "sloc", "SLOC")
            if (
                isinstance(raw_cc, bool)
                or isinstance(raw_loc, bool)
                or not isinstance(raw_loc, int)
                or raw_loc <= 0
            ):
                raise ProductionQualityError(
                    "production_symbol_evidence_invalid"
                )
            try:
                cc = Decimal(str(raw_cc))
            except Exception as error:
                raise ProductionQualityError(
                    "production_symbol_evidence_invalid"
                ) from error
            if not cc.is_finite() or cc < 0 or str(cc) != str(raw_cc):
                raise ProductionQualityError(
                    "production_symbol_evidence_invalid"
                )
            mass = cc * Decimal(raw_loc).sqrt()
            total += mass
            high = cc > 10
            if high:
                erosion_mass += mass
            symbols.append(
                EligibleSymbolEvidence(
                    identity=identity,
                    cc=cc,
                    sloc=raw_loc,
                    mass=mass,
                    high_complexity=high,
                )
            )
        symbols.sort(key=lambda symbol: symbol.identity)
        excluded_symbols.sort(
            key=lambda symbol: (
                symbol.reason.value,
                symbol.path.encode("utf-8"),
                symbol.kind.encode("utf-8"),
            )
        )
        erosion = (
            Decimal(1) if total == 0 else Decimal(1) - erosion_mass / total
        )
    if not (
        Decimal(0) <= verbosity_component <= Decimal(1)
        and Decimal(0) <= erosion <= Decimal(1)
    ):
        raise ProductionQualityError(
            "score_evidence_invalid: component out of range"
        )
    typed_evidence = ProductionQualityRawEvidence(
        checkpoint_id=checkpoint_id,
        interpreter=QualityInterpreterEvidence.model_validate(
            payload["interpreter"]
        ),
        parser_tokenizer_schema_id=payload["parser_tokenizer_schema_id"],
        parser_tokenizer_probe=payload["parser_tokenizer_probe"],
        files=tuple(
            QualityFileEvidence.model_validate(item)
            for item in payload["files"]
        ),
        ruff=QualityRuffEvidence(
            version=version,
            invocation=invocation,
            rules=RUFF_RULES,
            diagnostics=tuple(
                QualityRuffDiagnosticEvidence.model_validate(item)
                for item in diagnostics
            ),
        ),
        clones=tuple(
            QualityCloneGroupEvidence.model_validate(group)
            for group in clone_groups
        ),
        verbosity_lines=tuple(sorted(verbosity)),
        clone_lines=tuple(sorted(clone_lines)),
        union_numerator=numerator,
        source_loc_denominator=denominator,
        eligible_symbols=tuple(symbols),
        excluded_symbols=tuple(excluded_symbols),
        erosion_numerator=erosion_mass,
        erosion_denominator=total,
        decimal_context=QualityDecimalContextEvidence(
            precision=50, rounding="ROUND_HALF_EVEN"
        ),
        verbosity=verbosity_component,
        erosion=erosion,
    )
    return ProductionQualityResult(verbosity_component, erosion, typed_evidence)
