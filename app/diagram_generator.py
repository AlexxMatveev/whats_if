#!/usr/bin/env python3
"""
Генератор drawio-диаграмм из ARCHOPS YAML-манифестов (C4-model).
"""

import os, sys, re, argparse, glob
from dataclasses import dataclass, field
from typing import Optional
from xml.sax.saxutils import escape

try:
    import yaml
except ImportError:
    print("Установите PyYAML: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# ──────────────────────────────────────────────
# 1. Data Model
# ──────────────────────────────────────────────

@dataclass
class Interface:
    id: str
    name: str = ""
    desc: str = ""
    port: int = 0
    tech: str = ""
    spec: str = ""
    uri: str = ""
    slo: dict = field(default_factory=dict)

@dataclass
class Role:
    id: str
    desc: str = ""
    tech: str = ""
    dataflow: str = ""
    dataobjects: list = field(default_factory=list)

@dataclass
class Dependency:
    id: str
    desc: str = ""
    tech: str = ""
    dataflow: str = ""
    interfaceId: str = ""

@dataclass
class Consumer:
    id: str
    interfaceId: str = ""

@dataclass
class Container:
    id: str
    name: str = ""
    desc: str = ""
    kind: str = ""
    tech: list = field(default_factory=list)
    dataCategories: list = field(default_factory=list)
    repo: str = ""
    systemId: str = ""
    interfaces: list = field(default_factory=list)
    dependencies: list = field(default_factory=list)
    roles: list = field(default_factory=list)
    consumers: list = field(default_factory=list)

@dataclass
class System:
    id: str
    name: str = ""
    desc: str = ""
    productId: str = ""
    dataCategories: list = field(default_factory=list)
    status: str = ""
    pbc: bool = False
    is_external: bool = False
    containers: list = field(default_factory=list)
    interfaces: list = field(default_factory=list)
    roles: list = field(default_factory=list)
    dependencies: list = field(default_factory=list)
    consumers: list = field(default_factory=list)

# ──────────────────────────────────────────────
# 2. Parser
# ──────────────────────────────────────────────

def _norm(d, mapping=None):
    """Normalize YAML dict keys to match dataclass fields"""
    if not d:
        return d
    mapping = mapping or {"SLO": "slo"}
    return {mapping.get(k, k): v for k, v in d.items()}

def _parse_interfaces(raw_list):
    return [Interface(**_norm(i)) for i in raw_list] if raw_list else []

def _parse_roles(raw_list):
    return [Role(**r) for r in raw_list] if raw_list else []

def _parse_deps(raw_list):
    return [Dependency(**d) for d in raw_list] if raw_list else []

def _parse_consumers(raw_list):
    return [Consumer(**c) for c in raw_list] if raw_list else []

def is_system_manifest(filename):
    return "-sys-ARCHOPS" in filename and filename.endswith(".yaml")

def is_container_manifest(filename):
    return "-ARCHOPS" in filename and filename.endswith(".yaml") and not is_system_manifest(filename)

def parse_yaml(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data:
        return None
    return data

def build_model(yaml_dir):
    systems = {}
    containers_map = {}
    all_roles = {}
    all_interfaces = {}

    manifest_files = glob.glob(os.path.join(yaml_dir, "*.yaml"))
    if not manifest_files:
        print(f"Не найдено YAML-файлов в {yaml_dir}", file=sys.stderr)
        sys.exit(1)

    for fp in manifest_files:
        fname = os.path.basename(fp)
        data = parse_yaml(fp)
        if not data:
            continue
        if is_system_manifest(fname):
            sys_id = data.get("id")
            ext = data.get("is_external", False)
            roles = _parse_roles(data.get("roles"))
            interfaces = _parse_interfaces(data.get("interfaces"))
            consumers = _parse_consumers(data.get("consumers"))
            deps = _parse_deps(data.get("dependencies"))
            containers_raw = data.get("containers", [])
            containers = []
            for c in containers_raw:
                containers.append(Container(
                    id=c.get("id"),
                    name=c.get("name", ""),
                ))

            s = System(
                id=sys_id,
                name=data.get("name", ""),
                desc=data.get("desc", ""),
                productId=data.get("productId", ""),
                dataCategories=data.get("dataCategories", []),
                status=data.get("status", ""),
                pbc=data.get("pbc", False),
                is_external=ext,
                containers=containers,
                interfaces=interfaces,
                roles=roles,
                dependencies=deps,
                consumers=consumers,
            )
            systems[sys_id] = s
            for r in roles:
                all_roles[r.id] = r

        elif is_container_manifest(fname):
            cid = data.get("id")
            roles = _parse_roles(data.get("roles"))
            interfaces = _parse_interfaces(data.get("interfaces"))
            deps = _parse_deps(data.get("dependencies"))
            consumers = _parse_consumers(data.get("consumers"))

            c = Container(
                id=cid,
                name=data.get("name", ""),
                desc=data.get("desc", ""),
                kind=data.get("kind", ""),
                tech=data.get("tech", []),
                dataCategories=data.get("dataCategories", []),
                repo=data.get("repo", ""),
                systemId=data.get("systemId", ""),
                interfaces=interfaces,
                dependencies=deps,
                roles=roles,
                consumers=consumers,
            )
            containers_map[cid] = c
            for r in roles:
                all_roles[r.id] = r

    # Merge container details into system container stubs
    for s in systems.values():
        for sc in s.containers:
            cid = sc.id
            if cid in containers_map:
                detailed = containers_map[cid]
                sc.name = detailed.name or sc.name
                sc.desc = detailed.desc or sc.desc
                sc.kind = detailed.kind
                sc.tech = detailed.tech
                sc.dataCategories = detailed.dataCategories or sc.dataCategories
                sc.repo = detailed.repo
                sc.systemId = detailed.systemId or s.id
                sc.interfaces = detailed.interfaces
                sc.dependencies = detailed.dependencies
                sc.roles = detailed.roles
                sc.consumers = detailed.consumers
                # Collect roles from container
                for r in detailed.roles:
                    all_roles[r.id] = r
                del containers_map[cid]
            else:
                sc.systemId = s.id

    # Remaining unmatched containers become standalone
    standalone = list(containers_map.values())

    # Collect all interfaces
    for s in systems.values():
        for iface in s.interfaces:
            all_interfaces[iface.id] = iface
        for c in s.containers:
            for iface in c.interfaces:
                all_interfaces[iface.id] = iface
    for c in standalone:
        for iface in c.interfaces:
            all_interfaces[iface.id] = iface

    return systems, standalone, all_roles, all_interfaces

# ──────────────────────────────────────────────
# 3. Layout
# ──────────────────────────────────────────────

CONTAINER_W = 240
CONTAINER_H = 120
SYS_PAD_LEFT = 80
SYS_PAD_TOP = 80
SYS_PAD_BOTTOM = 80
SYS_MIN_W = 400
SYS_MIN_H = 200
SYS_GAP_X = 100
SYS_GAP_Y = 80

ROLE_W = 200
ROLE_H = 180
ROLE_GAP_X = 220
ROLE_Y = -850

EXT_SYS_W = 240
EXT_SYS_H = 120
EXT_X = -1400
EXT_GAP_Y = 40

def assign_layout(systems, standalone, all_interfaces):
    positions = {}
    bboxes = {}  # element_id → (x, y, w, h)

    col = 0
    start_x = -600
    start_y = -300
    max_h_in_row = 0

    sys_list = sorted(systems.values(), key=lambda s: s.id)
    sys_order = [s for s in sys_list if not s.is_external]

    for c in standalone:
        positions[c.id] = (start_x + 100, 500)
        bboxes[c.id] = (start_x + 100, 500, CONTAINER_W, CONTAINER_H)
        start_x += 100

    start_x = -600
    for s in sys_order:
        n = len(s.containers)
        sys_h = max(SYS_MIN_H, SYS_PAD_TOP + n * CONTAINER_H + (n - 1) * 40 + SYS_PAD_BOTTOM)
        if col > 0:
            start_x += SYS_MIN_W + SYS_GAP_X
        positions[s.id] = (start_x, start_y)
        positions[s.id + "_h"] = sys_h
        bboxes[s.id] = (start_x, start_y, SYS_MIN_W, sys_h)

        for i, c in enumerate(s.containers):
            cx = start_x + SYS_PAD_LEFT
            cy = start_y + SYS_PAD_TOP + i * (CONTAINER_H + 40)
            positions[c.id] = (cx, cy)
            bboxes[c.id] = (cx, cy, CONTAINER_W, CONTAINER_H)
            for j, iface in enumerate(c.interfaces):
                pid = iface.id
                positions[pid] = (0.076 + j * 0.067, iface)

        col += 1
        sys_h_val = positions[s.id + "_h"]
        if sys_h_val > max_h_in_row:
            max_h_in_row = sys_h_val

    # Roles at top
    role_ids = sorted(set(r.id for r in _collect_roles(systems, standalone)))
    for i, rid in enumerate(role_ids):
        rx = -1000 + i * ROLE_GAP_X
        positions[rid] = (rx, ROLE_Y)
        bboxes[rid] = (rx, ROLE_Y, ROLE_W, ROLE_H)

    # External systems
    ext_list = [s for s in systems.values() if s.is_external]
    for i, s in enumerate(ext_list):
        ey = -110 + i * (EXT_SYS_H + EXT_GAP_Y)
        positions[s.id] = (EXT_X, ey)
        bboxes[s.id] = (EXT_X, ey, EXT_SYS_W, EXT_SYS_H)
        for j, iface in enumerate(s.interfaces):
            pid = iface.id
            abs_x, abs_y = EXT_X - 8, ey + 10 + j * 30
            positions[pid] = (pid, abs_x, abs_y)
            bboxes[pid] = (abs_x - 8, abs_y - 8, 16, 16)

    return positions, bboxes

def _collect_roles(systems, standalone):
    roles = []
    seen = set()
    for s in systems.values():
        for r in s.roles:
            if r.id not in seen:
                roles.append(r)
                seen.add(r.id)
        for c in s.containers:
            for r in c.roles:
                if r.id not in seen:
                    roles.append(r)
                    seen.add(r.id)
    for c in standalone:
        for r in c.roles:
            if r.id not in seen:
                roles.append(r)
                seen.add(r.id)
    return roles

# ──────────────────────────────────────────────
# 4. Drawio Generator
# ──────────────────────────────────────────────

PORT_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' "
    "viewBox='0 0 16 16'%3E%3Crect x='1' y='3' width='14' height='10' rx='2' "
    "fill='%230E7DAD' stroke='%23FFFFFF' stroke-width='1.5'/%3E"
    "%3Ccircle cx='8' cy='8' r='3' fill='%23FFFFFF'/%3E%3C/svg%3E"
)

_J = '{"editable": false}'
def _make_meta(*keys):
    pairs = ','.join(f'"{k}":' + _J for k in keys)
    val = f'{{{pairs}}}'
    # Escape double quotes for XML attribute safety
    val = val.replace('"', '&quot;')
    return f'metaData={val};'

SYS_BOUNDARY_META = _make_meta('c4Name', 'c4Type', 'c4Application', 'label', 'type', 'custom_id')
CONTAINER_META = _make_meta('c4Name', 'c4Type', 'c4Description', 'c4Technology', 'label', 'type', 'kind', 'custom_id', 'repo', 'datacategories', 'ports', 'consumer')
EXTERNAL_META = _make_meta('c4Name', 'c4Type', 'c4Description', 'label', 'type', 'is_external', 'consumer', 'custom_id')
ROLE_META = _make_meta('c4Type', 'c4Name', 'c4Description', 'custom_id', 'type', 'not_target')
EDGE_META = _make_meta('c4Name', 'c4Type', 'desc', 'c4Technology', 'tech', 'type')

def esc(text):
    return escape(str(text or ""))

def esc_attr(text):
    return escape(str(text or ""), {'"': '&quot;'})

def xmlesc(text):
    s = str(text or "")
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    s = s.replace("\n", "&#xa;")
    return s

def _tech_str(tech_list):
    if not tech_list:
        return ""
    parts = []
    for t in tech_list:
        name = t.get("name", "")
        ver = t.get("version", "")
        if ver:
            parts.append(f"{name} {ver}")
        else:
            parts.append(name)
    return ", ".join(parts)

def _short_id(full_id):
    parts = full_id.split(".")
    return parts[-1] if len(parts) > 1 else full_id

def _make_id(*parts):
    return "_".join(str(p) for p in parts if p)

def _container_desc(container):
    return container.desc.replace("\n", "&#xa;") if container.desc else ""

def _container_tech_label(tech_list, container_kind=""):
    t = _tech_str(tech_list)
    if not t:
        return ""
    return f": {t}"

def generate_drawio(systems, standalone, all_roles, all_interfaces, positions, bboxes):
    lines = []
    lines.append('''<mxfile host="app.diagrams.net" agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" version="22.1.18">
  <diagram name="System Container view" id="System Container view">
    <mxGraphModel dx="3223" dy="2229" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="827" pageHeight="1169" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />''')

    used_ids = set()
    edge_keys = set()

    # Build set of all known element IDs for edge target validation
    known_ids = set()
    for s in systems.values():
        known_ids.add(s.id)
        for c in s.containers:
            known_ids.add(c.id)
            for iface in c.interfaces:
                known_ids.add(iface.id)
        for iface in s.interfaces:
            known_ids.add(iface.id)
        for r in s.roles:
            known_ids.add(r.id)
    for c in standalone:
        known_ids.add(c.id)
        for iface in c.interfaces:
            known_ids.add(iface.id)
        for r in c.roles:
            known_ids.add(r.id)
    role_data = {}
    for s in systems.values():
        for r in s.roles:
            role_data[r.id] = r
        for c in s.containers:
            for r in c.roles:
                role_data[r.id] = r
    for c in standalone:
        for r in c.roles:
            role_data[r.id] = r

    def safe_id(base_id):
        """Ensure unique IDs"""
        if base_id not in used_ids:
            used_ids.add(base_id)
            return base_id
        i = 2
        while f"{base_id}_{i}" in used_ids:
            i += 1
        result = f"{base_id}_{i}"
        used_ids.add(result)
        return result

    # ── External Systems ──
    for s in systems.values():
        if not s.is_external:
            continue
        pos = positions.get(s.id, (0, 0))
        x, y = pos
        sys_id = s.id
        safe_sys_id = safe_id(sys_id)
        label = (f'<font style="font-size: 16px"><b>{xmlesc(s.name)}</b></font>'
                 f'<div>[externalMTSSystem]</div><br>'
                 f'<div><font style="font-size: 11px"><font color="#cccccc">{xmlesc(s.desc)}</font></font></div>')
        lines.append(f'''        <object placeholders="1" c4Name="{xmlesc(s.name)}" c4Type="externalMTSSystem" c4Description="{xmlesc(s.desc)}" label="{xmlesc(label)}" type="external" is_external="1" consumer="1" custom_id="{xmlesc(sys_id)}" id="{safe_sys_id}">
          <mxCell style="rounded=1;whiteSpace=wrap;html=1;labelBackgroundColor=none;fillColor=#e51400;fontColor=#ffffff;align=center;arcSize=10;strokeColor=#736782;metaEdit=1;resizable=1;points=[[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0.25,0],[1,0.5,0],[1,0.75,0],[0.75,1,0],[0.5,1,0],[0.25,1,0],[0,0.75,0],[0,0.5,0],[0,0.25,0]];resizeHeight=1;dropTarget=0;{EXTERNAL_META}fetchDataType=&quot;system&quot;;" parent="1" vertex="1">
            <mxGeometry x="{x}" y="{y}" width="{EXT_SYS_W}" height="{EXT_SYS_H}" as="geometry" />
          </mxCell>
        </object>''')
        # Ports on external system (at root level with absolute coords)
        for iface in s.interfaces:
            pid = iface.id
            safe_pid = safe_id(pid)
            ppos = positions.get(pid, (0, 0))
            if isinstance(ppos, tuple) and len(ppos) == 3:
                _, abs_x, abs_y = ppos
            else:
                abs_x, abs_y = x + EXT_SYS_W - 30, y + 10
            pdesc = xmlesc(iface.desc)
            pname = xmlesc(iface.name)
            ptech = xmlesc(iface.tech)
            pspec = xmlesc(iface.spec)
            puri = xmlesc(iface.uri)
            lines.append(f'''        <object placeholders="1" label="" type="port" custom_id="{xmlesc(iface.id.split('.')[-1])}" c4Name="{pname}" port="{iface.port}" desc="{pdesc}" tech="{ptech}" serviceid="" dataobjects="" spec="{pspec}" slo="latency=0" uri="{puri}" id="{xmlesc(pid)}">
          <mxCell style="port;image={PORT_SVG};" parent="1" vertex="1">
            <mxGeometry x="{abs_x}" y="{abs_y}" width="16" height="16" as="geometry">
              <mxPoint x="-8" y="-8" as="offset" />
            </mxGeometry>
          </mxCell>
        </object>''')

    # ── Roles ──
    role_list = sorted(set(r.id for r in _collect_roles(systems, standalone)))

    for rid in role_list:
        r = role_data.get(rid)
        if not r:
            continue
        pos = positions.get(rid, (0, 0))
        rx, ry = pos
        safe_rid = safe_id(rid)
        label = (f'<font style=" font-size: 16px"><b>{xmlesc(rid)}</b></font>'
                 f'<div>[Role]</div><br>'
                 f'<div><font style="font-size: 11px"><font color="#cccccc">{xmlesc(r.desc)}</font></font></div>')
        lines.append(f'''        <object placeholders="1" c4Type="Role" c4Name="{xmlesc(rid)}" c4Description="{xmlesc(r.desc)}" custom_id="{xmlesc(rid)}" label="{xmlesc(label)}" type="role" not_target="1" id="{safe_rid}">
          <mxCell style="html=1;fontSize=11;dashed=0;whiteSpace=wrap;fillColor=#083F75;strokeColor=#ffffff;fontColor=#ffffff;shape=mxgraph.c4.person2;align=center;metaEdit=1;points=[[0.5,0,0],[1,0.5,0],[1,0.75,0],[0.75,1,0],[0.5,1,0],[0.25,1,0],[0,0.75,0],[0,0.5,0]];resizable=0;dropTarget=0;{ROLE_META}movable=1;rotatable=1;deletable=1;editable=1;locked=0;connectable=1;" parent="1" vertex="1">
            <mxGeometry x="{rx}" y="{ry}" width="{ROLE_W}" height="{ROLE_H}" as="geometry" />
          </mxCell>
        </object>''')

    # ── System Boundaries ──
    for s in systems.values():
        if s.is_external:
            continue
        pos = positions.get(s.id)
        if not pos:
            continue
        sx, sy = pos
        sys_h = positions.get(s.id + "_h", SYS_MIN_H)
        safe_sys_id = safe_id(s.id)
        label = (f'<font style="font-size: 16px"><b><div style="text-align: left">{xmlesc(s.name)}</div></b></font>'
                 f'<div style="text-align: left">[Software System]</div>'
                 f'<div style="text-align: left">{xmlesc(s.desc)}</div>')
        lines.append(f'''        <object placeholders="1" c4Name="{xmlesc(s.name)}" c4Type="Software System" c4Application="Software System" label="{xmlesc(label)}" type="systemBoundary" custom_id="{xmlesc(s.id)}" c4Description="{xmlesc(s.desc)}" id="{safe_sys_id}">
          <mxCell style="rounded=1;fontSize=11;whiteSpace=wrap;html=1;dashed=1;arcSize=20;fillColor=none;strokeColor=#00A9E3;strokeWidth=2;fontColor=#0078A1;labelBackgroundColor=none;align=left;verticalAlign=bottom;labelBorderColor=none;spacingTop=0;spacing=10;dashPattern=8 4;metaEdit=1;rotatable=0;perimeter=rectanglePerimeter;noLabel=0;labelPadding=0;allowArrows=0;connectable=1;expand=0;recursiveResize=0;editable=1;pointerEvents=0;absoluteArcSize=1;points=[[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0.25,0],[1,0.5,0],[1,0.75,0],[0.75,1,0],[0.5,1,0],[0.25,1,0],[0,0.75,0],[0,0.5,0],[0,0.25,0]];container=1;{SYS_BOUNDARY_META}" parent="1" vertex="1">
            <mxGeometry x="{sx}" y="{sy}" width="{SYS_MIN_W}" height="{sys_h}" as="geometry" />
          </mxCell>
        </object>''')

        # Containers inside system
        for i, c in enumerate(s.containers):
            cpos = positions.get(c.id)
            if not cpos:
                continue
            cx, cy = cpos
            safe_cid = safe_id(c.id)
            tech_name = _container_tech_label(c.tech)
            c4tech = _tech_str(c.tech)
            cdesc = _container_desc(c)
            kind = c.kind or "service"
            custom_id = _short_id(c.id)

            label = (f'<font style="font-size: 16px"><b>{xmlesc(c.name)}</b></font>'
                     f'<div>[container{tech_name}]</div><br>'
                     f'<div><font style="font-size: 11px"><font color="#E6E6E6">{cdesc}</font></font></div>')

            lines.append(f'''        <object placeholders="1" c4Name="{xmlesc(c.name)}" c4Type="container" c4Description="{cdesc}" c4Technology="{xmlesc(c4tech)}" label="{xmlesc(label)}" type="container" kind="{kind}" custom_id="{xmlesc(custom_id)}" repo="{xmlesc(c.repo)}" datacategories="{xmlesc(','.join(c.dataCategories))}" ports="1" consumer="1" id="{safe_cid}">
          <mxCell style="rounded=1;whiteSpace=wrap;html=1;fontSize=11;labelBackgroundColor=none;fillColor=#23A2D9;fontColor=#ffffff;align=center;arcSize=10;strokeColor=#0E7DAD;metaEdit=1;resizable=0;points=[[0.5,0,0],[1,0.5,0],[1,0.75,0],[0.75,1,0],[0.5,1,0],[0.25,1,0],[0,0.75,0],[0,0.5,0]];resizable=0;dropTarget=0;{CONTAINER_META}" parent="{safe_sys_id}" vertex="1">
            <mxGeometry x="80" y="{80 + i * (CONTAINER_H + 40)}" width="{CONTAINER_W}" height="{CONTAINER_H}" as="geometry" />
          </mxCell>
        </object>''')

            # Ports on container
            port_x = 0.076
            port_step = 0.067
            for j, iface in enumerate(c.interfaces):
                pid = iface.id
                safe_pid = safe_id(pid)
                lines.append(_gen_port(pid, iface, safe_cid, positions, port_x + j * port_step))
                port_x += port_step

            # System-level interfaces not already on container
            c_interface_ids = {i.id for i in c.interfaces}
            for iface in s.interfaces:
                if iface.id.startswith(c.id + ".") and iface.id not in c_interface_ids:
                    pid = iface.id
                    safe_pid = safe_id(pid)
                    lines.append(_gen_port(pid, iface, safe_cid, positions, port_x))
                    port_x += port_step

    # ── Standalone Containers ──
    for c in standalone:
        cpos = positions.get(c.id)
        if not cpos:
            continue
        cx, cy = cpos
        safe_cid = safe_id(c.id)
        tech_name = _container_tech_label(c.tech)
        c4tech = _tech_str(c.tech)
        cdesc = _container_desc(c)
        kind = c.kind or "service"
        custom_id = _short_id(c.id)
        label = (f'<font style="font-size: 16px"><b>{xmlesc(c.name)}</b></font>'
                 f'<div>[container{tech_name}]</div><br>'
                 f'<div><font style="font-size: 11px"><font color="#E6E6E6">{cdesc}</font></font></div>')
        lines.append(f'''        <object placeholders="1" c4Name="{xmlesc(c.name)}" c4Type="container" c4Description="{cdesc}" c4Technology="{xmlesc(c4tech)}" label="{xmlesc(label)}" type="container" kind="{kind}" custom_id="{xmlesc(custom_id)}" repo="{xmlesc(c.repo)}" datacategories="{xmlesc(','.join(c.dataCategories))}" ports="1" consumer="1" id="{safe_cid}">
          <mxCell style="rounded=1;whiteSpace=wrap;html=1;fontSize=11;labelBackgroundColor=none;fillColor=#23A2D9;fontColor=#ffffff;align=center;arcSize=10;strokeColor=#0E7DAD;metaEdit=1;resizable=0;points=[[0.5,0,0],[1,0.5,0],[1,0.75,0],[0.75,1,0],[0.5,1,0],[0.25,1,0],[0,0.75,0],[0,0.5,0]];resizable=0;dropTarget=0;{CONTAINER_META}" parent="1" vertex="1">
            <mxGeometry x="{cx}" y="{cy}" width="{CONTAINER_W}" height="{CONTAINER_H}" as="geometry" />
          </mxCell>
        </object>''')
        port_x = 0.076
        port_step = 0.067
        for j, iface in enumerate(c.interfaces):
            pid = iface.id
            safe_pid = safe_id(pid)
            lines.append(_gen_port(pid, iface, safe_cid, positions, port_x + j * port_step))
            port_x += port_step

    # ── Relationships (edges) ──
    # From container dependencies
    for s in systems.values():
        if s.is_external:
            continue
        for c in s.containers:
            for dep in c.dependencies:
                target_id = dep.interfaceId or dep.id
                src = c.id
                tgt = target_id
                edge_key = (src, tgt)
                if edge_key in edge_keys:
                    continue
                edge_keys.add(edge_key)
                rel_id = f"{src}_{tgt}{dep.desc}"[:120]
                safe_rel_id = safe_id(rel_id)
                if src in known_ids and tgt in known_ids:
                    lines.append(_gen_relationship(src, tgt, dep.desc, dep.tech, dep.dataflow, safe_rel_id, bboxes))

    for c in standalone:
        for dep in c.dependencies:
            target_id = dep.interfaceId or dep.id
            src = c.id
            tgt = target_id
            edge_key = (src, tgt)
            if edge_key in edge_keys:
                continue
            edge_keys.add(edge_key)
            rel_id = f"{src}_{tgt}{dep.desc}"[:120]
            safe_rel_id = safe_id(rel_id)
            if src in known_ids and tgt in known_ids:
                lines.append(_gen_relationship(src, tgt, dep.desc, dep.tech, dep.dataflow, safe_rel_id, bboxes))

    # From system consumers → edges from consumer to interface
    for s in systems.values():
        if s.is_external:
            continue
        for consumer in s.consumers:
            tgt = consumer.interfaceId
            src = consumer.id
            edge_key = (src, tgt)
            if edge_key in edge_keys:
                continue
            edge_keys.add(edge_key)
            rel_id = f"{src}_{tgt}_consumer"[:120]
            safe_rel_id = safe_id(rel_id)
            dep_obj = _find_dep_for(s, consumer.id, consumer.interfaceId)
            desc = dep_obj.desc if dep_obj else ""
            tech = dep_obj.tech if dep_obj else ""
            dataflow = dep_obj.dataflow if dep_obj else ""
            if src in known_ids and tgt in known_ids:
                lines.append(_gen_relationship(src, tgt, desc, tech, dataflow, safe_rel_id))

    # From container consumers
    for s in systems.values():
        for c in s.containers:
            for consumer in c.consumers:
                tgt = consumer.interfaceId
                src = consumer.id
                edge_key = (src, tgt)
                if edge_key in edge_keys:
                    continue
                edge_keys.add(edge_key)
                rel_id = f"{src}_{tgt}_consumer"[:120]
                safe_rel_id = safe_id(rel_id)
                dep_obj = _find_dep_for_container(c, consumer.id, consumer.interfaceId)
                desc = dep_obj.desc if dep_obj else ""
                tech = dep_obj.tech if dep_obj else ""
                dataflow = dep_obj.dataflow if dep_obj else ""
                if src in known_ids and tgt in known_ids:
                    lines.append(_gen_relationship(src, tgt, desc, tech, dataflow, safe_rel_id))

    for c in standalone:
        for consumer in c.consumers:
            tgt = consumer.interfaceId
            src = consumer.id
            edge_key = (src, tgt)
            if edge_key in edge_keys:
                continue
            edge_keys.add(edge_key)
            rel_id = f"{src}_{tgt}_consumer"[:120]
            safe_rel_id = safe_id(rel_id)
            dep_obj = _find_dep_for_container(c, consumer.id, consumer.interfaceId)
            desc = dep_obj.desc if dep_obj else ""
            tech = dep_obj.tech if dep_obj else ""
            dataflow = dep_obj.dataflow if dep_obj else ""
            if src in known_ids and tgt in known_ids:
                lines.append(_gen_relationship(src, tgt, desc, tech, dataflow, safe_rel_id))

    # Role → system/container relationships (deduplicated: prefer container over system)
    role_targets = {}  # role_id → best_target_id
    for s in systems.values():
        if s.is_external:
            continue
        for r in s.roles:
            role_targets[r.id] = s.id
        for c in s.containers:
            for r in c.roles:
                role_targets[r.id] = c.id
    for c in standalone:
        for r in c.roles:
            role_targets[r.id] = c.id
    for rid, target_id in role_targets.items():
        r = role_data.get(rid)
        if not r:
            continue
        src = rid
        edge_key = (src, target_id)
        if edge_key in edge_keys:
            continue
        edge_keys.add(edge_key)
        rel_id = f"{src}_{target_id}{r.desc}"[:120]
        safe_rel_id = safe_id(rel_id)
        if src in known_ids and target_id in known_ids:
            lines.append(_gen_relationship(src, target_id, r.desc, r.tech, r.dataflow, safe_rel_id, bboxes))

    lines.append('''      </root>
    </mxGraphModel>
  </diagram>
</mxfile>''')
    return "\n".join(lines)

def _find_dep_for(system, consumer_id, interface_id):
    for c in system.containers:
        for dep in c.dependencies:
            if dep.interfaceId == interface_id:
                return dep
    for dep in system.dependencies:
        if dep.interfaceId == interface_id:
            return dep
    return None

def _find_dep_for_container(container, consumer_id, interface_id):
    for dep in container.dependencies:
        if dep.interfaceId == interface_id:
            return dep
    return None

def _gen_port(pid, iface, parent_id, positions, fixed_px=None):
    if fixed_px is not None:
        px = fixed_px
    else:
        px = positions.get(pid, (0.076,))[0] if isinstance(positions.get(pid, (0.076,)), tuple) else 0.076
        if isinstance(px, float):
            pass
        else:
            px = 0.076
    pdesc = xmlesc(iface.desc)
    pname = xmlesc(iface.name)
    ptech = xmlesc(iface.tech)
    pspec = xmlesc(iface.spec)
    puri = xmlesc(iface.uri)
    plabel = xmlesc(iface.name)
    return f'''        <object placeholders="1" label="" type="port" custom_id="{xmlesc(iface.id.split('.')[-1])}" c4Name="{pname}" port="{iface.port}" desc="{pdesc}" tech="{ptech}" serviceid="" dataobjects="" spec="{pspec}" slo="latency=0" uri="{puri}" id="{xmlesc(pid)}">
          <mxCell style="port;image={PORT_SVG};" parent="{parent_id}" vertex="1">
            <mxGeometry x="{px}" width="16" height="16" relative="1" as="geometry">
              <mxPoint x="-8" y="-8" as="offset" />
            </mxGeometry>
          </mxCell>
        </object>'''

def _route_edge(src_id, tgt_id, bboxes):
    """Compute orthogonal waypoints to avoid element overlap."""
    def _find_bbox(eid):
        if eid in bboxes:
            return bboxes[eid]
        # Try parent container (ID before last dot)
        parts = eid.rsplit('.', 1)
        if len(parts) > 1 and parts[0] in bboxes:
            return bboxes[parts[0]]
        return None

    src_box = _find_bbox(src_id)
    tgt_box = _find_bbox(tgt_id)
    if src_box is None or tgt_box is None:
        return []
    sx, sy, sw, sh = src_box
    tx, ty, tw, th = tgt_box
    scx, scy = sx + sw / 2, sy + sh / 2
    tcx, tcy = tx + tw / 2, ty + th / 2
    dx, dy = tcx - scx, tcy - scy
    # Add simple offset to spread multi-edges
    off = hash(src_id + tgt_id) % 60 - 30
    if abs(dx) > abs(dy):
        mx = (scx + tcx) / 2 + off
        return [(mx, scy), (mx, tcy)]
    else:
        my = (scy + tcy) / 2 + off
        return [(scx, my), (tcx, my)]

def _gen_relationship(source, target, desc, tech, dataflow, rel_id, bboxes=None):
    label = (f'<div style="text-align: left">'
             f'<div style="text-align: center"><b>{xmlesc(desc)}</b></div>'
             f'<div style="text-align: center">[{xmlesc(tech)}]</div>'
             f'</div>')
    pts = _route_edge(source, target, bboxes or {})
    pts_xml = ""
    if pts:
        pts_str = "\n".join(f'                <mxPoint x="{round(p[0])}" y="{round(p[1])}" />' for p in pts)
        pts_xml = f'''
              <Array as="points">
{pts_str}
              </Array>'''
    return f'''        <object placeholders="1" c4Name="Relationship" c4Type="Relationship" desc="{xmlesc(desc)}" c4Technology="{xmlesc(tech)}" tech="{xmlesc(tech)}" label="{xmlesc(label)}" type="relationship" dataflow="{xmlesc(dataflow)}" id="{xmlesc(rel_id)}">
          <mxCell style="endArrow=blockThin;html=1;fontSize=10;fontColor=#404040;strokeWidth=1;endFill=1;strokeColor=#545454;elbow=vertical;metaEdit=1;endSize=14;startSize=14;jumpStyle=arc;jumpSize=16;rounded=0;edgeStyle=orthogonalEdgeStyle;{EDGE_META}" parent="1" source="{xmlesc(source)}" target="{xmlesc(target)}" edge="1">
            <mxGeometry x="0.5" width="240" relative="1" as="geometry">{pts_xml}
            </mxGeometry>
          </mxCell>
        </object>'''

# ──────────────────────────────────────────────
# 5. Product View Generator
# ──────────────────────────────────────────────

PROD_CONTAINER_W = 240
PROD_CONTAINER_H = 120
PROD_SYS_PAD = 50
PROD_SYS_MIN_W = 340
PROD_SYS_MIN_H = 200
PROD_SYS_GAP_X = 40
PROD_SYS_GAP_Y = 40
PROD_CONTAINER_GAP = 30
PROD_START_X = 50
PROD_START_Y = 50
PROD_EXT_X = 200
PROD_EXT_Y = 0
PROD_ROLE_X = 0
PROD_ROLE_Y = 200

def _prod_layout(systems, standalone, all_interfaces):
    """Layout for product view: systems in grid, external on right"""
    pos = {}
    bboxes = {}

    sys_list = [s for s in systems.values() if not s.is_external]
    ext_list = [s for s in systems.values() if s.is_external]

    # Grid layout for internal systems
    cols = 3
    max_sys_w = 0
    max_sys_h = 0
    sys_positions = []
    for i, s in enumerate(sys_list):
        n = len(s.containers)
        sys_h = max(PROD_SYS_MIN_H, PROD_SYS_PAD + n * PROD_CONTAINER_H + (n - 1) * PROD_CONTAINER_GAP + PROD_SYS_PAD)
        sys_w = PROD_SYS_MIN_W
        col = i % cols
        row = i // cols
        sx = PROD_START_X + col * (sys_w + PROD_SYS_GAP_X)
        sy = PROD_START_Y + row * (sys_h + PROD_SYS_GAP_Y)
        sys_positions.append((s, sx, sy, sys_w, sys_h))
        if sys_w > max_sys_w: max_sys_w = sys_w
        if sys_h > max_sys_h: max_sys_h = sys_h

    for s, sx, sy, sw, sh in sys_positions:
        pos[s.id] = (sx, sy)
        pos[s.id + "_h"] = sh
        bboxes[s.id] = (sx, sy, sw, sh)
        for i, c in enumerate(s.containers):
            cx = sx + PROD_SYS_PAD
            cy = sy + PROD_SYS_PAD + i * (PROD_CONTAINER_H + PROD_CONTAINER_GAP)
            pos[c.id] = (cx, cy)
            bboxes[c.id] = (cx, cy, PROD_CONTAINER_W, PROD_CONTAINER_H)
            for j, iface in enumerate(c.interfaces):
                pos[iface.id] = (0.076 + j * 0.067, iface)

    # External systems on right
    if ext_list:
        ext_start_x = PROD_START_X + (max_sys_w + PROD_SYS_GAP_X) * min(cols, len(sys_list)) + 80
        for i, s in enumerate(ext_list):
            ey = PROD_START_Y + i * 160
            pos[s.id] = (ext_start_x, ey)
            bboxes[s.id] = (ext_start_x, ey, 240, 120)
            for j, iface in enumerate(s.interfaces):
                pid = iface.id
                abs_x, abs_y = ext_start_x - 8, ey + 10 + j * 30
                pos[pid] = (pid, abs_x, abs_y)
                bboxes[pid] = (abs_x - 8, abs_y - 8, 16, 16)

    # Standalone containers
    for i, c in enumerate(standalone):
        cx = PROD_START_X + 200 + i * 280
        cy = PROD_START_Y + 500
        pos[c.id] = (cx, cy)
        bboxes[c.id] = (cx, cy, PROD_CONTAINER_W, PROD_CONTAINER_H)

    # Roles (people) - place below product
    role_ids = sorted(set(r.id for r in _collect_roles(systems, standalone)))
    role_gap = 220
    for i, rid in enumerate(role_ids):
        rx = PROD_START_X + i * role_gap
        ry = PROD_ROLE_Y
        pos[rid] = (rx, ry)
        bboxes[rid] = (rx, ry, 200, 160)

    return pos, bboxes

def generate_product_view(systems, standalone, all_roles, all_interfaces, positions, bboxes):
    lines = []

    sys_list = sorted([s for s in systems.values() if not s.is_external], key=lambda s: s.id)
    ext_list = sorted([s for s in systems.values() if s.is_external], key=lambda s: s.id)

    # Compute product boundary dimensions
    min_x = float('inf')
    min_y = float('inf')
    max_x = float('-inf')
    max_y = float('-inf')
    for s in sys_list:
        p = positions.get(s.id)
        if not p: continue
        sh = positions.get(s.id + "_h", PROD_SYS_MIN_H)
        sx, sy = p
        min_x = min(min_x, sx - 20)
        min_y = min(min_y, sy - 20)
        max_x = max(max_x, sx + PROD_SYS_MIN_W + 20)
        max_y = max(max_y, sy + sh + 20)
    # Include standalone
    for c in standalone:
        p = positions.get(c.id)
        if p:
            cx, cy = p
            min_x = min(min_x, cx - 20)
            min_y = min(min_y, cy - 20)
            max_x = max(max_x, cx + PROD_CONTAINER_W + 20)
            max_y = max(max_y, cy + PROD_CONTAINER_H + 20)
    # Include roles
    role_ids = sorted(set(r.id for r in _collect_roles(systems, standalone)))
    for rid in role_ids:
        p = positions.get(rid)
        if p:
            rx, ry = p
            min_x = min(min_x, rx - 20)
            min_y = min(min_y, ry - 20)
            max_x = max(max_x, rx + 200 + 20)
            max_y = max(max_y, ry + 160 + 20)
    # Include external
    for s in ext_list:
        p = positions.get(s.id)
        if p:
            ex, ey = p
            min_x = min(min_x, ex - 20)
            min_y = min(min_y, ey - 20)
            max_x = max(max_x, ex + 240 + 20)
            max_y = max(max_y, ey + 120 + 20)

    if min_x == float('inf'):
        min_x, min_y, max_x, max_y = 0, 0, 800, 600

    prod_w = max_x - min_x + 40
    prod_h = max_y - min_y + 40

    # Offset all positions so product starts at 0,0
    offset_x = min_x - 20
    offset_y = min_y - 20
    offset_pos = {}
    offset_bboxes = {}
    for k, v in positions.items():
        if isinstance(v, tuple) and len(v) == 2 and all(isinstance(c, (int, float)) for c in v):
            offset_pos[k] = (v[0] - offset_x, v[1] - offset_y)
        elif isinstance(v, tuple) and len(v) == 3 and isinstance(v[0], str):
            offset_pos[k] = (v[0], v[1] - offset_x, v[2] - offset_y)
        else:
            offset_pos[k] = v
    for k, v in bboxes.items():
        bx, by, bw, bh = v
        offset_bboxes[k] = (bx - offset_x, by - offset_y, bw, bh)

    used_ids = set()
    edge_keys = set()

    known_ids = set()
    for s in systems.values():
        known_ids.add(s.id)
        for c in s.containers:
            known_ids.add(c.id)
            for iface in c.interfaces:
                known_ids.add(iface.id)
        for iface in s.interfaces:
            known_ids.add(iface.id)
        for r in s.roles:
            known_ids.add(r.id)
    for c in standalone:
        known_ids.add(c.id)
        for iface in c.interfaces:
            known_ids.add(iface.id)
        for r in c.roles:
            known_ids.add(r.id)
    role_data = {}
    for s in systems.values():
        for r in s.roles:
            role_data[r.id] = r
        for c in s.containers:
            for r in c.roles:
                role_data[r.id] = r
    for c in standalone:
        for r in c.roles:
            role_data[r.id] = r

    def safe_id(base_id):
        if base_id not in used_ids:
            used_ids.add(base_id)
            return base_id
        i = 2
        while f"{base_id}_{i}" in used_ids:
            i += 1
        result = f"{base_id}_{i}"
        used_ids.add(result)
        return result

    PROD_META = 'metaData={"type":{"editable": false},"c4Type":{"editable": false}};'
    SYS_META_PROD = 'metaData={"type":{"editable": false},"c4Description":{"editable": false},"c4Type":{"editable": false},"kind":{"editable": false},"c4Name":{"editable": true},"ports":{"editable": false},"c4Application":{"editable": false}};'
    CONT_META_PROD = 'metaData={"type":{"editable": false},"c4Description":{"editable": false},"c4Type":{"editable": false},"kind":{"editable": false},"ports":{"editable": false},"consumer":{"editable": false}};'
    EXT_META_PROD = 'metaData={"type":{"editable": false},"c4Description":{"editable": true},"c4Type":{"editable": false},"consumer":{"editable": false},"custom_id":{"editable": false},"is_external":{"editable": false},"c4Name":{"editable": false}};fetchDataType="system";'
    EDGE_META_PROD = 'metaData={"type":{"editable": false},"c4Name":{"editable": false},"c4Type":{"editable": false},"c4Description":{"editable": false},"desc":{"editable": false},"c4Technology":{"editable": false},"dataflow":{"editable": false},"dataobjects":{"editable": false}};'

    # ── Product Boundary ──
    product_name = "Product"
    if sys_list:
        product_name = sys_list[0].productId or "Product"
    # Try to find a common product name
    for s in sys_list:
        if s.productId:
            product_name = s.productId
            break

    safe_prod_id = safe_id("product_boundary")
    prod_label = f'<font style="font-size: 16px"><b><div style="text-align: left">{xmlesc(product_name)}</div></b></font><div style="text-align: left">[product]</div>'
    lines.append(f'''        <object placeholders="1" c4Name="{xmlesc(product_name)}" c4Type="product" label="{xmlesc(prod_label)}" type="product" custom_id="{xmlesc(product_name)}" id="{safe_prod_id}">
          <mxCell parent="1" style="rounded=1;fontSize=11;whiteSpace=wrap;html=1;dashed=1;arcSize=20;fillColor=none;strokeColor=#666666;fontColor=#333333;labelBackgroundColor=none;align=left;verticalAlign=bottom;labelBorderColor=none;spacingTop=0;spacing=10;dashPattern=8 4;metaEdit=1;rotatable=0;perimeter=rectanglePerimeter;noLabel=0;labelPadding=0;allowArrows=0;connectable=0;expand=0;recursiveResize=0;editable=1;pointerEvents=0;absoluteArcSize=1;points=[[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0.25,0],[1,0.5,0],[1,0.75,0],[0.75,1,0],[0.5,1,0],[0.25,1,0],[0,0.75,0],[0,0.5,0],[0,0.25,0]];container=1;deletable=0;resizable=1;{PROD_META}" vertex="1">
            <mxGeometry height="{prod_h}" width="{prod_w}" x="0" y="0" as="geometry" />
          </mxCell>
        </object>''')

    # ── System Boundaries ──
    for s in sys_list:
        pos = offset_pos.get(s.id)
        if not pos:
            continue
        sx, sy = pos
        sh = offset_pos.get(s.id + "_h", PROD_SYS_MIN_H)
        safe_sys_id = safe_id(s.id)
        label = f'<font style="font-size: 16px"><b><div style="text-align: left">{xmlesc(s.name)}</div></b></font><div style="text-align: left">[{xmlesc(s.desc.split(chr(10))[0] if s.desc else "Software System")}]</div>'
        lines.append(f'''        <object placeholders="1" c4Name="{xmlesc(s.name)}" c4Type="Software system" c4Application="Software System" label="{xmlesc(label)}" type="systemBoundary" custom_id="{xmlesc(s.id.split('.')[-1])}" c4Description="{xmlesc(s.desc)}" id="{safe_sys_id}">
          <mxCell parent="{safe_prod_id}" style="rounded=1;fontSize=11;whiteSpace=wrap;html=1;dashed=1;arcSize=20;fillColor=none;strokeColor=#666666;fontColor=#333333;labelBackgroundColor=none;align=left;verticalAlign=bottom;labelBorderColor=none;spacingTop=0;spacing=10;dashPattern=8 4;metaEdit=1;rotatable=0;perimeter=rectanglePerimeter;noLabel=0;labelPadding=0;allowArrows=0;connectable=1;expand=0;recursiveResize=0;editable=1;pointerEvents=0;absoluteArcSize=1;points=[[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0.25,0],[1,0.5,0],[1,0.75,0],[0.75,1,0],[0.5,1,0],[0.25,1,0],[0,0.75,0],[0,0.5,0],[0,0.25,0]];container=1;{SYS_META_PROD}" vertex="1">
            <mxGeometry height="{sh}" width="{PROD_SYS_MIN_W}" x="{sx}" y="{sy}" as="geometry" />
          </mxCell>
        </object>''')

        # Containers inside system
        for i, c in enumerate(s.containers):
            cpos = offset_pos.get(c.id)
            if not cpos:
                continue
            cx, cy = cpos
            safe_cid = safe_id(c.id)
            custom_id = _short_id(c.id)
            tech_name = _container_tech_label(c.tech)
            c4tech = _tech_str(c.tech)
            cdesc = _container_desc(c)
            kind = c.kind or "service"

            label_parts = [f'<font style="font-size: 16px"><b>{xmlesc(c.name)}</b></font>']
            if kind == "ui":
                label_parts.append(f'<div>[container: {xmlesc(", ".join(t.get("name", "") for t in c.tech) if c.tech else "")}]</div>')
            else:
                label_parts.append(f'<div>[{xmlesc(kind or "container")}{tech_name}]</div>')
            label_parts.append(f'<br><div><font style="font-size: 11px"><font color="#E6E6E6">{cdesc}</font></font></div>')
            label = "".join(label_parts)

            # Container style depends on kind
            if kind == "ui":
                cont_style = f'shape=mxgraph.c4.webBrowserContainer2;whiteSpace=wrap;html=1;boundedLbl=1;rounded=0;labelBackgroundColor=none;strokeColor=#118ACD;fillColor=#23A2D9;strokeColor2=#0E7DAD;fontSize=12;fontColor=#ffffff;align=center;arcSize=20;metaEdit=1;points=[[0.5,0,0],[1,0.25,0],[1,0.5,0],[1,0.75,0],[0.5,1,0],[0,0.75,0],[0,0.5,0],[0,0.25,0]];resizable=0;dropTarget=0;{CONT_META_PROD}'
            elif kind == "db":
                cont_style = f'shape=cylinder3;size=15;whiteSpace=wrap;html=1;boundedLbl=1;rounded=0;labelBackgroundColor=none;fillColor=#23A2D9;fontSize=12;fontColor=#ffffff;align=center;arcSize=20;strokeColor=#0E7DAD;metaEdit=1;points=[[0.5,0,0],[1,0.25,0],[1,0.5,0],[1,0.75,0],[0.5,1,0],[0,0.75,0],[0,0.5,0],[0,0.25,0]];resizable=0;dropTarget=0;{CONT_META_PROD}'
            else:
                cont_style = f'rounded=1;whiteSpace=wrap;html=1;fontSize=11;labelBackgroundColor=none;fillColor=#23A2D9;fontColor=#ffffff;align=center;arcSize=10;strokeColor=#0E7DAD;metaEdit=1;resizable=0;points=[[0.5,0,0],[1,0.5,0],[1,0.75,0],[0.75,1,0],[0.5,1,0],[0.25,1,0],[0,0.75,0],[0,0.5,0]];resizable=0;dropTarget=0;{CONT_META_PROD}'

            lines.append(f'''        <object placeholders="1" c4Name="{xmlesc(c.name)}" c4Type="container" c4Description="{cdesc}" c4Technology="{xmlesc(c4tech)}" label="{xmlesc(label)}" type="container" kind="{kind}" custom_id="{xmlesc(custom_id)}" repo="{xmlesc(c.repo)}" datacategories="{xmlesc(','.join(c.dataCategories))}" ports="1" consumer="1" id="{safe_cid}">
          <mxCell parent="{safe_sys_id}" style="{cont_style}" vertex="1">
            <mxGeometry height="{PROD_CONTAINER_H}" width="{PROD_CONTAINER_W}" x="{cx - sx - offset_x + offset_x}" y="{cy - sy - offset_y + offset_y}" as="geometry" />
          </mxCell>
        </object>''')

            # Ports
            port_x = 0.076
            port_step = 0.067
            for j, iface in enumerate(c.interfaces):
                pid = iface.id
                safe_pid = safe_id(pid)
                lines.append(_gen_port_small(pid, iface, safe_cid, port_x + j * port_step))
                port_x += port_step

    # ── Standalone containers ──
    for c in standalone:
        cpos = offset_pos.get(c.id)
        if not cpos:
            continue
        cx, cy = cpos
        safe_cid = safe_id(c.id)
        custom_id = _short_id(c.id)
        tech_name = _container_tech_label(c.tech)
        c4tech = _tech_str(c.tech)
        cdesc = _container_desc(c)
        kind = c.kind or "service"

        label = (f'<font style="font-size: 16px"><b>{xmlesc(c.name)}</b></font>'
                 f'<div>[container{tech_name}]</div><br>'
                 f'<div><font style="font-size: 11px"><font color="#E6E6E6">{cdesc}</font></font></div>')

        if kind == "db":
            cont_style = f'shape=cylinder3;size=15;whiteSpace=wrap;html=1;boundedLbl=1;rounded=0;labelBackgroundColor=none;fillColor=#23A2D9;fontSize=12;fontColor=#ffffff;align=center;arcSize=20;strokeColor=#0E7DAD;metaEdit=1;points=[[0.5,0,0],[1,0.25,0],[1,0.5,0],[1,0.75,0],[0.5,1,0],[0,0.75,0],[0,0.5,0],[0,0.25,0]];resizable=0;dropTarget=0;{CONT_META_PROD}'
        else:
            cont_style = f'rounded=1;whiteSpace=wrap;html=1;fontSize=11;labelBackgroundColor=none;fillColor=#23A2D9;fontColor=#ffffff;align=center;arcSize=10;strokeColor=#0E7DAD;metaEdit=1;resizable=0;points=[[0.5,0,0],[1,0.5,0],[1,0.75,0],[0.75,1,0],[0.5,1,0],[0.25,1,0],[0,0.75,0],[0,0.5,0]];resizable=0;dropTarget=0;{CONT_META_PROD}'

        lines.append(f'''        <object placeholders="1" c4Name="{xmlesc(c.name)}" c4Type="container" c4Description="{cdesc}" c4Technology="{xmlesc(c4tech)}" label="{xmlesc(label)}" type="container" kind="{kind}" custom_id="{xmlesc(custom_id)}" repo="{xmlesc(c.repo)}" datacategories="{xmlesc(','.join(c.dataCategories))}" ports="1" consumer="1" id="{safe_cid}">
          <mxCell parent="{safe_prod_id}" style="{cont_style}" vertex="1">
            <mxGeometry height="{PROD_CONTAINER_H}" width="{PROD_CONTAINER_W}" x="{cx}" y="{cy}" as="geometry" />
          </mxCell>
        </object>''')

        port_x = 0.076
        port_step = 0.067
        for j, iface in enumerate(c.interfaces):
            pid = iface.id
            safe_pid = safe_id(pid)
            lines.append(_gen_port_small(pid, iface, safe_cid, port_x + j * port_step))
            port_x += port_step

    # ── External Systems ──
    for s in ext_list:
        pos = offset_pos.get(s.id)
        if not pos:
            continue
        ex, ey = pos
        safe_ext_id = safe_id(s.id)
        ext_label = (f'<font style="font-size: 16px"><b>{xmlesc(s.name)}</b></font>'
                     f'<div>[{xmlesc(s.desc.split(chr(10))[0] if s.desc else "externalMTSSystem")}]</div>')
        lines.append(f'''        <object placeholders="1" c4Name="{xmlesc(s.name)}" c4Type="externalMTSSystem" c4Description="{xmlesc(s.desc)}" label="{xmlesc(ext_label)}" type="external" is_external="1" consumer="1" custom_id="{xmlesc(s.id)}" id="{safe_ext_id}">
          <mxCell parent="1" style="rounded=1;whiteSpace=wrap;html=1;labelBackgroundColor=none;fillColor=#e51400;fontColor=#ffffff;align=center;arcSize=10;strokeColor=#736782;metaEdit=1;resizable=1;points=[[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0.25,0],[1,0.5,0],[1,0.75,0],[0.75,1,0],[0.5,1,0],[0.25,1,0],[0,0.75,0],[0,0.5,0],[0,0.25,0]];resizeHeight=1;dropTarget=0;{EXT_META_PROD}" vertex="1">
            <mxGeometry x="{ex}" y="{ey}" width="240" height="120" as="geometry" />
          </mxCell>
        </object>''')
        for iface in s.interfaces:
            pid = iface.id
            safe_pid = safe_id(pid)
            ppos = offset_pos.get(pid, (0, 0, 0))
            if isinstance(ppos, tuple) and len(ppos) == 3:
                _, abs_x, abs_y = ppos
            else:
                abs_x, abs_y = ex - 8, ey + 10
            pdesc = xmlesc(iface.desc)
            pname = xmlesc(iface.name)
            ptech = xmlesc(iface.tech)
            pspec = xmlesc(iface.spec)
            puri = xmlesc(iface.uri)
            lines.append(f'''        <object placeholders="1" label="" type="port" custom_id="{xmlesc(iface.id.split('.')[-1])}" c4Name="{pname}" port="{iface.port}" desc="{pdesc}" tech="{ptech}" serviceid="" dataobjects="" spec="{pspec}" slo="latency=0" uri="{puri}" id="{xmlesc(pid)}">
          <mxCell style="port;image={PORT_SVG};" parent="1" vertex="1">
            <mxGeometry x="{abs_x}" y="{abs_y}" width="16" height="16" as="geometry">
              <mxPoint x="-8" y="-8" as="offset" />
            </mxGeometry>
          </mxCell>
        </object>''')

    # ── Roles (people) ──
    role_list = sorted(set(r.id for r in _collect_roles(systems, standalone)))
    for rid in role_list:
        r = role_data.get(rid)
        if not r:
            continue
        pos = offset_pos.get(rid)
        if not pos:
            continue
        rx, ry = pos
        safe_rid = safe_id(rid)
        label = (f'<font style=" font-size: 16px"><b>{xmlesc(rid)}</b></font>'
                 f'<div>[Role]</div><br>'
                 f'<div><font style="font-size: 11px"><font color="#cccccc">{xmlesc(r.desc)}</font></font></div>')
        lines.append(f'''        <object placeholders="1" c4Type="Role" c4Name="{xmlesc(rid)}" c4Description="{xmlesc(r.desc)}" custom_id="{xmlesc(rid)}" label="{xmlesc(label)}" type="role" not_target="1" id="{safe_rid}">
          <mxCell parent="{safe_prod_id}" style="html=1;fontSize=11;dashed=0;whiteSpace=wrap;fillColor=#083F75;strokeColor=#ffffff;fontColor=#ffffff;shape=mxgraph.c4.person2;align=center;metaEdit=1;points=[[0.5,0,0],[1,0.5,0],[1,0.75,0],[0.75,1,0],[0.5,1,0],[0.25,1,0],[0,0.75,0],[0,0.5,0]];resizable=0;dropTarget=0;metaData={{"c4Type":{{"editable": false}},"c4Name":{{"editable": false}},"c4Description":{{"editable": false}},"custom_id":{{"editable": false}},"type":{{"editable": false}},"not_target":{{"editable": false}}}};movable=1;rotatable=1;deletable=1;editable=1;locked=0;connectable=1;" vertex="1">
            <mxGeometry x="{rx}" y="{ry}" width="200" height="160" as="geometry" />
          </mxCell>
        </object>''')

    # ── Relationships (edges) ──
    def gen_prod_edge(source, target, desc, tech, dataflow, rel_id):
        label = (f'<div style="text-align: left">'
                 f'<div style="text-align: center"><b>{xmlesc(desc)}</b></div>'
                 f'<div style="text-align: center">[{xmlesc(tech)}]</div>'
                 f'</div>')
        pts = _route_edge(source, target, offset_bboxes)
        pts_xml = ""
        if pts:
            pts_str = "\n".join(f'                <mxPoint x="{round(p[0])}" y="{round(p[1])}" />' for p in pts)
            pts_xml = f'''
              <Array as="points">
{pts_str}
              </Array>'''
        return f'''        <object placeholders="1" c4Name="Relationship" c4Type="Relationship" desc="{xmlesc(desc)}" c4Technology="{xmlesc(tech)}" label="{xmlesc(label)}" type="relationship" dataflow="{xmlesc(dataflow)}" c4Description="{xmlesc(desc)}" id="{xmlesc(rel_id)}">
          <mxCell edge="1" parent="1" source="{xmlesc(source)}" style="endArrow=blockThin;html=1;fontSize=10;fontColor=#404040;strokeWidth=1;endFill=1;strokeColor=#828282;elbow=vertical;metaEdit=1;endSize=14;startSize=14;jumpStyle=arc;jumpSize=16;rounded=0;edgeStyle=orthogonalEdgeStyle;{EDGE_META_PROD}" target="{xmlesc(target)}">
            <mxGeometry width="240" as="geometry">{pts_xml}
            </mxGeometry>
          </mxCell>
        </object>'''

    # Container dependencies
    for s in systems.values():
        if s.is_external:
            continue
        for c in s.containers:
            for dep in c.dependencies:
                target_id = dep.interfaceId or dep.id
                src, tgt = c.id, target_id
                ek = (src, tgt)
                if ek in edge_keys: continue
                edge_keys.add(ek)
                rid = f"{src}_{tgt}{dep.desc}"[:120]
                safe_rid = safe_id(rid)
                if src in known_ids and tgt in known_ids:
                    lines.append(gen_prod_edge(src, tgt, dep.desc, dep.tech, dep.dataflow, safe_rid))

    for c in standalone:
        for dep in c.dependencies:
            target_id = dep.interfaceId or dep.id
            src, tgt = c.id, target_id
            ek = (src, tgt)
            if ek in edge_keys: continue
            edge_keys.add(ek)
            rid = f"{src}_{tgt}{dep.desc}"[:120]
            safe_rid = safe_id(rid)
            if src in known_ids and tgt in known_ids:
                lines.append(gen_prod_edge(src, tgt, dep.desc, dep.tech, dep.dataflow, safe_rid))

    # Consumers
    for s in systems.values():
        for consumer in s.consumers:
            src, tgt = consumer.id, consumer.interfaceId
            ek = (src, tgt)
            if ek in edge_keys: continue
            edge_keys.add(ek)
            rid = f"{src}_{tgt}_consumer"[:120]
            safe_rid = safe_id(rid)
            dep_obj = _find_dep_for(s, consumer.id, consumer.interfaceId)
            desc = dep_obj.desc if dep_obj else ""
            tech = dep_obj.tech if dep_obj else ""
            dataflow = dep_obj.dataflow if dep_obj else ""
            if src in known_ids and tgt in known_ids:
                lines.append(gen_prod_edge(src, tgt, desc, tech, dataflow, safe_rid))

    for s in systems.values():
        for c in s.containers:
            for consumer in c.consumers:
                src, tgt = consumer.id, consumer.interfaceId
                ek = (src, tgt)
                if ek in edge_keys: continue
                edge_keys.add(ek)
                rid = f"{src}_{tgt}_consumer"[:120]
                safe_rid = safe_id(rid)
                dep_obj = _find_dep_for_container(c, consumer.id, consumer.interfaceId)
                desc = dep_obj.desc if dep_obj else ""
                tech = dep_obj.tech if dep_obj else ""
                dataflow = dep_obj.dataflow if dep_obj else ""
                if src in known_ids and tgt in known_ids:
                    lines.append(gen_prod_edge(src, tgt, desc, tech, dataflow, safe_rid))

    for c in standalone:
        for consumer in c.consumers:
            src, tgt = consumer.id, consumer.interfaceId
            ek = (src, tgt)
            if ek in edge_keys: continue
            edge_keys.add(ek)
            rid = f"{src}_{tgt}_consumer"[:120]
            safe_rid = safe_id(rid)
            dep_obj = _find_dep_for_container(c, consumer.id, consumer.interfaceId)
            desc = dep_obj.desc if dep_obj else ""
            tech = dep_obj.tech if dep_obj else ""
            dataflow = dep_obj.dataflow if dep_obj else ""
            if src in known_ids and tgt in known_ids:
                lines.append(gen_prod_edge(src, tgt, desc, tech, dataflow, safe_rid))

    # Role → system/container
    role_targets = {}
    for s in systems.values():
        if s.is_external:
            continue
        for r in s.roles:
            role_targets[r.id] = s.id
        for c in s.containers:
            for r in c.roles:
                role_targets[r.id] = c.id
    for c in standalone:
        for r in c.roles:
            role_targets[r.id] = c.id
    for rid, target_id in role_targets.items():
        r = role_data.get(rid)
        if not r:
            continue
        ek = (rid, target_id)
        if ek in edge_keys: continue
        edge_keys.add(ek)
        rel_id = f"{rid}_{target_id}{r.desc}"[:120]
        safe_rel_id = safe_id(rel_id)
        if rid in known_ids and target_id in known_ids:
            lines.append(gen_prod_edge(rid, target_id, r.desc, r.tech, r.dataflow, safe_rel_id))

    diagram_xml = "\n".join(lines)
    return f'''<mxfile host="app.diagrams.net" agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" version="22.1.18">
  <diagram name="Контейнеры продукта" id="Контейнеры продукта">
    <mxGraphModel dx="869" dy="2882" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="850" pageHeight="1100" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
{diagram_xml}
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>'''


def _gen_port_small(pid, iface, parent_id, fixed_px):
    px = fixed_px
    pdesc = xmlesc(iface.desc)
    pname = xmlesc(iface.name)
    ptech = xmlesc(iface.tech)
    pspec = xmlesc(iface.spec)
    puri = xmlesc(iface.uri)
    cust_id = xmlesc(iface.id.split('.')[-1])
    label = f'<font style="font-size: 8px">{cust_id}</font>'
    return f'''        <object placeholders="1" label="{label}" type="port" custom_id="{cust_id}" c4Name="{pname}" port="{iface.port}" desc="{pdesc}" tech="{ptech}" serviceid="" dataobjects="" dataflow="pull" spec="{pspec}" slo="latency=0" uri="{puri}" id="{xmlesc(pid)}">
          <mxCell parent="{parent_id}" style="image={PORT_SVG};" vertex="1">
            <mxGeometry height="16" relative="1" width="16" x="{px}" as="geometry">
              <mxPoint x="-8" y="-8" as="offset" />
            </mxGeometry>
          </mxCell>
        </object>'''


# ──────────────────────────────────────────────
# 6. Main
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Генератор drawio-диаграмм из ARCHOPS YAML-манифестов")
    parser.add_argument("input_dir", help="Путь к папке с YAML-манифестами")
    parser.add_argument("-o", "--output", default="diagram.drawio", help="Путь к выходному файлу (по умолчанию: diagram.drawio)")
    args = parser.parse_args()

    if not os.path.isdir(args.input_dir):
        print(f"Ошибка: директория {args.input_dir} не найдена", file=sys.stderr)
        sys.exit(1)

    systems, standalone, all_roles, all_interfaces = build_model(args.input_dir)
    if not systems and not standalone:
        print("Не найдено ни одной системы/контейнера в YAML-файлах", file=sys.stderr)
        sys.exit(1)

    # View 1: C4 System Container view
    positions, bboxes = assign_layout(systems, standalone, all_interfaces)
    c4_xml = generate_drawio(systems, standalone, all_roles, all_interfaces, positions, bboxes)

    # View 2: Product container view
    prod_positions, prod_bboxes = _prod_layout(systems, standalone, all_interfaces)
    prod_xml = generate_product_view(systems, standalone, all_roles, all_interfaces, prod_positions, prod_bboxes)

    # Extract diagram blocks from both and combine in one mxfile
    import re
    c4_diag = re.search(r'<diagram[> ]', c4_xml)
    prod_diag = re.search(r'<diagram[> ]', prod_xml)
    c4_start = c4_diag.start() if c4_diag else 0
    prod_start = prod_diag.start() if prod_diag else 0
    mxfile_end_c4 = c4_xml.rfind('</mxfile>')
    mxfile_end_prod = prod_xml.rfind('</mxfile>')
    c4_body = c4_xml[c4_start:mxfile_end_c4] if mxfile_end_c4 > 0 else c4_xml
    prod_body = prod_xml[prod_start:mxfile_end_prod] if mxfile_end_prod > 0 else prod_xml

    mxfile_start = c4_xml[:c4_start] if c4_start > 0 else '<mxfile host="app.diagrams.net" version="22.1.18">'
    combined = f"{mxfile_start}\n{c4_body}\n{prod_body}\n</mxfile>"

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(combined)
    print(f"OK. Diagram saved: {args.output}")

def generate_diagram_xml(yaml_dir):
    """Generate drawio XML from YAML manifests in yaml_dir.
    Returns a tuple (c4_view_xml, product_view_xml, combined_xml)."""
    systems, standalone, all_roles, all_interfaces = build_model(yaml_dir)
    if not systems and not standalone:
        return None, None, None

    positions, bboxes = assign_layout(systems, standalone, all_interfaces)
    c4_xml = generate_drawio(systems, standalone, all_roles, all_interfaces, positions, bboxes)

    prod_positions, prod_bboxes = _prod_layout(systems, standalone, all_interfaces)
    prod_xml = generate_product_view(systems, standalone, all_roles, all_interfaces, prod_positions, prod_bboxes)

    import re
    c4_diag = re.search(r'<diagram[> ]', c4_xml)
    prod_diag = re.search(r'<diagram[> ]', prod_xml)
    c4_start = c4_diag.start() if c4_diag else 0
    prod_start = prod_diag.start() if prod_diag else 0
    mxfile_end_c4 = c4_xml.rfind('</mxfile>')
    mxfile_end_prod = prod_xml.rfind('</mxfile>')
    c4_body = c4_xml[c4_start:mxfile_end_c4] if mxfile_end_c4 > 0 else c4_xml
    prod_body = prod_xml[prod_start:mxfile_end_prod] if mxfile_end_prod > 0 else prod_xml
    mxfile_start = c4_xml[:c4_start] if c4_start > 0 else '<mxfile host="app.diagrams.net" version="22.1.18">'
    combined = f"{mxfile_start}\n{c4_body}\n{prod_body}\n</mxfile>"
    return c4_xml, prod_xml, combined

if __name__ == "__main__":
    main()
