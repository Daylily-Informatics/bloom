"""Spreadsheet parsing helpers for Bloom lab-action uploads."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree


@dataclass(frozen=True)
class ParsedSheet:
    name: str
    headers: list[str]
    rows: list[dict[str, Any]]


_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def normalize_header(value: Any) -> str:
    """Normalize operator spreadsheet headers to stable snake_case keys."""
    text = str(value or "").strip().lower()
    replacements = {
        "continer": "container",
        "conteiner": "container",
        "templae": "template",
        "destination": "target",
        "(r)": "",
        "(data)": "",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    text = text.replace("/", " ")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _cell_column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref.upper())
    if not match:
        return 0
    value = 0
    for char in match.group(1):
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def _xml_text(element: ElementTree.Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext())


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    strings: list[str] = []
    for item in root.findall("main:si", _NS):
        strings.append(_xml_text(item))
    return strings


def _sheet_paths(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_by_id = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall("pkgrel:Relationship", _NS)
    }
    sheets: list[tuple[str, str]] = []
    for sheet in workbook.findall("main:sheets/main:sheet", _NS):
        rel_id = sheet.attrib.get(f"{{{_NS['rel']}}}id", "")
        target = rel_by_id.get(rel_id)
        if not target:
            continue
        clean_target = target.lstrip("/")
        path = (
            PurePosixPath(clean_target)
            if clean_target.startswith("xl/")
            else PurePosixPath("xl") / clean_target
        )
        sheets.append((sheet.attrib.get("name", "Sheet"), str(path)))
    return sheets


def _parse_xlsx_sheet(
    archive: zipfile.ZipFile, path: str, shared_strings: list[str]
) -> list[list[Any]]:
    root = ElementTree.fromstring(archive.read(path))
    rows: list[list[Any]] = []
    for row_el in root.findall(".//main:sheetData/main:row", _NS):
        values: list[Any] = []
        for cell in row_el.findall("main:c", _NS):
            col_index = _cell_column_index(cell.attrib.get("r", "A"))
            while len(values) <= col_index:
                values.append(None)
            cell_type = cell.attrib.get("t")
            value_el = cell.find("main:v", _NS)
            if cell_type == "s":
                raw = _xml_text(value_el)
                values[col_index] = (
                    shared_strings[int(raw)] if raw and raw.isdigit() else raw
                )
            elif cell_type == "inlineStr":
                values[col_index] = _xml_text(cell.find("main:is", _NS))
            else:
                raw = _xml_text(value_el)
                values[col_index] = raw if raw != "" else None
        rows.append(values)
    return rows


def _find_header_row(rows: list[list[Any]]) -> int | None:
    best_index = None
    best_score = 0
    for index, row in enumerate(rows[:20]):
        headers = [normalize_header(value) for value in row]
        non_empty = [header for header in headers if header]
        score = len(set(non_empty))
        if any(
            token in set(non_empty)
            for token in {
                "tube_euid",
                "container_euid",
                "source_well_euid",
                "pool_tube_euid",
                "annotation_template_euid",
            }
        ):
            score += 10
        if score > best_score:
            best_score = score
            best_index = index
    return best_index if best_score >= 2 else None


def _rows_to_sheet(name: str, rows: list[list[Any]]) -> ParsedSheet:
    header_index = _find_header_row(rows)
    if header_index is None:
        return ParsedSheet(name=name, headers=[], rows=[])
    headers = [normalize_header(value) for value in rows[header_index]]
    seen: dict[str, int] = {}
    unique_headers: list[str] = []
    for index, header in enumerate(headers):
        if not header:
            header = f"unnamed_{index + 1}"
        count = seen.get(header, 0)
        seen[header] = count + 1
        unique_headers.append(header if count == 0 else f"{header}_{count + 1}")
    parsed_rows: list[dict[str, Any]] = []
    for row in rows[header_index + 1 :]:
        item = {
            header: row[index] if index < len(row) else None
            for index, header in enumerate(unique_headers)
        }
        if any(value not in (None, "") for value in item.values()):
            parsed_rows.append(item)
    return ParsedSheet(name=name, headers=unique_headers, rows=parsed_rows)


def parse_workbook(filename: str, data: bytes) -> list[ParsedSheet]:
    """Parse CSV/XLSX data into normalized sheets.

    This function intentionally avoids optional Excel dependencies so deployed
    Bloom containers can accept simple operator workbooks without changing the
    runtime package set.
    """
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == "csv":
        text = data.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        return [_rows_to_sheet("CSV", list(reader))]
    if suffix != "xlsx":
        raise ValueError("Spreadsheet upload must be .csv or .xlsx")
    sheets: list[ParsedSheet] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        shared_strings = _shared_strings(archive)
        for sheet_name, sheet_path in _sheet_paths(archive):
            rows = _parse_xlsx_sheet(archive, sheet_path, shared_strings)
            sheets.append(_rows_to_sheet(sheet_name, rows))
    return sheets
