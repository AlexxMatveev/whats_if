"""Parser for drawio (C4 model) files — handles drawio C4 plugin format."""

import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class ArchNode:
    id: str
    name: str
    type: str  # systemBoundary, container, external, role
    description: str = ""
    parent_id: Optional[str] = None
    fill: str = ""
    shape: str = ""


@dataclass
class ArchEdge:
    id: str
    source: str
    target: str
    description: str = ""
    technology: str = ""
    dataflow: str = ""


def _clean_id(raw: str) -> str:
    """Clean an ID — remove trailing description appended after last space."""
    return raw.split("─")[0].strip() if "─" in raw else raw


def parse_drawio(filepath: str) -> Dict[str, Any]:
    tree = ET.parse(filepath)
    root = tree.getroot()

    root_cell = root.find("diagram/mxGraphModel/root")
    if root_cell is None:
        raise ValueError("No <root> found")

    children = list(root_cell)
    objects = [c for c in children if c.tag == "object"]

    nodes: List[ArchNode] = []
    edges: List[ArchEdge] = []
    obj_by_id: Dict[str, Any] = {}

    for obj in objects:
        oid = obj.get("id", "")
        obj_by_id[oid] = obj

    # First pass: extract edges (relationships)
    for obj in objects:
        obj_type = obj.get("type", "")
        inner = obj.find("mxCell")
        if inner is None:
            continue

        if obj_type == "relationship":
            source = inner.get("source", "")
            target = inner.get("target", "")
            if not source or not target:
                continue
            desc = obj.get("desc", "")
            tech = obj.get("c4Technology", "")
            dataflow = obj.get("dataflow", "")
            edges.append(ArchEdge(
                id=obj.get("id", ""),
                source=source,
                target=target,
                description=desc,
                technology=tech,
                dataflow=dataflow,
            ))

    # Second pass: extract nodes
    for obj in objects:
        obj_type = obj.get("type", "")
        c4type = obj.get("c4Type", "")
        inner = obj.find("mxCell")
        if inner is None:
            continue

        vertex = inner.get("vertex", "0")
        if vertex != "1":
            continue

        # Skip ports — they're interface labels, not independent components
        if obj_type == "port":
            continue

        # Skip the root product wrapper
        if obj_type == "product":
            continue

        name = obj.get("c4Name", "") or obj.get("label", "") or ""
        desc = obj.get("desc", "")

        style_str = inner.get("style", "")
        style_parts = dict(p.split("=", 1) for p in style_str.split(";") if "=" in p)
        fill = style_parts.get("fillColor", "")
        shape = style_parts.get("shape", "")
        parent = inner.get("parent", "1")
        if parent == "0" or parent == "1":
            parent = ""

        # Map drawio types to our types
        drawio_type = obj_type
        if c4type and not drawio_type:
            drawio_type = c4type

        nodes.append(ArchNode(
            id=obj.get("id", ""),
            name=name,
            type=drawio_type,
            description=desc,
            parent_id=parent,
            fill=fill,
            shape=shape,
        ))

    return {
        "nodes": nodes,
        "edges": edges,
    }
