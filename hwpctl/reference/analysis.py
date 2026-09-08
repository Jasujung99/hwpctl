"""Static reference inventory for authoring preflight, not an authoring spec.

Extracts the reusable *analysis* responsibility of the private FAQ converter.
No paths, COM, source-specific aliases, default assets, or guessed formatting.
"""
from dataclasses import dataclass
import xml.etree.ElementTree as ET

from hwpctl.reference.grid import GridEvidence, solve_grid_tracks
from hwpctl.reference.model import NormalizedDocument, normalize_hwpml


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].upper()


@dataclass(frozen=True)
class ReferenceAnalysis:
    document: NormalizedDocument
    table_grids: tuple[GridEvidence, ...]
    blockers: tuple[str, ...]
    section_count: int
    table_count: int
    image_count: int

    def require_supported(self) -> None:
        """Fail before any writing; absence of blockers is not rendering fidelity."""
        if self.blockers:
            raise ValueError("Reference requires explicit handling: " + ", ".join(self.blockers))


def analyze_hwpml(hwpml: str) -> ReferenceAnalysis:
    root = ET.fromstring(hwpml)
    if _tag(root) != "HWPML":
        raise ValueError("Expected HWPML, not HWPX section XML")
    document = normalize_hwpml(hwpml)
    sections = [node for node in root.iter() if _tag(node) == "SECTION"]
    tables = [node for node in root.iter() if _tag(node) == "TABLE"]
    blockers = set(document.unsupported)
    if len(sections) != 1:
        blockers.add("section_count_not_one")
    # The comparison model currently holds one table per paragraph. Do not hide
    # a second table or a nested control behind successful normalization.
    for paragraph in (node for node in root.iter() if _tag(node) == "P"):
        if sum(_tag(node) == "TABLE" for node in paragraph.iter()) > 1:
            blockers.add("multiple_or_nested_tables")
    grids = []
    for table in tables:
        try:
            cells = [cell for row in table if _tag(row) == "ROW" for cell in row if _tag(cell) == "CELL"]
            grid = solve_grid_tracks(int(table.attrib["ColCount"]), [
                (int(cell.attrib["ColAddr"]), int(cell.attrib["ColSpan"]), int(cell.attrib["Width"]))
                for cell in cells
            ])
        except (KeyError, ValueError):
            blockers.add("invalid_grid_facts")
            grid = GridEvidence("inconsistent", (), 0)
        if grid.status != "exact":
            blockers.add("grid_" + grid.status)
        grids.append(grid)
    # Unknown controls are reported instead of being silently converted into text.
    known_text_controls = {"CHAR", "TABLE", "SECDEF", "COLDEF", "LINEBREAK", "TAB", "NBSPACE", "FWSPACE"}
    for text in (node for node in root.iter() if _tag(node) == "TEXT"):
        for child in text:
            if _tag(child) not in known_text_controls:
                blockers.add("control:" + _tag(child))
    for attr, definition in (("CharShape", "CHARSHAPE"), ("ParaShape", "PARASHAPE"), ("BorderFill", "BORDERFILL")):
        ids = {node.get("Id") for node in root.iter() if _tag(node) == definition}
        if any(node.get(attr) not in ids for node in root.iter() if attr in node.attrib):
            blockers.add("unresolved:" + attr)
    images = sum(_tag(node) == "IMAGE" for node in root.iter())
    return ReferenceAnalysis(document, tuple(grids), tuple(sorted(blockers)), len(sections), len(tables), images)
