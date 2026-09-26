"""Versioned ordered authoring input. Reference comparison has its own model."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from hwpctl.errors import UsageError

SCHEMA = "hwpctl.blank-rebuild/2"


@dataclass(frozen=True)
class DocumentSpec:
    sections: tuple[dict[str, Any], ...]
    assets: dict[str, dict[str, Any]]
    reference: dict[str, Any]
    digest: str
    base_dir: Path


def mapping(value: Any, where: str, allowed: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UsageError(f"{where}: expected object")
    if allowed is not None and set(value) - allowed:
        raise UsageError(f"{where}: unknown fields {sorted(set(value) - allowed)}")
    return value


def sequence(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise UsageError(f"{where}: expected array")
    return value


def upgrade_v1(raw: dict[str, Any]) -> dict[str, Any]:
    """Preserve v1 operations, including cell paragraph/image order, without I/O."""
    mapping(raw, "spec", {"schema", "reference", "page", "page_number", "assets", "operations"})
    operations = deepcopy(raw.get("operations", []))
    from hwpctl.authoring import legacy
    for index, operation in enumerate(operations):
        if isinstance(operation, dict) and operation.get("kind") == "table":
            if "position" in operation:
                operation["position"] = legacy._table_position(operation["position"], f"operations[{index}].position")
            operation.setdefault("review", True)
    return {"schema": SCHEMA, "reference": deepcopy(raw.get("reference", {})),
            "assets": deepcopy(raw.get("assets", {})), "sections": [{
                "page": deepcopy(raw.get("page", {})),
                "page_number": deepcopy(raw.get("page_number")),
                "content": operations,
            }]}


def parse_spec(raw: dict[str, Any], *, base_dir: Path) -> DocumentSpec:
    mapping(raw, "spec")
    try:
        original = json.dumps(raw, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise UsageError(f"spec must contain finite JSON values: {exc}") from exc
    if raw.get("schema") == "hwpctl.blank-rebuild/1":
        raw = upgrade_v1(raw)
    mapping(raw, "spec", {"schema", "reference", "assets", "sections"})
    if raw.get("schema") != SCHEMA:
        raise UsageError("Unsupported authoring schema")
    sections = sequence(raw.get("sections"), "sections")
    if not sections:
        raise UsageError("sections must not be empty")
    for index, section in enumerate(sections):
        mapping(section, f"sections[{index}]", {"page", "page_number", "content"})
        mapping(section.get("page", {}), "section.page")
        sequence(section.get("content"), "section.content")
    assets = mapping(raw.get("assets", {}), "assets")
    for key, asset in assets.items():
        if not isinstance(key, str) or not key:
            raise UsageError("asset IDs must be non-empty strings")
        mapping(asset, f"assets.{key}", {"path", "sha256"})
        if not isinstance(asset.get("path"), str) or not asset["path"]:
            raise UsageError(f"assets.{key}.path is required")
        digest = asset.get("sha256")
        if digest is not None and (not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest)):
            raise UsageError(f"assets.{key}.sha256 is invalid")
    result = DocumentSpec(tuple(deepcopy(sections)), deepcopy(assets),
                        deepcopy(mapping(raw.get("reference", {}), "reference")),
                        hashlib.sha256(original.encode("utf-8")).hexdigest(), base_dir.resolve())
    from hwpctl.authoring.compiler import compile_spec
    compile_spec(result, check_assets=False)
    return result


def load_spec(path: str | Path) -> DocumentSpec:
    path = Path(path).expanduser().resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        mapping(raw, "spec")
        return parse_spec(raw, base_dir=path.parent)
    except (OSError, ValueError, TypeError) as exc:
        raise UsageError(f"Cannot load authoring spec: {exc}") from exc
