import json
import os
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from app.diagram_generator import build_model, _prod_layout, _collect_roles, _route_edge, _short_id

router = APIRouter(prefix="/api", tags=["diagram"])

YAML_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "examples")


@router.get("/diagram")
def get_diagram():
    """Download .drawio file."""
    from app.diagram_generator import generate_diagram_xml
    combined = generate_diagram_xml(YAML_DIR)
    if combined is None:
        return PlainTextResponse("No YAML manifests found", status_code=404)
    c4_xml, prod_xml, full_xml = combined
    return Response(
        content=full_xml,
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="architecture.drawio"'},
    )


@router.get("/diagram/data")
def get_product_data():
    """Return product view layout data as JSON for client-side rendering."""
    systems, standalone, all_roles, all_interfaces = build_model(YAML_DIR)
    if not systems and not standalone:
        return PlainTextResponse("No YAML manifests found", status_code=404)

    positions, bboxes = _prod_layout(systems, standalone, all_interfaces)

    sys_list = sorted([s for s in systems.values() if not s.is_external], key=lambda s: s.id)
    ext_list = sorted([s for s in systems.values() if s.is_external], key=lambda s: s.id)
    role_list = sorted(set(r.id for r in _collect_roles(systems, standalone)))

    # Product boundary
    min_x = min(
        (positions[s.id][0] for s in sys_list if s.id in positions),
        default=0
    )
    min_y = min(
        (positions[s.id][1] for s in sys_list if s.id in positions),
        default=0
    )
    max_x = max(
        (positions[s.id][0] + 340 for s in sys_list if s.id in positions),
        default=800
    )
    max_y = max(
        (positions[s.id][1] + (positions.get(s.id + "_h", 200)) for s in sys_list if s.id in positions),
        default=600
    )
    for c in standalone:
        if c.id in positions:
            cx, cy = positions[c.id]
            min_x = min(min_x, cx)
            min_y = min(min_y, cy)
            max_x = max(max_x, cx + 240)
            max_y = max(max_y, cy + 120)
    for s in ext_list:
        if s.id in positions:
            ex, ey = positions[s.id]
            min_x = min(min_x, ex)
            min_y = min(min_y, ey)
            max_x = max(max_x, ex + 240)
            max_y = max(max_y, ey + 120)
    for rid in role_list:
        if rid in positions:
            rx, ry = positions[rid]
            min_x = min(min_x, rx)
            min_y = min(min_y, ry)
            max_x = max(max_x, rx + 200)
            max_y = max(max_y, ry + 160)

    ox, oy = min_x - 30, min_y - 30

    def off(pos):
        if isinstance(pos, tuple) and len(pos) >= 2:
            return (pos[0] - ox, pos[1] - oy)
        return pos

    product_name = "Product"
    for s in sys_list:
        if s.productId:
            product_name = s.productId
            break

    data = {
        "product": {
            "name": product_name,
            "x": 10,
            "y": 10,
            "w": max_x - min_x + 60,
            "h": max_y - min_y + 60,
        },
        "systems": [],
        "containers": [],
        "externalSystems": [],
        "roles": [],
        "edges": [],
    }

    # Internal systems + containers
    for s in sys_list:
        if s.id not in positions:
            continue
        sx, sy = off(positions[s.id])
        sh = positions.get(s.id + "_h", 200)
        data["systems"].append({
            "id": s.id, "name": s.name,
            "x": sx, "y": sy, "w": 340, "h": sh,
        })
        for c in s.containers:
            if c.id not in positions:
                continue
            cx, cy = off(positions[c.id])
            kind = c.kind or "service"
            data["containers"].append({
                "id": c.id, "name": c.name, "kind": kind,
                "x": cx, "y": cy, "w": 240, "h": 120,
                "systemId": s.id,
                "tech": ", ".join(t.get("name", "") for t in c.tech) if c.tech else "",
                "desc": c.desc,
                "ports": [
                    {"id": iface.id, "name": iface.id.split(".")[-1]}
                    for iface in c.interfaces
                ],
            })

    # Standalone containers
    for c in standalone:
        if c.id not in positions:
            continue
        cx, cy = off(positions[c.id])
        kind = c.kind or "service"
        data["containers"].append({
            "id": c.id, "name": c.name, "kind": kind,
            "x": cx, "y": cy, "w": 240, "h": 120,
            "systemId": None,
            "tech": ", ".join(t.get("name", "") for t in c.tech) if c.tech else "",
            "desc": c.desc,
            "ports": [
                {"id": iface.id, "name": iface.id.split(".")[-1]}
                for iface in c.interfaces
            ],
        })

    # External systems
    for s in ext_list:
        if s.id not in positions:
            continue
        ex, ey = off(positions[s.id])
        data["externalSystems"].append({
            "id": s.id, "name": s.name,
            "x": ex, "y": ey, "w": 240, "h": 120,
        })

    # Roles
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

    for rid in role_list:
        if rid not in positions:
            continue
        rx, ry = off(positions[rid])
        r = role_data.get(rid)
        data["roles"].append({
            "id": rid, "name": rid,
            "desc": r.desc if r else "",
            "x": rx, "y": ry, "w": 200, "h": 160,
        })

    # Edges (relationships)
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
    for c in standalone:
        known_ids.add(c.id)
        for iface in c.interfaces:
            known_ids.add(iface.id)

    def add_edge(src, tgt, desc, tech):
        ek = (src, tgt)
        if ek in edge_keys:
            return
        edge_keys.add(ek)
        if src not in known_ids or tgt not in known_ids:
            return
        pts = _route_edge(src, tgt, bboxes)
        waypoints = [{"x": round(p[0] - ox), "y": round(p[1] - oy)} for p in pts] if pts else []
        data["edges"].append({
            "source": src, "target": tgt,
            "label": desc, "tech": tech,
            "waypoints": waypoints,
        })

    for s in systems.values():
        if s.is_external:
            continue
        for c in s.containers:
            for dep in c.dependencies:
                add_edge(c.id, dep.interfaceId or dep.id, dep.desc, dep.tech)
    for c in standalone:
        for dep in c.dependencies:
            add_edge(c.id, dep.interfaceId or dep.id, dep.desc, dep.tech)

    # Container consumers
    for s in systems.values():
        for consumer in s.consumers:
            add_edge(consumer.id, consumer.interfaceId, "", "")
    for s in systems.values():
        for c in s.containers:
            for consumer in c.consumers:
                add_edge(consumer.id, consumer.interfaceId, "", "")
    for c in standalone:
        for consumer in c.consumers:
            add_edge(consumer.id, consumer.interfaceId, "", "")

    # Role → system / container
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
        add_edge(rid, target_id, r.desc if r else "", r.tech if r else "")

    return data


@router.get("/diagram/view", response_class=HTMLResponse)
def view_diagram():
    """SVG-based product view rendered in browser."""
    return HTMLResponse(PRODUCT_VIEW_HTML)


PRODUCT_VIEW_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Whats If — Архитектура (product view)</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#1e1e1e; font-family:'Segoe UI',sans-serif; color:#ddd; overflow:hidden; }
  .bar {
    position:fixed; top:0; left:0; right:0; height:40px;
    background:#2d2d2d; display:flex; align-items:center;
    justify-content:space-between; padding:0 16px; z-index:100;
    border-bottom:1px solid #404040;
  }
  .bar h1 { font-size:14px; font-weight:600; color:#eee; }
  .bar a { color:#2ea043; text-decoration:none; font-size:13px; font-weight:600; }
  #canvas {
    position:fixed; top:40px; left:0; right:0; bottom:0;
    overflow:auto; background:#f5f5f5;
  }
  #canvas svg { display:block; }
</style>
</head>
<body>
<div class="bar">
  <h1>📐 Product View — Архитектура</h1>
  <a href="#" onclick="window.open('/api/diagram','_blank')">⬇ Скачать .drawio</a>
</div>
<div id="canvas"></div>
<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
fetch('/api/diagram/data')
  .then(r => r.json())
  .then(data => {
    const w = data.product.w + 40;
    const h = data.product.h + 40;
    const svg = d3.select('#canvas')
      .append('svg')
      .attr('width', w)
      .attr('height', h)
      .style('min-width', w + 'px')
      .style('min-height', h + 'px');

    const defs = svg.append('defs');
    defs.append('marker')
      .attr('id', 'arr-gray')
      .attr('viewBox', '0 -5 10 10').attr('refX', 20).attr('refY', 0)
      .attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
      .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#828282');

    // Edges
    data.edges.forEach(e => {
      const srcEl = data.containers.find(c => c.id === e.source)
        || data.externalSystems.find(s => s.id === e.source)
        || data.roles.find(r => r.id === e.source)
        || data.systems.find(s => s.id === e.source);
      const tgtEl = data.containers.find(c => c.id === e.target)
        || data.externalSystems.find(s => s.id === e.target)
        || data.roles.find(r => r.id === e.target)
        || data.systems.find(s => s.id === e.target);
      if (!srcEl || !tgtEl) return;
      const sx = srcEl.x + srcEl.w / 2, sy = srcEl.y + srcEl.h / 2;
      const tx = tgtEl.x + tgtEl.w / 2, ty = tgtEl.y + tgtEl.h / 2;

      let pts;
      if (e.waypoints && e.waypoints.length) {
        pts = e.waypoints.map(p => [p.x, p.y]);
      } else {
        pts = [[(sx+tx)/2, sy], [(sx+tx)/2, ty]];
      }
      const allPts = [[sx, sy], ...pts, [tx, ty]];
      const line = d3.line()(allPts);

      svg.append('path')
        .attr('d', line)
        .attr('fill', 'none')
        .attr('stroke', '#828282')
        .attr('stroke-width', 1.5)
        .attr('marker-end', 'url(#arr-gray)');

      if (e.label) {
        const mx = (sx + tx) / 2;
        const my = (sy + ty) / 2;
        svg.append('text')
          .attr('x', mx).attr('y', my - 4)
          .attr('text-anchor', 'middle')
          .attr('font-size', '10px')
          .attr('fill', '#828282')
          .text(e.label);
      }
    });

    // Product boundary
    svg.append('rect')
      .attr('x', data.product.x).attr('y', data.product.y)
      .attr('width', data.product.w).attr('height', data.product.h)
      .attr('rx', 12).attr('ry', 12)
      .attr('fill', 'none')
      .attr('stroke', '#666')
      .attr('stroke-width', 2)
      .attr('stroke-dasharray', '8 4');
    svg.append('text')
      .attr('x', data.product.x + 14).attr('y', data.product.y + 24)
      .attr('font-size', '16px').attr('font-weight', 'bold').attr('fill', '#333')
      .text(data.product.name);
    svg.append('text')
      .attr('x', data.product.x + 14).attr('y', data.product.y + 40)
      .attr('font-size', '11px').attr('fill', '#666')
      .text('[product]');

    // System boundaries
    data.systems.forEach(s => {
      const g = svg.append('g');
      g.append('rect')
        .attr('x', s.x).attr('y', s.y)
        .attr('width', s.w).attr('height', s.h)
        .attr('rx', 10).attr('ry', 10)
        .attr('fill', 'none')
        .attr('stroke', '#666')
        .attr('stroke-width', 1.5)
        .attr('stroke-dasharray', '6 3');
      g.append('text')
        .attr('x', s.x + 12).attr('y', s.y + 22)
        .attr('font-size', '13px').attr('font-weight', 'bold').attr('fill', '#333')
        .text(s.name);
    });

    // Containers
    data.containers.forEach(c => {
      const g = svg.append('g');
      const fill = '#23A2D9', stroke = '#0E7DAD', textColor = '#fff';

      if (c.kind === 'ui') {
        // Browser shape
        g.append('rect')
          .attr('x', c.x).attr('y', c.y)
          .attr('width', c.w).attr('height', c.h)
          .attr('rx', 4).attr('ry', 4)
          .attr('fill', fill).attr('stroke', stroke).attr('stroke-width', 1.5);
        g.append('rect')
          .attr('x', c.x).attr('y', c.y)
          .attr('width', c.w).attr('height', 22)
          .attr('rx', 4).attr('ry', 4)
          .attr('fill', stroke);
        g.append('circle')
          .attr('cx', c.x + 12).attr('cy', c.y + 11)
          .attr('r', 5)
          .attr('fill', '#fff').attr('opacity', 0.6);
        g.append('circle')
          .attr('cx', c.x + 26).attr('cy', c.y + 11)
          .attr('r', 5)
          .attr('fill', '#fff').attr('opacity', 0.6);
        g.append('circle')
          .attr('cx', c.x + 40).attr('cy', c.y + 11)
          .attr('r', 5)
          .attr('fill', '#fff').attr('opacity', 0.6);
      } else if (c.kind === 'db') {
        // Cylinder shape
        g.append('ellipse')
          .attr('cx', c.x + c.w / 2).attr('cy', c.y + 10)
          .attr('rx', c.w / 2 - 2).attr('ry', 10)
          .attr('fill', fill).attr('stroke', stroke).attr('stroke-width', 1.5);
        g.append('rect')
          .attr('x', c.x + 2).attr('y', c.y + 10)
          .attr('width', c.w - 4).attr('height', c.h - 20)
          .attr('fill', fill).attr('stroke', stroke).attr('stroke-width', 1.5);
        g.append('line')
          .attr('x1', c.x + 2).attr('y1', c.y + c.h - 10)
          .attr('x2', c.x + c.w - 2).attr('y2', c.y + c.h - 10)
          .attr('stroke', stroke).attr('stroke-width', 1.5);
        g.append('ellipse')
          .attr('cx', c.x + c.w / 2).attr('cy', c.y + c.h - 10)
          .attr('rx', c.w / 2 - 2).attr('ry', 10)
          .attr('fill', fill).attr('stroke', stroke).attr('stroke-width', 1.5);
      } else {
        // Service shape
        g.append('rect')
          .attr('x', c.x).attr('y', c.y)
          .attr('width', c.w).attr('height', c.h)
          .attr('rx', 8).attr('ry', 8)
          .attr('fill', fill).attr('stroke', stroke).attr('stroke-width', 1.5);
      }

      // Container label
      g.append('text')
        .attr('x', c.x + c.w / 2).attr('y', c.y + 28)
        .attr('text-anchor', 'middle')
        .attr('font-size', '13px').attr('font-weight', 'bold')
        .attr('fill', textColor)
        .text(c.name.length > 18 ? c.name.slice(0, 16) + '..' : c.name);
      g.append('text')
        .attr('x', c.x + c.w / 2).attr('y', c.y + 44)
        .attr('text-anchor', 'middle')
        .attr('font-size', '10px')
        .attr('fill', '#ccc')
        .text('[' + c.kind + ']' + (c.tech ? ': ' + c.tech.slice(0, 20) : ''));

      // Ports
      c.ports.forEach((p, i) => {
        const px = c.x + 10 + i * 30;
        const py = c.y + c.h - 10;
        g.append('rect')
          .attr('x', px - 6).attr('y', py - 6)
          .attr('width', 12).attr('height', 12).attr('rx', 2)
          .attr('fill', '#0E7DAD').attr('stroke', '#fff').attr('stroke-width', 1);
        g.append('text')
          .attr('x', px).attr('y', py - 10)
          .attr('text-anchor', 'middle')
          .attr('font-size', '7px').attr('fill', '#555')
          .text(p.name.length > 6 ? p.name.slice(0, 5) + '..' : p.name);
      });
    });

    // External systems
    data.externalSystems.forEach(s => {
      const g = svg.append('g');
      g.append('rect')
        .attr('x', s.x).attr('y', s.y)
        .attr('width', s.w).attr('height', s.h)
        .attr('rx', 8).attr('ry', 8)
        .attr('fill', '#e51400').attr('stroke', '#736782').attr('stroke-width', 1.5);
      g.append('text')
        .attr('x', s.x + s.w / 2).attr('y', s.y + 28)
        .attr('text-anchor', 'middle')
        .attr('font-size', '14px').attr('font-weight', 'bold')
        .attr('fill', '#fff')
        .text(s.name.length > 16 ? s.name.slice(0, 14) + '..' : s.name);
      g.append('text')
        .attr('x', s.x + s.w / 2).attr('y', s.y + 48)
        .attr('text-anchor', 'middle')
        .attr('font-size', '11px').attr('fill', '#ccc')
        .text('[external system]');
    });

    // Roles (person shape)
    data.roles.forEach(r => {
      const g = svg.append('g');
      const cx = r.x + r.w / 2;
      // Head
      g.append('circle')
        .attr('cx', cx).attr('cy', r.y + 30)
        .attr('r', 14)
        .attr('fill', '#083F75').attr('stroke', '#fff').attr('stroke-width', 1.5);
      // Body (shoulders)
      g.append('ellipse')
        .attr('cx', cx).attr('cy', r.y + 70)
        .attr('rx', 30).attr('ry', 20)
        .attr('fill', '#083F75').attr('stroke', '#fff').attr('stroke-width', 1.5);
      // Body (torso)
      g.append('rect')
        .attr('x', cx - 20).attr('y', r.y + 48)
        .attr('width', 40).attr('height', 24)
        .attr('fill', '#083F75').attr('stroke', '#fff').attr('stroke-width', 1.5);
      // Label
      g.append('text')
        .attr('x', cx).attr('y', r.y + 100)
        .attr('text-anchor', 'middle')
        .attr('font-size', '12px').attr('font-weight', 'bold')
        .attr('fill', '#083F75')
        .text(r.name.length > 12 ? r.name.slice(0, 10) + '..' : r.name);
      g.append('text')
        .attr('x', cx).attr('y', r.y + 115)
        .attr('text-anchor', 'middle')
        .attr('font-size', '9px').attr('fill', '#666')
        .text('[Role]');
    });
  })
  .catch(err => {
    document.getElementById('canvas').innerHTML = '<p style="padding:20px;color:red;">Ошибка загрузки: ' + err.message + '</p>';
  });
</script>
</body>
</html>"""
