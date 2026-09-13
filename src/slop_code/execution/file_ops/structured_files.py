from __future__ import annotations

import contextlib
import csv
import json
import os
import sqlite3
import tempfile
from collections.abc import Iterable
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeGuard, TypedDict

from slop_code.execution.file_ops.models import Compression
from slop_code.execution.file_ops.models import FileContent
from slop_code.execution.file_ops.models import FileHandler
from slop_code.execution.file_ops.models import FileType
from slop_code.execution.file_ops.models import InputFileReadError
from slop_code.execution.file_ops.models import InputFileWriteError
from slop_code.execution.file_ops.models import open_stream


def _is_mapping_rows(content: object) -> TypeGuard[list[Mapping[str, object]]]:
    return isinstance(content, list) and all(
        isinstance(row, Mapping) for row in content
    )


def _is_row_sequences(content: object) -> TypeGuard[list[Iterable[object]]]:
    return isinstance(content, list) and all(
        isinstance(row, Iterable) for row in content
    )


type SQLiteRow = dict[str, object]


class SQLiteTable(TypedDict):
    columns: list[str]
    rows: list[SQLiteRow]


type SQLiteTables = dict[str, SQLiteTable]


class SQLitePayload(TypedDict):
    tables: SQLiteTables


class StructuredFileHandler(FileHandler):
    """Base handler that provides shared error handling utilities."""

    requires_tokens: bool = False

    @contextlib.contextmanager
    def open(self, path: Path, mode: str, **kwargs):
        """Open a file stream."""
        try:
            with open_stream(
                path,
                mode,
                compression=self.compression,
                force_use_tokens=self.requires_tokens,
                **kwargs,
            ) as stream:
                yield stream
        except (
            OSError,
            EOFError,
            UnicodeError,
            csv.Error,
            TypeError,
            ValueError,
        ) as exc:
            if "w" in mode:
                raise InputFileWriteError(
                    f"Failed to write {path}: {exc}"
                ) from exc
            raise InputFileReadError(f"Failed to open {path}: {exc}") from exc


class JSONHandler(StructuredFileHandler):
    """Shared logic for reading and writing JSON payloads."""

    file_type: FileType = FileType.JSON
    requires_tokens = True

    def read(self, path: Path) -> FileContent:
        with self.open(path, "r", encoding="utf-8") as stream:
            return json.load(stream)

    def write(self, path: Path, content: FileContent) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.open(path, "w", encoding="utf-8") as stream:
            if isinstance(content, str):
                stream.write(content)
            else:
                json.dump(content, stream, indent=2, ensure_ascii=False)


class JSONLinesHandler(StructuredFileHandler):
    """Shared logic for JSON lines formats."""

    requires_tokens = True

    def read(self, path: Path) -> FileContent:
        with self.open(path, "rt", encoding="utf-8") as stream:
            items: list[Any] = []
            for raw_line in stream:
                raw_line = raw_line.strip()
                if raw_line:
                    items.append(json.loads(raw_line))
            return items

    def _prepare_items(self, content: FileContent) -> list[Any]:
        items = content if isinstance(content, list) else [content]

        return [json.dumps(item, ensure_ascii=False) for item in items]

    def write(self, path: Path, content: FileContent) -> None:
        items = self._prepare_items(content)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.open(path, "w", encoding="utf-8") as stream:
            for item in items:
                stream.write(item + "\n")


class DelimitedHandlerBase(StructuredFileHandler):
    """Shared logic for delimited tabular formats."""

    delimiter: str = ","
    requires_tokens = True

    def read(self, path: Path) -> FileContent:
        with self.open(path, "rt", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, delimiter=self.delimiter)
            return list(reader)

    def write(self, path: Path, content: FileContent) -> None:
        if not isinstance(content, list | Mapping):
            raise InputFileWriteError(
                f"DelimitedHandlerBase require list of dicts/lists or string-convertible "
                f"content, got {type(content).__name__}"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.open(path, "wt", encoding="utf-8", newline="") as stream:
            if isinstance(content, list):
                if _is_mapping_rows(content) and content:
                    fieldnames = content[0].keys()
                    writer = csv.DictWriter(
                        stream,
                        fieldnames=fieldnames,
                        delimiter=self.delimiter,
                    )
                    writer.writeheader()
                    writer.writerows(content)
                elif content:
                    if not _is_row_sequences(content):
                        raise InputFileWriteError(
                            "DelimitedHandlerBase rows must be iterable"
                        )
                    writer = csv.writer(stream, delimiter=self.delimiter)
                    writer.writerows(content)
            else:
                stream.write(str(content))


class TSVHandler(DelimitedHandlerBase):
    """Handler for TSV files."""

    delimiter = "\t"


class SQLiteHandler(StructuredFileHandler):
    """Handler for representing SQLite databases as structured JSON payloads."""

    file_type: FileType = FileType.SQLITE

    def read(self, path: Path) -> FileContent:
        if not path.exists():
            raise InputFileReadError(f"SQLite database does not exist: {path}")

        try:
            tables: SQLiteTables = {}
            with sqlite3.connect(path) as conn:
                conn.row_factory = sqlite3.Row
                for table_name in self._list_tables(conn):
                    query = " ".join(
                        ("SELECT * FROM", self._quote_identifier(table_name))
                    )
                    cursor = conn.execute(query)
                    description = cursor.description
                    if description is None:
                        raise InputFileReadError(
                            f"SQLite query returned no columns for table {table_name!r}"
                        )
                    tables[table_name] = {
                        "columns": [column[0] for column in description],
                        "rows": [dict(row) for row in cursor.fetchall()],
                    }
            return SQLitePayload(tables=tables)
        except sqlite3.Error as exc:
            raise InputFileReadError(
                f"Failed to read SQLite database {path}: {exc}"
            ) from exc

    def write(self, path: Path, content: FileContent) -> None:
        tables = self._normalize_tables(content)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        os.close(descriptor)
        replacement_path = Path(temporary_path)

        try:
            with sqlite3.connect(replacement_path) as conn:
                for table_name, spec in tables.items():
                    self._create_table(
                        conn, table_name, spec["columns"], spec["rows"]
                    )
                conn.commit()
            replacement_path.replace(path)
        except (OSError, sqlite3.Error) as exc:
            raise InputFileWriteError(
                f"Failed to write SQLite database {path}: {exc}"
            ) from exc
        finally:
            replacement_path.unlink(missing_ok=True)

    def _normalize_tables(self, content: FileContent) -> SQLiteTables:
        if isinstance(content, list):
            raw_tables: Mapping[str, object] = {"table": content}
        elif isinstance(content, Mapping):
            raw_content = self._string_keyed_mapping(content, "SQLite payload")
            maybe_tables = raw_content.get("tables")
            if isinstance(maybe_tables, Mapping):
                raw_tables = self._string_keyed_mapping(
                    maybe_tables, "SQLite tables"
                )
            else:
                raw_tables = raw_content
        else:
            raise InputFileWriteError(
                "SQLiteHandler requires list of rows or a mapping of table definitions"
            )

        normalized: SQLiteTables = {}
        for table_name, table_payload in raw_tables.items():
            if not isinstance(table_name, str):
                raise InputFileWriteError("Table names must be strings")
            normalized[table_name] = self._normalize_table_payload(
                table_name, table_payload
            )

        return normalized

    def _normalize_table_payload(
        self,
        table_name: str,
        payload: object,
    ) -> SQLiteTable:
        if isinstance(payload, list):
            rows = [self._normalize_row(table_name, row) for row in payload]
            columns = self._deduce_columns(rows)
        elif isinstance(payload, Mapping):
            table_definition = self._string_keyed_mapping(
                payload, f"Table '{table_name}' definition"
            )
            raw_rows = table_definition.get("rows", [])
            if not isinstance(raw_rows, list):
                raise InputFileWriteError(
                    f"Table '{table_name}' rows must be provided as a list"
                )
            rows = [self._normalize_row(table_name, row) for row in raw_rows]
            columns = table_definition.get("columns")
            if columns is None:
                columns = self._deduce_columns(rows)
            else:
                columns = self._normalize_columns(table_name, columns)
        else:
            raise InputFileWriteError(
                f"Table '{table_name}' must be defined as a list of rows or mapping"
            )

        if not columns:
            raise InputFileWriteError(
                f"Table '{table_name}' must provide columns or at least one populated row"
            )

        return {"columns": columns, "rows": rows}

    def _string_keyed_mapping(
        self, payload: object, label: str
    ) -> dict[str, object]:
        if not isinstance(payload, Mapping):
            raise InputFileWriteError(f"{label} must be a mapping")
        normalized: dict[str, object] = {}
        for key, value in payload.items():
            if not isinstance(key, str):
                raise InputFileWriteError(f"{label} keys must be strings")
            normalized[key] = value
        return normalized

    def _normalize_columns(self, table_name: str, columns: object) -> list[str]:
        if not isinstance(columns, list):
            raise InputFileWriteError(
                f"Columns for table '{table_name}' must be provided as a list of strings"
            )
        seen: set[str] = set()
        normalized: list[str] = []
        for column in columns:
            if not isinstance(column, str):
                raise InputFileWriteError(
                    f"Column names for table '{table_name}' must be strings"
                )
            if column not in seen:
                seen.add(column)
                normalized.append(column)
        if not normalized:
            raise InputFileWriteError(
                f"Table '{table_name}' must contain at least one column"
            )
        return normalized

    def _normalize_row(self, table_name: str, row: object) -> SQLiteRow:
        if not isinstance(row, Mapping):
            raise InputFileWriteError(
                f"Rows for table '{table_name}' must be mappings of column names to values"
            )
        normalized: SQLiteRow = {}
        for key, value in row.items():
            if not isinstance(key, str):
                raise InputFileWriteError(
                    f"Column names for table '{table_name}' must be strings"
                )
            normalized[key] = value
        if not normalized:
            raise InputFileWriteError(
                f"Rows for table '{table_name}' must contain at least one column"
            )
        return normalized

    def _deduce_columns(self, rows: list[SQLiteRow]) -> list[str]:
        ordered_columns: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for column in row:
                if column not in seen:
                    seen.add(column)
                    ordered_columns.append(column)
        return ordered_columns

    def _create_table(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        columns: list[str],
        rows: list[SQLiteRow],
    ) -> None:
        column_types = {
            column: self._infer_sql_type([row.get(column) for row in rows])
            for column in columns
        }
        columns_sql = ", ".join(
            f"{self._quote_identifier(column)} {column_types[column]}"
            for column in columns
        )
        quoted_table_name = self._quote_identifier(table_name)
        conn.execute(" ".join(("DROP TABLE IF EXISTS", quoted_table_name)))
        conn.execute(
            " ".join(("CREATE TABLE", quoted_table_name, f"({columns_sql})"))
        )
        if rows:
            placeholders = ", ".join(["?"] * len(columns))
            quoted_columns = ", ".join(
                self._quote_identifier(column) for column in columns
            )
            insert_sql = " ".join(
                (
                    "INSERT INTO",
                    quoted_table_name,
                    f"({quoted_columns})",
                    "VALUES",
                    f"({placeholders})",
                )
            )
            prepared_rows = [
                [self._prepare_value(row.get(column)) for column in columns]
                for row in rows
            ]
            conn.executemany(insert_sql, prepared_rows)

    def _prepare_value(self, value: object) -> object:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, bytearray):
            return bytes(value)
        if isinstance(value, int | float | str | bytes) or value is None:
            return value
        if isinstance(value, list | dict):
            return json.dumps(value, ensure_ascii=False)
        return value

    def _infer_sql_type(self, values: list[object]) -> str:
        for value in values:
            if value is None:
                continue
            if isinstance(value, bool):
                return "INTEGER"
            if isinstance(value, int):
                return "INTEGER"
            if isinstance(value, float):
                return "REAL"
            if isinstance(value, bytes | bytearray):
                return "BLOB"
            break
        return "TEXT"

    def _list_tables(self, conn: sqlite3.Connection) -> list[str]:
        query = """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
        cursor = conn.execute(query)
        return [row[0] for row in cursor.fetchall()]

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        escaped = identifier.replace('"', '""')
        return f'"{escaped}"'


SETUPS = {
    (JSONHandler, FileType.JSON): {
        Compression.GZIP: {".json.gz"},
        Compression.BZIP2: {".json.bz2"},
        Compression.NONE: {".json"},
    },
    (JSONLinesHandler, FileType.JSONL): {
        Compression.GZIP: {".jsonl.gz", ".ndjson.gz"},
        Compression.BZIP2: {".jsonl.bz2", ".ndjson.bz2"},
        Compression.NONE: {".jsonl", ".ndjson"},
    },
    (DelimitedHandlerBase, FileType.CSV): {
        Compression.GZIP: {".csv.gz"},
        Compression.BZIP2: {".csv.bz2"},
        Compression.NONE: {".csv"},
    },
    (TSVHandler, FileType.TSV): {
        Compression.GZIP: {".tsv.gz"},
        Compression.BZIP2: {".tsv.bz2"},
        Compression.NONE: {".tsv"},
    },
    (SQLiteHandler, FileType.SQLITE): {
        Compression.NONE: {".sqlite", ".sqlite3", ".db"},
    },
}
