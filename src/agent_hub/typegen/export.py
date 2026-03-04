"""Generate TypeScript interfaces from all AgentHub Pydantic models.

Usage::

    python -m agent_hub.typegen.export > frontend/src/types/generated.ts

The script:

1. Collects every Pydantic model exposed in ``agent_hub.models``.
2. Collects Annotated union types (ServerMessage, ClientMessage, etc.).
3. Collects StrEnum types (DiffMode, etc.).
4. Calls ``model_json_schema()`` on each model to obtain a JSON Schema.
5. Converts the JSON Schema tree into clean TypeScript ``export interface``
   and ``export type`` declarations.
6. Writes the result to *stdout* so it can be piped to a file.
"""

from __future__ import annotations

import json
import sys
from collections import OrderedDict
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# 1. Collect all Pydantic models, Annotated unions, and StrEnums
# ---------------------------------------------------------------------------

import agent_hub.models as _models_pkg  # noqa: E402

_ALL_MODELS: list[type[BaseModel]] = []
_ANNOTATED_UNIONS: dict[str, list[type[BaseModel]]] = {}
_STR_ENUMS: dict[str, list[str]] = {}

for _attr_name in dir(_models_pkg):
    _obj = getattr(_models_pkg, _attr_name)
    if isinstance(_obj, type) and issubclass(_obj, BaseModel) and _obj is not BaseModel:
        _ALL_MODELS.append(_obj)
    elif isinstance(_obj, type) and issubclass(_obj, StrEnum) and _obj is not StrEnum:
        _STR_ENUMS[_attr_name] = [m.value for m in _obj]
    elif get_origin(_obj) is Annotated:
        # Annotated union types like ServerMessage, ClientMessage
        args = get_args(_obj)
        if args:
            inner = args[0]
            # UnionType (X | Y | Z) — get_args extracts the union members
            members = get_args(inner)
            if members and all(
                isinstance(m, type) and issubclass(m, BaseModel)
                for m in members
            ):
                _ANNOTATED_UNIONS[_attr_name] = list(members)

# Deterministic output order — sort by class name
_ALL_MODELS.sort(key=lambda cls: cls.__name__)

# ---------------------------------------------------------------------------
# 2. JSON Schema -> TypeScript helpers
# ---------------------------------------------------------------------------

# Track emitted interface/type names so we don't duplicate
_emitted: set[str] = set()

# Collect all output lines
_output_lines: list[str] = []


def _ts_name(schema_title: str) -> str:
    """Convert a JSON Schema ``title`` (PascalCase class name) to the TS name."""
    return schema_title


def _json_schema_type_to_ts(
    prop: dict[str, Any],
    defs: dict[str, Any],
    nullable: bool = False,
) -> str:
    """Recursively convert a JSON Schema property to a TypeScript type string."""

    # $ref — reference to a $defs entry
    ref = prop.get("$ref")
    if ref is not None:
        ref_name = ref.rsplit("/", 1)[-1]
        ref_def = defs.get(ref_name, {})
        ts = _ts_name(ref_def.get("title", ref_name))
        # If the referenced def is an enum-like (just a const or literal),
        # the name is still valid; we emit it separately.
        return f"{ts} | null" if nullable else ts

    # const (literal value)
    if "const" in prop:
        val = prop["const"]
        if isinstance(val, str):
            return f'"{val}"'
        return json.dumps(val)

    # enum
    if "enum" in prop:
        members = prop["enum"]
        parts = [f'"{m}"' if isinstance(m, str) else str(m) for m in members]
        ts = " | ".join(parts)
        return f"({ts}) | null" if nullable else ts

    # allOf — usually a single $ref wrapped in allOf by Pydantic
    all_of = prop.get("allOf")
    if all_of:
        types = [_json_schema_type_to_ts(sub, defs) for sub in all_of]
        ts = " & ".join(types) if len(types) > 1 else types[0]
        return f"({ts}) | null" if nullable else ts

    # anyOf / oneOf — discriminated union or optional
    for key in ("anyOf", "oneOf"):
        variants = prop.get(key)
        if variants is None:
            continue

        # Filter out the {"type": "null"} variant that Pydantic adds for Optional
        non_null = [v for v in variants if v.get("type") != "null"]
        has_null = len(non_null) < len(variants)

        if len(non_null) == 1:
            ts = _json_schema_type_to_ts(non_null[0], defs)
            return f"{ts} | null" if (has_null or nullable) else ts

        parts = [_json_schema_type_to_ts(v, defs) for v in non_null]
        ts = " | ".join(parts)
        if has_null or nullable:
            ts = f"({ts}) | null"
        return ts

    # Primitive types
    json_type = prop.get("type")

    if json_type == "string":
        fmt = prop.get("format", "")
        if fmt in ("date-time", "date", "time"):
            ts = "string"  # ISO-8601 strings in JSON
        elif fmt == "uuid":
            ts = "string"
        else:
            ts = "string"
        return f"{ts} | null" if nullable else ts

    if json_type == "integer" or json_type == "number":
        ts = "number"
        return f"{ts} | null" if nullable else ts

    if json_type == "boolean":
        ts = "boolean"
        return f"{ts} | null" if nullable else ts

    if json_type == "null":
        return "null"

    if json_type == "array":
        items = prop.get("items", {})
        item_ts = _json_schema_type_to_ts(items, defs)
        # Wrap compound types in parens for array
        if " | " in item_ts or " & " in item_ts:
            ts = f"({item_ts})[]"
        else:
            ts = f"{item_ts}[]"
        return f"{ts} | null" if nullable else ts

    if json_type == "object":
        # additionalProperties gives us Record<string, V>
        additional = prop.get("additionalProperties")
        if additional:
            val_ts = _json_schema_type_to_ts(additional, defs)
            ts = f"Record<string, {val_ts}>"
            return f"{ts} | null" if nullable else ts
        # If it has properties, it should be emitted as an inline object
        props = prop.get("properties")
        if props:
            ts = _inline_object(props, prop.get("required", []), defs)
            return f"({ts}) | null" if nullable else ts
        # Fallback for generic object
        ts = "Record<string, unknown>"
        return f"{ts} | null" if nullable else ts

    # Fallback
    return "unknown"


def _inline_object(
    properties: dict[str, Any],
    required: list[str],
    defs: dict[str, Any],
) -> str:
    """Render a JSON Schema object with properties as an inline TS object type."""
    parts: list[str] = []
    for name, prop in properties.items():
        optional = name not in required
        ts_type = _json_schema_type_to_ts(prop, defs)
        q = "?" if optional else ""
        parts.append(f"{name}{q}: {ts_type}")
    return "{ " + "; ".join(parts) + " }"


def _emit_interface(
    title: str,
    schema: dict[str, Any],
    defs: dict[str, Any],
) -> None:
    """Emit a TypeScript ``export interface`` for a JSON Schema object."""
    if title in _emitted:
        return
    _emitted.add(title)

    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))

    lines: list[str] = []
    lines.append(f"export interface {title} {{")

    for prop_name, prop_schema in properties.items():
        # Properties with "const" are discriminator fields — always required
        has_const = "const" in prop_schema
        optional = prop_name not in required_fields and not has_const
        ts_type = _json_schema_type_to_ts(prop_schema, defs)
        q = "?" if optional else ""
        desc = prop_schema.get("description")
        if desc:
            lines.append(f"  /** {desc} */")
        lines.append(f"  {prop_name}{q}: {ts_type};")

    lines.append("}")
    _output_lines.append("\n".join(lines))


def _emit_discriminated_union(
    title: str,
    variants: list[dict[str, Any]],
    defs: dict[str, Any],
) -> None:
    """Emit a TypeScript ``export type`` for a discriminated union."""
    if title in _emitted:
        return
    _emitted.add(title)

    member_types: list[str] = []
    for variant in variants:
        ref = variant.get("$ref")
        if ref:
            ref_name = ref.rsplit("/", 1)[-1]
            ref_def = defs.get(ref_name, {})
            ts = _ts_name(ref_def.get("title", ref_name))
            member_types.append(ts)
        else:
            ts = _json_schema_type_to_ts(variant, defs)
            member_types.append(ts)

    union_str = "\n  | ".join(member_types)
    _output_lines.append(f"export type {title} =\n  | {union_str};")


def _emit_enum(title: str, members: list[Any]) -> None:
    """Emit a TypeScript string literal union for an enum."""
    if title in _emitted:
        return
    _emitted.add(title)

    parts = [f'"{m}"' if isinstance(m, str) else str(m) for m in members]
    _output_lines.append(f"export type {title} = {' | '.join(parts)};")


def _process_defs(defs: dict[str, Any]) -> None:
    """Walk all $defs and emit interfaces/types for each."""
    for def_name, def_schema in defs.items():
        title = _ts_name(def_schema.get("title", def_name))

        # Enum
        if "enum" in def_schema:
            _emit_enum(title, def_schema["enum"])
            continue

        # Discriminated union (anyOf / oneOf at top level)
        for key in ("anyOf", "oneOf"):
            if key in def_schema:
                # Check if it looks like a union of refs (discriminated union)
                variants = def_schema[key]
                non_null = [v for v in variants if v.get("type") != "null"]
                if len(non_null) > 1 or any("$ref" in v for v in non_null):
                    _emit_discriminated_union(title, non_null, defs)
                elif len(non_null) == 1:
                    # Single variant optional — just alias
                    ts = _json_schema_type_to_ts(non_null[0], defs)
                    if title not in _emitted:
                        _emitted.add(title)
                        _output_lines.append(f"export type {title} = {ts} | null;")
                break
        else:
            # Object / interface
            if def_schema.get("type") == "object" or "properties" in def_schema:
                _emit_interface(title, def_schema, defs)
            elif "allOf" in def_schema:
                # allOf wrapping a single $ref
                all_of = def_schema["allOf"]
                if len(all_of) == 1 and "$ref" in all_of[0]:
                    ts = _json_schema_type_to_ts(all_of[0], defs)
                    if title not in _emitted:
                        _emitted.add(title)
                        _output_lines.append(f"export type {title} = {ts};")
                else:
                    ts = _json_schema_type_to_ts(def_schema, defs)
                    if title not in _emitted:
                        _emitted.add(title)
                        _output_lines.append(f"export type {title} = {ts};")


def _process_model(model_cls: type[BaseModel]) -> None:
    """Process a single Pydantic model and emit its TypeScript representation."""
    schema = model_cls.model_json_schema()
    title = _ts_name(schema.get("title", model_cls.__name__))
    defs = schema.get("$defs", {})

    # First, emit all referenced definitions
    _process_defs(defs)

    # Then emit the top-level schema
    if "enum" in schema:
        _emit_enum(title, schema["enum"])
    elif any(k in schema for k in ("anyOf", "oneOf")):
        key = "anyOf" if "anyOf" in schema else "oneOf"
        variants = schema[key]
        non_null = [v for v in variants if v.get("type") != "null"]
        _emit_discriminated_union(title, non_null, defs)
    elif schema.get("type") == "object" or "properties" in schema:
        _emit_interface(title, schema, defs)


# ---------------------------------------------------------------------------
# 3. Main
# ---------------------------------------------------------------------------

def generate() -> str:
    """Generate all TypeScript declarations and return as a single string."""
    _emitted.clear()
    _output_lines.clear()

    _output_lines.append("// Auto-generated by agent_hub.typegen.export")
    _output_lines.append("// Do not edit manually.\n")

    # Emit StrEnum types first (they may be referenced by interfaces)
    for enum_name in sorted(_STR_ENUMS):
        members = _STR_ENUMS[enum_name]
        _emit_enum(enum_name, members)

    # Emit all BaseModel types
    for model_cls in _ALL_MODELS:
        try:
            _process_model(model_cls)
        except Exception as exc:
            _output_lines.append(f"// ERROR generating {model_cls.__name__}: {exc}")

    # Emit Annotated discriminated union type aliases
    for union_name in sorted(_ANNOTATED_UNIONS):
        if union_name in _emitted:
            continue
        _emitted.add(union_name)
        member_names = [cls.__name__ for cls in _ANNOTATED_UNIONS[union_name]]
        union_str = "\n  | ".join(member_names)
        _output_lines.append(f"export type {union_name} =\n  | {union_str};")

    return "\n\n".join(_output_lines) + "\n"


if __name__ == "__main__":
    sys.stdout.write(generate())
