"""Deterministic, bounded production-source inventory classification."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .models import FileRole
from .models import InventoryFile

RECOGNIZED_EXTENSIONS = frozenset(
    {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".java",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".cxx",
        ".hpp",
        ".cs",
        ".kt",
        ".kts",
        ".swift",
        ".scala",
    }
)
_TEST_SEGMENTS = frozenset({"test", "tests", "testing", "__tests__"})
_GENERATED_MARKER = re.compile(
    r"^[ \t]*(?:#|//|/\*)[ \t]*(?:@generated\b|Code generated\b)"
)


@dataclass(frozen=True)
class InventoryResult:
    """Classified immutable snapshot entries and ineligibility evidence."""

    @property
    def eligibility_codes(self) -> tuple[str, ...]:
        """Return the exact ineligibility codes implied by this inventory."""
        return tuple(
            sorted(
                {
                    *self.invalid_codes,
                    *(
                        {"production_language_unsupported"}
                        if self.unsupported_paths
                        else set()
                    ),
                }
            )
        )

    files: tuple[InventoryFile, ...]
    invalid_codes: tuple[str, ...]
    unsupported_paths: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.invalid_codes and not self.unsupported_paths


def _matches_glob(path: str, pattern: str) -> bool:
    """Match the deliberately small, full-path-anchored glob language."""
    path_segments = path.split("/")
    pattern_segments = pattern.split("/")

    def match_segment(value: str, expression: str) -> bool:
        value_index = expression_index = 0
        star_index = retry_index = -1
        while value_index < len(value):
            if expression_index < len(expression) and (
                expression[expression_index] == "?"
                or expression[expression_index] == value[value_index]
            ):
                value_index += 1
                expression_index += 1
            elif (
                expression_index < len(expression)
                and expression[expression_index] == "*"
            ):
                star_index = expression_index
                expression_index += 1
                retry_index = value_index
            elif star_index >= 0:
                expression_index = star_index + 1
                retry_index += 1
                value_index = retry_index
            else:
                return False
        return all(
            character == "*" for character in expression[expression_index:]
        )

    def match(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_segments):
            return path_index == len(path_segments)
        segment = pattern_segments[pattern_index]
        if segment == "**":
            return any(
                match(next_index, pattern_index + 1)
                for next_index in range(path_index, len(path_segments) + 1)
            )
        return (
            path_index < len(path_segments)
            and match_segment(path_segments[path_index], segment)
            and match(path_index + 1, pattern_index + 1)
        )

    return match(0, 0)


def _extension(path: str) -> str | None:
    extension = Path(path).suffix
    return extension if extension in RECOGNIZED_EXTENSIONS else None


def _test_rules(path: str, extension: str) -> list[str]:
    parts = path.split("/")
    basename = parts[-1]
    rules = [
        f"test_segment:{part}" for part in parts[:-1] if part in _TEST_SEGMENTS
    ]
    if basename == "conftest.py":
        rules.append("test_basename:conftest.py")
    if extension == ".py" and (
        basename.startswith("test_")
        and basename.endswith(".py")
        or basename.endswith("_test.py")
    ):
        rules.append("test_basename:python")
    stem = basename[: -len(extension)]
    if stem.endswith(".test") or stem.endswith(".spec"):
        rules.append("test_basename:dot_test_or_spec")
    return rules


def _relative_target(root: Path, target: Path) -> str | None:
    try:
        return target.relative_to(root).as_posix()
    except ValueError:
        return None


def _iter_entries(root: Path) -> Iterable[tuple[str, Path, bool]]:
    """Yield lexical file paths in raw UTF-8-byte order without following dirs."""
    root_bytes = os.fsencode(root)

    def walk(
        directory: bytes, components: tuple[str, ...]
    ) -> Iterable[tuple[str, Path, bool]]:
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        decoded: list[tuple[bytes, str, os.DirEntry[bytes]]] = []
        for entry in entries:
            try:
                component = entry.name.decode("utf-8", "strict")
            except UnicodeDecodeError:
                yield "", Path(os.fsdecode(entry.path)), False
                continue
            decoded.append((entry.name, component, entry))
        for _, component, entry in sorted(decoded, key=lambda item: item[0]):
            path_components = (*components, component)
            lexical_path = "/".join(path_components)
            entry_path = Path(os.fsdecode(entry.path))
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError:
                yield lexical_path, entry_path, False
                continue
            if stat.S_ISDIR(mode):
                yield from walk(entry.path, path_components)
            elif stat.S_ISLNK(mode) or stat.S_ISREG(mode):
                yield lexical_path, entry_path, stat.S_ISLNK(mode)

    yield from walk(root_bytes, ())


def build_inventory(
    root: Path,
    *,
    generated_globs: Iterable[str] = (),
    test_globs: Iterable[str] = (),
) -> InventoryResult:
    """Inventory source files using lexical paths and role-precedence evidence."""
    resolved_root = root.resolve(strict=True)
    generated_globs = tuple(generated_globs)
    test_globs = tuple(test_globs)
    files: list[InventoryFile] = []
    invalid_codes: set[str] = set()
    unsupported_paths: list[str] = []

    for lexical_path, filesystem_path, is_symlink in _iter_entries(
        resolved_root
    ):
        if not lexical_path:
            invalid_codes.add("score_evidence_invalid")
            continue
        symlink_text = str(filesystem_path.readlink()) if is_symlink else None
        if is_symlink:
            try:
                symlink_target = filesystem_path.resolve(strict=True)
                if stat.S_ISDIR(symlink_target.stat().st_mode):
                    continue
                if _relative_target(
                    resolved_root, symlink_target
                ) is None or not stat.S_ISREG(symlink_target.stat().st_mode):
                    invalid_codes.add("score_evidence_invalid")
            except OSError:
                invalid_codes.add("score_evidence_invalid")
        extension = _extension(lexical_path)
        if extension is None:
            files.append(
                InventoryFile(
                    path=lexical_path,
                    lexical_path=lexical_path,
                    role=FileRole.IGNORED,
                    ignored_reason="extensionless"
                    if not Path(lexical_path).suffix
                    else "unrecognized_extension",
                    is_symlink=is_symlink,
                    symlink_target=symlink_text,
                )
            )
            continue
        resolved_path: str | None = None
        source_bytes: bytes | None = None
        if is_symlink:
            try:
                target = filesystem_path.resolve(strict=True)
                resolved_path = _relative_target(resolved_root, target)
                if stat.S_ISDIR(target.stat().st_mode):
                    continue
                if resolved_path is None or not stat.S_ISREG(
                    target.stat().st_mode
                ):
                    raise OSError(
                        "symlink target is not an in-root regular file"
                    )
                source_bytes = target.read_bytes()
            except OSError:
                invalid_codes.add("score_evidence_invalid")
        else:
            try:
                source_bytes = filesystem_path.read_bytes()
            except OSError:
                invalid_codes.add("score_evidence_invalid")
        decoded_lines: list[str] = []
        if source_bytes is not None:
            try:
                decoded_lines = source_bytes.decode(
                    "utf-8", "strict"
                ).splitlines()[:5]
            except UnicodeDecodeError:
                invalid_codes.add("score_evidence_invalid")
        generated_rules = [
            f"generated_glob:{pattern}"
            for pattern in generated_globs
            if _matches_glob(lexical_path, pattern)
        ]
        if any(_GENERATED_MARKER.match(line) for line in decoded_lines):
            generated_rules.append("generated_marker")
        test_rules = [
            f"test_glob:{pattern}"
            for pattern in test_globs
            if _matches_glob(lexical_path, pattern)
        ] + _test_rules(lexical_path, extension)
        matched_rules = (*generated_rules, *test_rules)
        if source_bytes is None or (
            source_bytes is not None and not decoded_lines and source_bytes
        ):
            files.append(
                InventoryFile(
                    path=lexical_path,
                    lexical_path=lexical_path,
                    role=FileRole.IGNORED,
                    recognized_extension=extension,
                    matched_rules=matched_rules,
                    ignored_reason="source_unreadable_or_non_utf8",
                    is_symlink=is_symlink,
                    resolved_path=resolved_path,
                    symlink_target=symlink_text,
                )
            )
            continue
        role = (
            FileRole.GENERATED
            if generated_rules
            else FileRole.TEST
            if test_rules
            else FileRole.PRODUCTION
        )
        if role is FileRole.PRODUCTION and extension != ".py":
            unsupported_paths.append(lexical_path)
        files.append(
            InventoryFile(
                path=lexical_path,
                lexical_path=lexical_path,
                role=role,
                source_hash=hashlib.sha256(source_bytes).hexdigest(),
                recognized_extension=extension,
                matched_rules=matched_rules,
                is_symlink=is_symlink,
                resolved_path=resolved_path,
                symlink_target=symlink_text,
            )
        )

    return InventoryResult(
        files=tuple(files),
        invalid_codes=tuple(sorted(invalid_codes)),
        unsupported_paths=tuple(unsupported_paths),
    )
