# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Read flat tables from CSV or Parquet into plain Python columns.

Only the requested columns are kept. Row counts are checked before data is
materialised: from the Parquet footer, or while streaming the CSV. Nested
Parquet types are refused. Nothing in a file is ever executed.
"""

from __future__ import annotations

import csv
import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from medagentrx.errors import InputError
from medagentrx.io.limits import Limits
from medagentrx.io.paths import check_size, resolve_input

CSV_SUFFIXES = frozenset({".csv"})
PARQUET_SUFFIXES = frozenset({".parquet", ".pq"})

Cell = str | int | float | bool | None


@dataclass(frozen=True)
class RawTable:
    """Columns read from a file, before any domain checks.

    Attributes:
        source: The path as given by the user, for messages.
        columns: Column name to values, all of equal length.
        n_rows: Number of data rows.
        from_csv: True when values are untyped CSV text.
    """

    source: str
    columns: dict[str, list[Cell]]
    n_rows: int
    from_csv: bool


def read_table(
    path: str | Path,
    *,
    required: Sequence[str],
    optional: Sequence[str] = (),
    all_columns: bool = False,
    limits: Limits | None = None,
    base: Path | None = None,
) -> RawTable:
    """Read a CSV or Parquet file.

    Args:
        path: File to read. The suffix selects the format.
        required: Columns that must be present.
        optional: Columns read when present.
        all_columns: Read every column instead of only the named ones.
        limits: Size limits. Defaults to ``Limits()``.
        base: Directory symlinks may point into.

    Raises:
        InputError: If the file breaks a limit, lacks a column or cannot be parsed.
    """
    limits = limits or Limits()
    source = str(path)
    real = resolve_input(path, base=base)
    check_size(real, max_bytes=limits.max_file_bytes)
    suffix = real.suffix.lower()
    if suffix in CSV_SUFFIXES:
        return _read_csv(real, source, required, optional, all_columns, limits)
    if suffix in PARQUET_SUFFIXES:
        return _read_parquet(real, source, required, optional, all_columns, limits)
    raise InputError(f"{source}: unsupported file type {suffix!r}; use .csv or .parquet")


def peek_columns(
    path: str | Path, *, limits: Limits | None = None, base: Path | None = None
) -> list[str]:
    """Return the column names of a CSV or Parquet file without reading its rows."""
    limits = limits or Limits()
    source = str(path)
    real = resolve_input(path, base=base)
    check_size(real, max_bytes=limits.max_file_bytes)
    suffix = real.suffix.lower()
    try:
        if suffix in CSV_SUFFIXES:
            with real.open("r", encoding="utf-8-sig", newline="") as handle:
                return next(csv.reader(handle), [])
        if suffix in PARQUET_SUFFIXES:
            return list(pq.ParquetFile(real).schema_arrow.names)
    except UnicodeDecodeError as exc:
        raise InputError(f"{source}: not UTF-8 text (byte {exc.start})") from None
    except (csv.Error, pa.ArrowException, OSError) as exc:
        raise InputError(f"{source}: cannot read the header ({exc})") from None
    raise InputError(f"{source}: unsupported file type {suffix!r}; use .csv or .parquet")


def _select(
    source: str,
    header: Sequence[str],
    required: Sequence[str],
    optional: Sequence[str],
    all_columns: bool,
) -> list[str]:
    seen: set[str] = set()
    for name in header:
        if name in seen:
            raise InputError(f"{source}: column {name!r} appears more than once")
        seen.add(name)
    missing = [name for name in required if name not in seen]
    if missing:
        raise InputError(f"{source}: missing required column(s): {', '.join(missing)}")
    if all_columns:
        return list(header)
    wanted = dict.fromkeys([*required, *(name for name in optional if name in seen)])
    return list(wanted)


def _read_csv(
    path: Path,
    source: str,
    required: Sequence[str],
    optional: Sequence[str],
    all_columns: bool,
    limits: Limits,
) -> RawTable:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            header = next(reader, None)
            if header is None:
                raise InputError(f"{source}: the file is empty")
            names = _select(source, header, required, optional, all_columns)
            index = {name: header.index(name) for name in names}
            columns: dict[str, list[Cell]] = {name: [] for name in names}
            n_rows = 0
            for row in reader:
                if not row:
                    continue
                n_rows += 1
                if n_rows > limits.max_rows:
                    raise InputError(f"{source}: more than the limit of {limits.max_rows} rows")
                if len(row) != len(header):
                    raise InputError(
                        f"{source}: line {reader.line_num} has {len(row)} fields, "
                        f"expected {len(header)}"
                    )
                for name, position in index.items():
                    columns[name].append(row[position])
    except UnicodeDecodeError as exc:
        raise InputError(f"{source}: not UTF-8 text (byte {exc.start})") from None
    except csv.Error as exc:
        raise InputError(f"{source}: not valid CSV ({exc})") from None
    return RawTable(source=source, columns=columns, n_rows=n_rows, from_csv=True)


def _read_parquet(
    path: Path,
    source: str,
    required: Sequence[str],
    optional: Sequence[str],
    all_columns: bool,
    limits: Limits,
) -> RawTable:
    try:
        parquet = pq.ParquetFile(path)
        n_rows = parquet.metadata.num_rows
        if n_rows > limits.max_rows:
            raise InputError(f"{source}: {n_rows} rows is more than the limit of {limits.max_rows}")
        schema = parquet.schema_arrow
        names = _select(source, schema.names, required, optional, all_columns)
        for name in names:
            kind = schema.field(name).type
            if not _is_flat(kind):
                raise InputError(
                    f"{source}: column {name!r} has nested type {kind}; use flat columns"
                )
        table = parquet.read(columns=names)
    except InputError:
        raise
    except (pa.ArrowException, OSError) as exc:
        raise InputError(f"{source}: not a readable Parquet file ({exc})") from None
    columns = {name: [_cell(v) for v in table.column(name).to_pylist()] for name in names}
    return RawTable(source=source, columns=columns, n_rows=n_rows, from_csv=False)


def _is_flat(kind: pa.DataType) -> bool:
    if pa.types.is_dictionary(kind):
        return _is_flat(kind.value_type)
    return bool(
        pa.types.is_integer(kind)
        or pa.types.is_floating(kind)
        or pa.types.is_boolean(kind)
        or pa.types.is_string(kind)
        or pa.types.is_large_string(kind)
        or pa.types.is_date(kind)
        or pa.types.is_timestamp(kind)
        or pa.types.is_null(kind)
    )


def _cell(value: object) -> Cell:
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)  # pragma: no cover  # flat Arrow types map to the cases above
