const $ = id => document.getElementById(id);

const numApps = $('numApps');
const contsPerApp = $('contsPerApp');
const numClients = $('numClients');
const rps = $('rps');
const dbLatency = $('dbLatency');

function formatNum(n) {
  return Number(n).toLocaleString('ru-RU');
}

numApps.addEventListener('input', () => $('numAppsVal').textContent = numApps.value);
contsPerApp.addEventListener('input', () => $('contsPerAppVal').textContent = contsPerApp.value);
numClients.addEventListener('input', () => $('numClientsVal').textContent = formatNum(numClients.value));
rps.addEventListener('input', () => $('rpsVal').textContent = rps.value);
dbLatency.addEventListener('input', () => $('dbLatencyVal').textContent = dbLatency.value);

const locustUsers = $('locustUsers');
const locustSpawnRate = $('locustSpawnRate');
const locustDuration = $('locustDuration');
locustUsers.addEventListener('input', () => $('locustUsersVal').textContent = locustUsers.value);
locustSpawnRate.addEventListener('input', () => $('locustSpawnRateVal').textContent = locustSpawnRate.value);
locustDuration.addEventListener('input', () => $('locustDurationVal').textContent = locustDuration.value);

// ── Scenarios ─────────────────────────────────────────────
let selectedScenario = null;
let scenariosData = {};

async function loadScenarios() {
  const res = await fetch('/api/scenarios');
  const data = await res.json();
  scenariosData = data.scenarios;
  const container = $('scenarios');
  container.innerHTML = '';
  Object.entries(data.scenarios).forEach(([key, sc]) => {
    const div = document.createElement('div');
    div.className = 'scenario-item';
    div.dataset.key = key;
    div.innerHTML = `
      <div class="s-name">${sc.name}</div>
      <div class="s-desc">${sc.description}</div>
      <div class="s-params">${sc.params.label || ''}</div>
    `;
    div.addEventListener('click', () => {
      container.querySelectorAll('.scenario-item').forEach(el => el.classList.remove('active'));
      div.classList.add('active');
      selectedScenario = key;
      const badge = $('scenarioBadge');
      badge.textContent = key;
      badge.className = 'scenario-badge ' + key;
      $('scenarioLabel').textContent = sc.name;
    });
    container.appendChild(div);
  });
}

// ── D3 Graph ──────────────────────────────────────────────
let currentResult = null;
let sim = null;

function svgW() { return document.getElementById('graph').clientWidth || 900; }
function svgH() { return document.getElementById('graph').clientHeight || 600; }

function buildGraph(result) {
  const w = svgW();
  const h = svgH();
  $('graph').innerHTML = '';

  const svg = d3.select('#graph')
    .append('svg')
    .attr('width', w)
    .attr('height', h);

  const defs = svg.append('defs');

  defs.append('marker')
    .attr('id', 'arr-gray')
    .attr('viewBox', '0 -5 10 10').attr('refX', 20).attr('refY', 0)
    .attr('markerWidth', 5).attr('markerHeight', 5).attr('orient', 'auto')
    .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#828282');

  defs.append('marker')
    .attr('id', 'arr-warn')
    .attr('viewBox', '0 -5 10 10').attr('refX', 20).attr('refY', 0)
    .attr('markerWidth', 5).attr('markerHeight', 5).attr('orient', 'auto')
    .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#d29922');

  defs.append('marker')
    .attr('id', 'arr-crit')
    .attr('viewBox', '0 -5 10 10').attr('refX', 20).attr('refY', 0)
    .attr('markerWidth', 5).attr('markerHeight', 5).attr('orient', 'auto')
    .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#f85149');

  const nodes = result.components.map(c => ({
    id: c.id, label: c.label, type: c.type, status: c.status,
    cpu: c.cpu_percent, mem: c.memory_percent, lat: c.latency_ms,
    rps: c.rps, err: c.error_rate, load: c.load_percent,
    propagated: c.propagated || false,
  }));

  const linkMap = new Map();
  result.edges.forEach(e => {
    const key = `${e.source}|${e.target}`;
    const prio = { critical: 2, warning: 1, healthy: 0 };
    if (!linkMap.has(key) || prio[e.status] > prio[linkMap.get(key).status]) {
      linkMap.set(key, e);
    }
  });
  const links = Array.from(linkMap.values()).map(e => ({
    source: e.source, target: e.target,
    label: e.label, value: e.value, status: e.status,
  }));

  const typeColors = {
    clients: '#58a6ff', lb: '#a371f7', gateway: '#f0883e',
    app: '#23A2D9', container: '#23A2D9', database: '#23A2D9',
    external: '#e51400',
  };
  const statusColors = {
    healthy: '#3fb950', warning: '#d29922', critical: '#f85149',
  };
  const PROD_GRAY = '#828282';

  // ── Build app groups for system boundaries ──
  const sysGroups = {};
  nodes.forEach(n => {
    if (n.type === 'app') {
      sysGroups[n.id] = { app: n, members: [n], label: n.label.split('\n')[0] };
    }
  });
  nodes.forEach(n => {
    if (n.type === 'container') {
      const parts = n.id.split('_');
      if (parts.length >= 3) {
        const appId = 'app_' + parts[1];
        if (sysGroups[appId]) {
          sysGroups[appId].members.push(n);
        }
      }
    }
  });

  // ── Layered layout to prevent edge crossings ──
  const layerY = {
    clients: h * 0.08, lb: h * 0.22, gateway: h * 0.36,
    app: h * 0.52, container: h * 0.68, database: h * 0.84,
    external: h * 0.84,
  };

  nodes.forEach(n => { n.y = layerY[n.type] || h * 0.5; });

  ['clients', 'lb', 'gateway', 'app', 'database', 'external'].forEach(type => {
    const typeNodes = nodes.filter(n => n.type === type);
    if (!typeNodes.length) return;
    if (type === 'clients' || type === 'lb' || type === 'gateway') {
      typeNodes.forEach(n => { n.x = w / 2; });
    } else if (type === 'app') {
      const totalW = w * 0.55;
      const startX = (w - totalW) / 2;
      typeNodes.forEach((n, i) => { n.x = startX + (i + 0.5) * (totalW / typeNodes.length); });
    } else if (type === 'database') {
      const totalW = w * 0.2;
      const startX = (w - totalW) / 2;
      typeNodes.forEach((n, i) => { n.x = startX + (i + 0.5) * (totalW / typeNodes.length); });
    } else if (type === 'external') {
      typeNodes.forEach(n => { n.x = w - 100; });
    }
  });

  const containers = nodes.filter(n => n.type === 'container');
  containers.forEach(n => {
    const parts = n.id.split('_');
    if (parts.length >= 3) {
      const appId = 'app_' + parts[1];
      const appNode = nodes.find(nn => nn.id === appId);
      if (appNode) {
        const siblings = containers.filter(nn => nn.id.startsWith('container_' + parts[1]));
        const idx = siblings.indexOf(n);
        const spacing = Math.min(80, (w * 0.5) / Math.max(1, siblings.length));
        const totalW = (siblings.length - 1) * spacing;
        n.x = appNode.x - totalW / 2 + idx * spacing;
      }
    }
  });

  sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(d => {
      const s = typeof d.source === 'object' ? d.source : nodes.find(n => n.id === d.source);
      const t = typeof d.target === 'object' ? d.target : nodes.find(n => n.id === d.target);
      if (!s || !t) return 120;
      if (s.type === 'clients' || t.type === 'clients') return 200;
      if (s.type === 'container' || t.type === 'container') return 90;
      return 130;
    }).strength(0.3))
    .force('x', d3.forceX(d => d.x).strength(0.25))
    .force('y', d3.forceY(d => layerY[d.type] || h * 0.5).strength(0.35))
    .force('collision', d3.forceCollide(d => d.type === 'container' ? 40 : 55))
    .alpha(0.2)
    .alphaDecay(0.04);

  const linkG = svg.append('g');
  // Mark propagated edges for thicker rendering
  const propagatedSourceIds = new Set(nodes.filter(n => n.propagated).map(n => n.id));
  links.forEach(l => { l.isPropagated = propagatedSourceIds.has(l.source) || propagatedSourceIds.has(l.target); });

  const linkEls = linkG.selectAll('line').data(links).join('line')
    .attr('stroke', d => d.status === 'healthy' ? PROD_GRAY : d.status === 'warning' ? '#d29922' : '#f85149')
    .attr('stroke-dasharray', d => d.status === 'critical' ? '5,3' : d.status === 'warning' ? '3,2' : 'none')
    .attr('stroke-width', d => {
      const base = Math.max(1, Math.min(3.5, (d.value || 1) / 40));
      return d.isPropagated && d.status !== 'healthy' ? base * 1.8 : base;
    })
    .attr('marker-end', d => 'url(#arr-' + (d.status === 'healthy' ? 'gray' : d.status === 'warning' ? 'warn' : 'crit') + ')');

  // ── System boundaries (dashed rects per app) ──
  const boundsG = svg.append('g');
  const boundRects = [];
  Object.values(sysGroups).forEach(group => {
    if (group.members.length < 2) return;
    const rect = boundsG.append('rect')
      .attr('rx', 10).attr('ry', 10)
      .attr('fill', 'none')
      .attr('stroke', '#666')
      .attr('stroke-width', 1.5)
      .attr('stroke-dasharray', '6 3')
      .attr('opacity', 0.7);
    const lbl = boundsG.append('text')
      .attr('font-size', '11px')
      .attr('font-weight', 'bold')
      .attr('fill', '#666');
    boundRects.push({ group, rect, lbl });
  });

  // ── Nodes ──
  const nodeG = svg.append('g');
  const nodeGroup = nodeG.selectAll('g.node').data(nodes).join('g')
    .attr('class', d => 'node' + (d.status === 'critical' ? ' critical' : ''))
    .call(d3.drag()
      .on('start', (ev, d) => {
        if (!ev.active) sim.alphaTarget(0.3).restart();
        d.fx = d.x; d.fy = d.y;
      })
      .on('drag', (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
      .on('end', (ev, d) => {
        if (!ev.active) sim.alphaTarget(0);
        d.fx = null; d.fy = null;
      }));

  nodeGroup.each(function(d) {
    const g = d3.select(this);
    const sz = d.type === 'clients' ? 38 : d.type === 'gateway' || d.type === 'lb' ? 34
             : d.type === 'app' ? 30 : d.type === 'container' ? 24 : 32;
    const isBox = d.type === 'clients' || d.type === 'lb' || d.type === 'gateway' || d.type === 'app';
    const isDb = d.type === 'database';
    const isContainer = d.type === 'container';
    const isExternal = d.type === 'external';
    const fillColor = typeColors[d.type] || '#23A2D9';
    const strokeColor = statusColors[d.status] || '#666';

    // Background shape — product view style
    if (isExternal) {
      const bw = sz * 1.6, bh = sz * 0.85;
      g.append('rect').attr('class', 'node-bg')
        .attr('x', -bw / 2).attr('y', -bh / 2)
        .attr('width', bw).attr('height', bh).attr('rx', 4)
        .attr('fill', fillColor).attr('opacity', 0.2)
        .attr('stroke', strokeColor).attr('stroke-width', 2)
        .attr('stroke-dasharray', '5,3');
    } else if (isDb) {
      // Cylinder shape
      const cw = sz * 1.1, ch = sz * 0.65;
      g.append('ellipse')
        .attr('cx', 0).attr('cy', -ch / 2 + 6)
        .attr('rx', cw / 2).attr('ry', 6)
        .attr('fill', fillColor).attr('opacity', 0.25)
        .attr('stroke', strokeColor).attr('stroke-width', 1.5);
      g.append('rect')
        .attr('x', -cw / 2).attr('y', -ch / 2 + 6)
        .attr('width', cw).attr('height', ch - 12)
        .attr('fill', fillColor).attr('opacity', 0.25)
        .attr('stroke', strokeColor).attr('stroke-width', 1.5);
      g.append('line')
        .attr('x1', -cw / 2).attr('y1', ch / 2 - 6)
        .attr('x2', cw / 2).attr('y2', ch / 2 - 6)
        .attr('stroke', strokeColor).attr('stroke-width', 1.5);
      g.append('ellipse')
        .attr('cx', 0).attr('cy', ch / 2 - 6)
        .attr('rx', cw / 2).attr('ry', 6)
        .attr('fill', fillColor).attr('opacity', 0.25)
        .attr('stroke', strokeColor).attr('stroke-width', 1.5);
    } else if (isBox || isContainer) {
      g.append('rect').attr('class', 'node-bg')
        .attr('x', -sz * 0.65).attr('y', -sz * 0.4)
        .attr('width', sz * 1.3).attr('height', sz * 0.75).attr('rx', isContainer ? 6 : 5)
        .attr('fill', fillColor).attr('opacity', isContainer ? 0.3 : 0.18)
        .attr('stroke', strokeColor).attr('stroke-width', 2);
    } else {
      g.append('ellipse').attr('class', 'node-bg')
        .attr('rx', d.type === 'app' ? sz * 0.6 : sz * 0.5)
        .attr('ry', sz * 0.4)
        .attr('fill', fillColor).attr('opacity', 0.18)
        .attr('stroke', strokeColor).attr('stroke-width', 2);
    }

    if (d.status === 'critical') {
      // Red glow for propagated degradation (chain reaction)
      if (d.propagated) {
        const glow = g.append(isDb ? 'rect' : isBox || isContainer || isExternal ? 'rect' : 'ellipse');
        if (isDb) {
          glow.attr('x', -sz * 0.65).attr('y', -sz * 0.4)
            .attr('width', sz * 1.3).attr('height', sz * 0.75).attr('rx', 6);
        } else if (isBox || isContainer || isExternal) {
          glow.attr('x', -sz * 0.75).attr('y', -sz * 0.5)
            .attr('width', sz * 1.5).attr('height', sz * 0.85).attr('rx', isContainer ? 8 : 6);
        } else {
          glow.attr('rx', (d.type === 'app' ? sz * 0.7 : sz * 0.6)).attr('ry', sz * 0.45);
        }
        glow.attr('fill', 'rgba(248,81,73,0.12)').attr('stroke', 'none');
      }

      const pulse = g.append(isDb ? 'rect' : isBox || isContainer || isExternal ? 'rect' : 'ellipse');
      if (isDb) {
        pulse.attr('x', -sz * 0.55).attr('y', -sz * 0.35)
          .attr('width', sz * 1.1).attr('height', sz * 0.65).attr('rx', 4);
      } else if (isBox || isContainer || isExternal) {
        pulse.attr('x', -sz * 0.65).attr('y', -sz * 0.4)
          .attr('width', sz * 1.3).attr('height', sz * 0.75).attr('rx', isContainer ? 6 : 5);
      } else {
        pulse.attr('rx', d.type === 'app' ? sz * 0.6 : sz * 0.5).attr('ry', sz * 0.4);
      }
      pulse.attr('fill', 'none').attr('stroke', '#f85149').attr('stroke-width', 2)
        .attr('opacity', 0.5)
        .append('animate')
        .attr('attributeName', 'opacity')
        .attr('values', '0.5;0;0.5').attr('dur', '1.2s').attr('repeatCount', 'indefinite');
    }

    const lines = d.label.split('\n');
    g.append('text').attr('class', 'node-label').attr('y', isDb ? -2 : -3)
      .text(lines[0]);
    if (lines.length > 1) {
      g.append('text').attr('class', 'node-sublabel').attr('y', isDb ? 10 : 9)
        .text(lines[1]);
    }

    // Status dot
    g.append('circle')
      .attr('cx', isBox || isContainer || isExternal ? 0 : d.type === 'app' ? 18 : 14)
      .attr('cy', -(isBox || isContainer || isDb || isExternal ? 14 : d.type === 'app' ? 18 : 14))
      .attr('r', 3.5)
      .attr('fill', statusColors[d.status])
      .attr('stroke', '#0d1117').attr('stroke-width', 1.5);

    // Load bar
    const barW = isBox || isContainer || isDb || isExternal ? sz * 1.3 : sz * 1.1;
    g.append('rect')
      .attr('x', -barW / 2).attr('y', (isDb ? sz * 0.4 : isBox || isContainer || isExternal ? sz * 0.5 : sz * 0.5) + 2)
      .attr('width', barW).attr('height', 3).attr('rx', 1.5)
      .attr('fill', '#21262d');

    g.append('rect')
      .attr('x', -barW / 2).attr('y', (isDb ? sz * 0.4 : isBox || isContainer || isExternal ? sz * 0.5 : sz * 0.5) + 2)
      .attr('width', barW * Math.min(1, d.load / 100)).attr('height', 3).attr('rx', 1.5)
      .attr('fill', statusColors[d.status]);
  });

  nodeGroup.on('click', (ev, d) => showModal(d));

  sim.on('tick', () => {
    // Update edges
    linkEls
      .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y);

    // Update nodes
    nodeGroup.attr('transform', d => `translate(${d.x},${d.y})`);

    // Update system boundaries
    const pad = 30;
    boundRects.forEach(({ group, rect, lbl }) => {
      const members = group.members;
      if (!members.length) { rect.attr('display', 'none'); return; }
      rect.attr('display', null);
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      members.forEach(m => {
        const r = 28; // approx node radius
        if (m.x < minX) minX = m.x;
        if (m.y < minY) minY = m.y;
        if (m.x > maxX) maxX = m.x;
        if (m.y > maxY) maxY = m.y;
      });
      const bw = maxX - minX + pad * 2;
      const bh = maxY - minY + pad * 2;
      rect.attr('x', minX - pad).attr('y', minY - pad)
        .attr('width', bw).attr('height', bh);
      lbl.attr('x', minX - pad + 10).attr('y', minY - pad + 18)
        .text(group.label);
    });
  });

  svg.call(d3.zoom()
    .scaleExtent([0.3, 3])
    .on('zoom', (ev) => {
      nodeG.attr('transform', ev.transform);
      linkG.attr('transform', ev.transform);
      boundsG.attr('transform', ev.transform);
    }));
}

// ── Modal ─────────────────────────────────────────────────
function showModal(d) {
  $('modalTitle').textContent = d.label.split('\n')[0];
  const sl = { healthy: 'Здоров', warning: '⚠ Внимание', critical: '✕ Критично' };
  const typeLabels = {
    app: 'Приложение', container: 'Контейнер', database: 'База данных',
    gateway: 'API Gateway', lb: 'Load Balancer', clients: 'Клиенты',
    external: 'Внешний продукт',
  };
  $('modalBody').innerHTML = `
    <div class="metric-grid">
      <div class="metric-item">
        <div class="m-label">CPU</div>
        <div class="m-value ${d.cpu > 80 ? 'critical' : d.cpu > 55 ? 'warning' : 'healthy'}">${Math.round(d.cpu)}%</div>
      </div>
      <div class="metric-item">
        <div class="m-label">Память</div>
        <div class="m-value ${d.mem > 80 ? 'critical' : d.mem > 55 ? 'warning' : 'healthy'}">${Math.round(d.mem)}%</div>
      </div>
      <div class="metric-item">
        <div class="m-label">Задержка</div>
        <div class="m-value ${d.lat > 300 ? 'critical' : d.lat > 150 ? 'warning' : 'healthy'}">${Math.round(d.lat)} ms</div>
      </div>
      <div class="metric-item">
        <div class="m-label">RPS</div>
        <div class="m-value">${Math.round(d.rps)}</div>
      </div>
      <div class="metric-item">
        <div class="m-label">Ошибки</div>
        <div class="m-value ${d.err > 5 ? 'critical' : d.err > 2 ? 'warning' : 'healthy'}">${d.err.toFixed(2)}%</div>
      </div>
      <div class="metric-item">
        <div class="m-label">Нагрузка</div>
        <div class="m-value ${d.load > 80 ? 'critical' : d.load > 55 ? 'warning' : 'healthy'}">${Math.round(d.load)}%</div>
      </div>
    </div>
    <div class="modal-status ${d.status}">
      ${sl[d.status] || 'Неизвестно'} — ${typeLabels[d.type] || d.type}
    </div>
  `;
  $('modal').classList.add('open');
}

$('modalClose').addEventListener('click', () => $('modal').classList.remove('open'));
$('modal').addEventListener('click', e => { if (e.target === $('modal')) $('modal').classList.remove('open'); });

// ── Analyze ───────────────────────────────────────────────
// ── Locust toggle ──
let useLocust = false;

$('locustCheck').addEventListener('change', () => {
  useLocust = $('locustCheck').checked;
  $('locustConfig').style.display = useLocust ? 'block' : 'none';
  $('analyzeBtn').textContent = useLocust ? '⚡ Запустить тест' : '🚀 Запустить анализ';
});

// ── Manifest upload ──
let manifestNormatives = null;

$('manifestCheck').addEventListener('change', () => {
  $('manifestConfig').style.display = $('manifestCheck').checked ? 'block' : 'none';
});

$('manifestFiles').addEventListener('change', async (e) => {
  const files = e.target.files;
  if (!files.length) return;
  const formData = new FormData();
  for (const f of files) formData.append('files', f);
  try {
    const res = await fetch('/api/manifest/parse', { method: 'POST', body: formData });
    if (!res.ok) throw new Error((await res.json()).detail || 'Parse failed');
    const data = await res.json();
    manifestNormatives = data.normatives;
    const list = $('manifestAppList');
    list.innerHTML = data.apps.map(a => {
      const hpa = a.hpa_cpu_target ? `HPA:${a.hpa_cpu_target}%` : '';
      const cpu = a.cpu_limit || a.cpu_request || '-';
      const rep = a.replicas ? `${a.replicas} репл.` : '';
      return `<div class="manifest-app-row"><span class="manifest-app-name">${a.name}</span><span class="manifest-app-badge">${rep}</span><span class="manifest-app-badge">CPU:${cpu}</span>${hpa ? `<span class="manifest-app-badge">${hpa}</span>` : ''}</div>`;
    }).join('');
    $('manifestResult').style.display = 'block';

    // Auto-fill config fields from manifest
    if (data.apps.length) {
      $('numApps').value = data.apps.length;
      const avgReplicas = Math.round(data.apps.reduce((s, a) => s + a.replicas, 0) / data.apps.length);
      if (avgReplicas > 0) $('contsPerApp').value = avgReplicas;
    }
  } catch (err) {
    console.error(err);
    $('manifestAppList').innerHTML = `<span style="color:var(--red)">Error: ${err.message}</span>`;
    $('manifestResult').style.display = 'block';
  }
});

// ── Capacities toggle ──
let useCapacities = false;

$('capacitiesCheck').addEventListener('change', () => {
  useCapacities = $('capacitiesCheck').checked;
  $('capacitiesConfig').style.display = useCapacities ? 'block' : 'none';
});

function readCapacities() {
  if (!useCapacities) return undefined;
  return {
    max_clients: parseInt($('capClients').value) || 500000,
    lb_max_rps: parseInt($('capLbRps').value) || 5000,
    gw_max_rps: parseInt($('capGwRps').value) || 3000,
    rps_per_container_max: parseInt($('capContMaxRps').value) || 80,
    rps_per_container_normal: parseInt($('capContNormRps').value) || 25,
    db_latency_normal_ms: parseFloat($('capDbLatNorm').value) || 5.0,
    db_latency_danger_ms: parseFloat($('capDbLatDanger').value) || 50.0,
    container_cpu_normal: parseFloat($('capCpuNorm').value) || 25.0,
    warn_pct: parseFloat($('capWarnPct').value) || 50.0,
    crit_pct: parseFloat($('capCritPct').value) || 80.0,
  };
}

async function analyze() {
  const btn = $('analyzeBtn');
  btn.textContent = '⏳ Выполнение...';
  btn.disabled = true;

  try {
    if (useLocust) {
      const endpoints = $('locustEndpoints').value.split('\n').map(s => s.trim()).filter(Boolean);
      const body = {
        target_url: $('locustUrl').value.trim(),
        endpoints,
        config: {
          num_apps: parseInt(numApps.value),
          containers_per_app: parseInt(contsPerApp.value),
          num_clients: parseInt(numClients.value),
          rps: parseInt(rps.value),
          db_latency_ms: parseFloat(dbLatency.value),
        },
        num_users: parseInt($('locustUsers').value),
        spawn_rate: parseFloat($('locustSpawnRate').value),
        duration_sec: parseInt($('locustDuration').value),
        method: 'GET',
        normatives: manifestNormatives || undefined,
      };
      const res = await fetch('/api/locust/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Locust test failed');
      }
      const result = await res.json();
      currentResult = result;
      updateUI(result);
      $('descText').textContent = `⚡ Locust-тест: ${body.num_users} users, ${body.duration_sec}с, ${body.endpoints.length} endpoint'ов`;
    } else {
      const config = {
        num_apps: parseInt(numApps.value),
        containers_per_app: parseInt(contsPerApp.value),
        num_clients: parseInt(numClients.value),
        rps: parseInt(rps.value),
        db_latency_ms: parseFloat(dbLatency.value),
      };

      let scenario;
      if (selectedScenario && scenariosData[selectedScenario]) {
        scenario = { name: selectedScenario, params: { ...scenariosData[selectedScenario].params } };
      } else {
        scenario = {
          name: 'baseline',
          params: { rps_multiplier: 1, client_multiplier: 1, fail_count: 0, containers_add: 0, db_latency_multiplier: 1 },
        };
      }

      const capacities = readCapacities();
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, scenario, normatives: manifestNormatives || undefined, capacities }),
      });
      const result = await res.json();
      currentResult = result;
      updateUI(result);
      if (archData) {
        try {
          const syncRes = await fetch('/api/architecture/analyze-topology', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              scenario: scenario.name,
              params: scenario.params,
              per_container_capacities: perContainerCapacities,
            }),
          });
          const archSync = await syncRes.json();
          archResult = archSync;
          archNodeStatuses = archSync.node_statuses;
          renderArchitecture(archData, archNodeStatuses);
          $('archUpdated').textContent = `🕐 ${new Date().toLocaleTimeString('ru-RU')}`;
        } catch (_) { }
      }
    }
  } catch (err) {
    console.error(err);
    $('descText').textContent = '❌ Ошибка: ' + err.message;
  } finally {
    btn.textContent = useLocust ? '⚡ Запустить тест' : '🚀 Запустить анализ';
    btn.disabled = false;
  }
}

function updateUI(result) {
  assertionResults = null;
  $('assertMainSummary').style.display = 'none';
  $('healthyCount').textContent = result.summary.healthy;
  $('warningCount').textContent = result.summary.warning;
  $('criticalCount').textContent = result.summary.critical;
  $('avgLatency').textContent = result.summary.avg_latency_ms;
  $('maxCpu').innerHTML = Math.round(result.summary.max_cpu_percent) + '<span class="unit">%</span>';
  $('totalRps').textContent = Math.round(result.summary.total_rps);
  $('descText').textContent = String(result.summary.description);
  $('lastUpdated').textContent = `🕐 ${new Date().toLocaleTimeString('ru-RU')}`;
  // Store normatives from result for assertion use
  if (result.normatives) manifestNormatives = result.normatives;

  // Recommendations (collapsible)
  const recBox = $('recBox');
  const recList = $('recList');
  const recCount = $('recCount');
  if (result.recommendations && result.recommendations.length) {
    recBox.style.display = 'block';
    recCount.textContent = result.recommendations.length;
    recList.innerHTML = result.recommendations.map(r => {
      let cls = '';
      if (r.startsWith('⚠') || r.startsWith('СИСТЕМА')) cls = 'critical';
      else if (r.startsWith('⚡')) cls = 'warning';
      else if (r.startsWith('✅')) cls = 'success';
      return `<div class="rec-item ${cls}">${r}</div>`;
    }).join('');
    recBox.classList.remove('rec-open');
  } else {
    recBox.style.display = 'none';
  }

  // Results explanation
  const rp = $('resultsPanel');
  const expl = result.scenario_explanation;
  if (expl) {
    rp.style.display = 'block';
    $('resultsTitle').textContent = expl.title;

    // Verdict
    const verdictEl = $('resultsVerdict');
    verdictEl.textContent = expl.verdict;
    verdictEl.className = 'results-verdict';
    if (expl.verdict.includes('КРИТИЧЕСКИЙ') || expl.verdict.includes('ДЕГРАДИРУЕТ')) {
      verdictEl.classList.add('fail');
    } else if (expl.verdict.includes('ПРЕДЕЛЕ')) {
      verdictEl.classList.add('warn');
    } else {
      verdictEl.classList.add('ok');
    }

    // What was tested
    $('resultsWhat').textContent = expl.what_was_tested;

    // Limits table
    const limitsEl = $('resultsLimits');
    const limits = expl.system_limits;
    const limitKeys = Object.keys(limits);
    if (limitKeys.length) {
      const rows = limitKeys.map(key => {
        const l = limits[key];
        const cls = l.status === 'critical' ? 'limit-fail' : l.status === 'warning' ? 'limit-warn' : 'limit-ok';
        return `<tr>
          <td>${key}</td>
          <td class="${cls}">${l.current} ${l.unit}</td>
          <td>${l.normal} ${l.unit}</td>
          <td>${l.max_capacity} ${l.unit}</td>
        </tr>`;
      }).join('');
      limitsEl.innerHTML = `<table class="limits-table">
        <thead><tr><th>Параметр</th><th>Текущее</th><th>Норма</th><th>Максимум</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    } else {
      limitsEl.innerHTML = '';
    }
  } else {
    rp.style.display = 'none';
  }

  buildGraph(result);
}

// ── Toggle recommendations ────────────────────────────────
$('recToggle').addEventListener('click', () => {
  const recBox = $('recBox');
  const arrow = recBox.querySelector('.rec-arrow');
  const isOpen = recBox.classList.toggle('rec-open');
  arrow.textContent = isOpen ? '▼' : '▶';
});

// ── Tab switching ─────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelector(`.tab[data-tab="${name}"]`).classList.add('active');
  $(`tab${name.charAt(0).toUpperCase() + name.slice(1)}`).classList.add('active');
  if (name === 'architecture') {
    if (!archData) loadArchitecture();
    else if (document.getElementById('archGraph').children.length === 0) renderArchitecture(archData);
  }
  if (name === 'analysis') {
    setTimeout(() => { if (currentResult) buildGraph(currentResult); }, 50);
  }
}

document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => switchTab(tab.dataset.tab));
});

// ── Architecture view ─────────────────────────────────────
let archData = null;
let selectedArchNode = null;
let archSim = null;
let archResult = null;
let archNodeStatuses = null;
let perContainerCapacities = {};  // { containerId: { rps_per_container_max, rps_per_container_normal, container_cpu_normal } }

async function loadArchitecture() {
  try {
    const res = await fetch('/api/architecture/view');
    archData = await res.json();
    renderArchitecture(archData, archNodeStatuses);
    updateArchFileInfo();
  } catch (e) {
    console.error('Failed to load architecture:', e);
  }
}

async function updateArchFileInfo() {
  try {
    const res = await fetch('/api/architecture/uploaded');
    const info = await res.json();
    $('archFileName').textContent = info.name;
    $('archTitle').textContent = '🏗️ Архитектура системы (' + info.name + ')';
  } catch (_) {}
}

$('archFileInput').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await fetch('/api/architecture/upload', { method: 'POST', body: formData });
    if (!res.ok) throw new Error((await res.json()).detail || 'Upload failed');
    const data = await res.json();
    archData = data.view;
    archNodeStatuses = null;
    archResult = null;
    renderArchitecture(archData, null);
    $('archFileName').textContent = data.name;
    $('archTitle').textContent = '🏗️ Архитектура системы (' + data.name + ')';
    $('archUpdated').textContent = '✅ Загружено: ' + data.name;
  } catch (err) {
    console.error(err);
    alert('Ошибка загрузки: ' + err.message);
  }
  e.target.value = '';
});

$('archResetBtn').addEventListener('click', async () => {
  try {
    const res = await fetch('/api/architecture/reset', { method: 'POST' });
    if (!res.ok) throw new Error('Reset failed');
    archData = null;
    archNodeStatuses = null;
    archResult = null;
    await loadArchitecture();
    $('archUpdated').textContent = '🔄 Сброшено на BI_3049.drawio';
  } catch (err) {
    console.error(err);
  }
});

function getArchGroups(data) {
  // Build groups: systemBoundary → child nodes
  const boundaries = data.components.filter(n => n.type === 'systemBoundary');
  const nodeIds = new Set(data.components.filter(n => n.type !== 'systemBoundary').map(n => n.id));
  const groups = [];
  boundaries.forEach(b => {
    const members = b.children.filter(cid => nodeIds.has(cid));
    if (members.length) {
      groups.push({ id: b.id, name: b.name, members });
    }
  });
  return groups;
}

function renderArchitecture(data, nodeStatuses) {
  const container = document.getElementById('archGraph');
  const w = container.clientWidth || 900;
  const h = container.clientHeight || 600;
  container.innerHTML = '';

  const boundaryIds = new Set(data.components.filter(n => n.type === 'systemBoundary').map(n => n.id));
  const nodes = data.components.filter(n => !boundaryIds.has(n.id) && n.type !== 'role');
  const nodeIds = new Set(nodes.map(n => n.id));
  const edges = data.edges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));
  const groups = getArchGroups(data);

  const svg = d3.select('#archGraph')
    .append('svg')
    .attr('width', w)
    .attr('height', h);

  const defs = svg.append('defs');
  ['#828282', '#d29922', '#f85149'].forEach((c, i) => {
    const id = ['arch-arr', 'arch-arr-warn', 'arch-arr-crit'][i];
    defs.append('marker')
      .attr('id', id)
      .attr('viewBox', '0 -5 10 10').attr('refX', 20).attr('refY', 0)
      .attr('markerWidth', 5).attr('markerHeight', 5).attr('orient', 'auto')
      .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', c);
  });

  // Node → group mapping
  const nodeToGroup = {};
  groups.forEach(g => {
    g.members.forEach(mid => { nodeToGroup[mid] = g.id; });
  });

  const d3nodes = nodes.map(n => ({
    id: n.id, name: n.name, type: n.type,
    children: n.children || [], fill: n.fill, shape: n.shape,
    groupId: nodeToGroup[n.id] || null,
    status: (nodeStatuses && nodeStatuses[n.id]) || 'healthy',
    propagated: false,
  }));
  const d3links = edges.map(e => ({ source: e.source, target: e.target, desc: e.description || e.technology || '' }));

  const statusColors = { healthy: '#3fb950', warning: '#d29922', critical: '#f85149' };
  const isUI = d => d.shape && d.shape.includes('webBrowserContainer2');
  const isDb = d => d.shape === 'cylinder3';
  const isRole = d => d.type === 'role';
  const isExternal = d => d.type === 'external';

  // ── 1. Deterministic layout: groups in a grid, members inside — no overlap ──
  const pad = 45;
  const cols = Math.max(1, Math.ceil(Math.sqrt(groups.length)));
  const rows = Math.max(1, Math.ceil(groups.length / cols));
  const cellW = (w - 80 * 2) / cols;
  const cellH = (h - 80 * 2) / rows;

  groups.forEach((g, gi) => {
    const members = g.members.map(mid => d3nodes.find(n => n.id === mid)).filter(Boolean);
    if (!members.length) return;
    const col = gi % cols;
    const row = Math.floor(gi / cols);
    const cx = 80 + col * cellW + cellW / 2;
    const cy = 80 + row * cellH + cellH / 2;
    const boxW = cellW - pad;
    const boxH = cellH - pad;
    const boxX = cx - boxW / 2;
    const boxY = cy - boxH / 2;
    // Arrange members in a sub-grid inside the box
    const subCols = Math.ceil(Math.sqrt(members.length));
    const subRows = Math.ceil(members.length / subCols);
    members.forEach((m, mi) => {
      const sc = mi % subCols;
      const sr = Math.floor(mi / subCols);
      const slotW = boxW / subCols;
      const slotH = (boxH - 28) / subRows;
      m.x = boxX + slotW * (sc + 0.5);
      m.y = boxY + 28 + slotH * (sr + 0.5);
    });
  });

  // Ungrouped nodes (external systems, roles) on the right side
  const ungrouped = d3nodes.filter(n => !n.groupId);
  ungrouped.forEach((n, i) => {
    const sideCol = Math.floor(i / 6);
    n.x = w - 130 - sideCol * 130;
    n.y = 100 + (i % 6) * 100;
  });

  // ── 2. Minimal force simulation: just enough for edge tension & drag ──
  // Custom force: push groups apart when their dashed rects overlap
  function separateBounds(alpha) {
    if (alpha < 0.01) return;
    const strength = alpha * 0.4;
    const bpad = 55;
    const bbs = {};
    groups.forEach(g => {
      const members = g.members.map(mid => d3nodes.find(n => n.id === mid)).filter(Boolean);
      if (!members.length) { bbs[g.id] = null; return; }
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      members.forEach(m => {
        if (m.x < minX) minX = m.x;
        if (m.y < minY) minY = m.y;
        if (m.x > maxX) maxX = m.x;
        if (m.y > maxY) maxY = m.y;
      });
      bbs[g.id] = { minX: minX - bpad, minY: minY - bpad, maxX: maxX + bpad, maxY: maxY + bpad };
    });
    for (let i = 0; i < groups.length; i++) {
      for (let j = i + 1; j < groups.length; j++) {
        const a = bbs[groups[i].id], b = bbs[groups[j].id];
        if (!a || !b) continue;
        const ox = Math.min(a.maxX, b.maxX) - Math.max(a.minX, b.minX);
        const oy = Math.min(a.maxY, b.maxY) - Math.max(a.minY, b.minY);
        if (ox > 0 && oy > 0) {
          const dx = (b.minX + b.maxX) / 2 - (a.minX + a.maxX) / 2;
          const dy = (b.minY + b.maxY) / 2 - (a.minY + a.maxY) / 2;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const nx = dx / dist, ny = dy / dist;
          const force = Math.min(ox, oy) * strength * 0.04;
          const ma = groups[i].members.map(mid => d3nodes.find(n => n.id === mid)).filter(Boolean);
          const mb = groups[j].members.map(mid => d3nodes.find(n => n.id === mid)).filter(Boolean);
          ma.forEach(m => { m.vx -= nx * force; m.vy -= ny * force; });
          mb.forEach(m => { m.vx += nx * force; m.vy += ny * force; });
        }
      }
    }
  }

  archSim = d3.forceSimulation(d3nodes)
    .force('link', d3.forceLink(d3links).id(d => d.id).distance(80).strength(0.15))
    .force('collision', d3.forceCollide(50))
    .force('x', d3.forceX(d => d.x).strength(0.12))
    .force('y', d3.forceY(d => d.y).strength(0.12))
    .force('boundsSep', separateBounds)
    .alpha(0.15)
    .alphaDecay(0.04);

  // ── System boundaries ──
  const boundsG = svg.append('g');
  const boundData = groups.map(g => {
    const members = g.members.map(mid => d3nodes.find(n => n.id === mid)).filter(Boolean);
    return { id: g.id, name: g.name, members, rect: null, lbl: null };
  });
  boundData.forEach(b => {
    if (b.members.length < 1) return;
    b.rect = boundsG.append('rect')
      .attr('rx', 10).attr('ry', 10)
      .attr('fill', 'rgba(102,102,102,0.04)')
      .attr('stroke', '#888')
      .attr('stroke-width', 1.5).attr('stroke-dasharray', '7 4')
      .attr('opacity', 0.8);
    b.lbl = boundsG.append('text')
      .attr('font-size', '10px').attr('font-weight', '700')
      .attr('fill', '#888').attr('text-transform', 'uppercase')
      .attr('letter-spacing', '0.5px');
  });

  // ── Edges ──
  const linkG = svg.append('g');
  const linkEls = linkG.selectAll('line').data(d3links).join('line')
    .attr('stroke', '#828282').attr('stroke-width', 1.2)
    .attr('marker-end', 'url(#arch-arr)');

  const linkLabelG = svg.append('g');
  const linkLabels = linkLabelG.selectAll('text')
    .data(d3links.filter(d => d.desc && d.desc.length < 25))
    .join('text').attr('class', 'edge-label').text(d => d.desc);

  // ── Nodes ──
  const nodeG = svg.append('g');
  const nodeEls = nodeG.selectAll('g.arch-node').data(d3nodes).join('g')
    .attr('class', 'arch-node')
    .call(d3.drag()
      .on('start', (ev, d) => { if (!ev.active) archSim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on('drag', (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
      .on('end', (ev, d) => { if (!ev.active) archSim.alphaTarget(0); d.fx = null; d.fy = null; }));

  nodeEls.each(function(d) {
    const g = d3.select(this);
    const _isDb = isDb(d);
    const _isRole = isRole(d);
    const _isExternal = isExternal(d);
    const _isUI = isUI(d);
    const sz = _isExternal ? 38 : _isRole ? 34 : _isDb ? 30 : 32;
    const fill = d.fill || (_isExternal ? '#e51400' : _isRole ? '#083F75' : '#23A2D9');
    const strokeC = statusColors[d.status] || '#666';

    if (_isRole) {
      const bw = sz * 1.6, bh = sz * 0.85;
      g.append('rect').attr('x', -bw / 2).attr('y', -bh / 2)
        .attr('width', bw).attr('height', bh).attr('rx', 5)
        .attr('fill', fill).attr('stroke', strokeC).attr('stroke-width', 1.5);

    } else if (_isDb) {
      // Cylinder (database)
      const cw = sz * 1.2, ch = sz * 0.65;
      g.append('ellipse').attr('cx', 0).attr('cy', -ch / 2 + 4)
        .attr('rx', cw / 2).attr('ry', 4)
        .attr('fill', fill).attr('stroke', strokeC).attr('stroke-width', 1.5);
      g.append('rect').attr('x', -cw / 2).attr('y', -ch / 2 + 4)
        .attr('width', cw).attr('height', ch - 8)
        .attr('fill', fill).attr('stroke', strokeC).attr('stroke-width', 1.5);
      g.append('line').attr('x1', -cw / 2).attr('y1', ch / 2 - 4)
        .attr('x2', cw / 2).attr('y2', ch / 2 - 4)
        .attr('stroke', strokeC).attr('stroke-width', 1.5);
      g.append('ellipse').attr('cx', 0).attr('cy', ch / 2 - 4)
        .attr('rx', cw / 2).attr('ry', 4)
        .attr('fill', fill).attr('stroke', strokeC).attr('stroke-width', 1.5);

    } else if (_isUI) {
      // Browser shape (web browser container)
      const bw = sz * 1.25, bh = sz * 0.85;
      const toolbarH = 10;
      g.append('rect').attr('x', -bw / 2).attr('y', -bh / 2)
        .attr('width', bw).attr('height', toolbarH).attr('rx', 3)
        .attr('fill', strokeC).attr('stroke', strokeC).attr('stroke-width', 1);
      [-bw / 2 + 6, -bw / 2 + 13, -bw / 2 + 20].forEach(cx => {
        g.append('circle').attr('cx', cx).attr('cy', -bh / 2 + toolbarH / 2)
          .attr('r', 2.5).attr('fill', '#fff').attr('opacity', 0.5);
      });
      g.append('rect').attr('x', -bw / 2).attr('y', -bh / 2 + toolbarH)
        .attr('width', bw).attr('height', bh - toolbarH).attr('rx', 3)
        .attr('fill', fill).attr('stroke', strokeC).attr('stroke-width', 1.5);

    } else if (_isExternal) {
      // External system — red rectangle
      const bw = sz * 1.6, bh = sz * 0.75;
      g.append('rect').attr('x', -bw / 2).attr('y', -bh / 2)
        .attr('width', bw).attr('height', bh).attr('rx', 4)
        .attr('fill', '#e51400').attr('stroke', strokeC).attr('stroke-width', 2);

    } else {
      // Regular container — rounded rectangle
      const bw = sz * 1.6, bh = sz * 0.85;
      g.append('rect').attr('x', -bw / 2).attr('y', -bh / 2)
        .attr('width', bw).attr('height', bh).attr('rx', 5)
        .attr('fill', fill).attr('stroke', strokeC).attr('stroke-width', 2);
    }

    // Status dot (top-right)
    g.append('circle')
      .attr('cx', sz * 0.6).attr('cy', -sz * 0.48)
      .attr('r', 4).attr('fill', strokeC)
      .attr('stroke', '#0d1117').attr('stroke-width', 1.5);

    // Label (8px font to fit inside shapes)
    const shortName = d.name.length > 12 ? d.name.slice(0, 10) + '..' : d.name;
    g.append('text').attr('class', 'node-label').attr('font-size', '8px')
      .attr('y', _isDb ? -2 : _isUI ? -2 : -4)
      .text(shortName);

    // Sub-label (type)
    let sub = '';
    if (_isDb) sub = '[db]';
    else if (_isUI) sub = '[ui]';
    else if (_isExternal) sub = '[ext]';
    else if (_isRole) sub = '[role]';
    else sub = '[c]';
    g.append('text').attr('class', 'node-sublabel').attr('font-size', '7px')
      .attr('y', _isDb ? 7 : _isUI ? 7 : 5)
      .text(sub);

    // Load bar (like Analysis tab)
    const loadPct = d.status === 'critical' ? 85 : d.status === 'warning' ? 55 : 25;
    const barW = _isDb ? sz * 1.2 : sz * 1.6;
    const barY = _isDb ? sz * 0.38 : sz * 0.5;
    g.append('rect').attr('x', -barW / 2).attr('y', barY)
      .attr('width', barW).attr('height', 3).attr('rx', 1.5)
      .attr('fill', '#21262d');
    g.append('rect').attr('x', -barW / 2).attr('y', barY)
      .attr('width', barW * (loadPct / 100)).attr('height', 3).attr('rx', 1.5)
      .attr('fill', strokeC);

    // Red glow for propagated degradation chain
    if (d.status === 'critical' && d.propagated) {
      const gw = _isDb ? sz * 1.4 : _isUI ? sz * 1.5 : sz * 1.8;
      const gh = _isDb ? sz * 0.8 : _isUI ? sz * 1.1 : _isRole ? sz * 1.0 : sz * 0.95;
      g.append('rect')
        .attr('x', -gw / 2).attr('y', -gh / 2)
        .attr('width', gw).attr('height', gh).attr('rx', 8)
        .attr('fill', 'rgba(248,81,73,0.12)').attr('stroke', 'none');
    }

    // Pulse for critical
    if (d.status === 'critical') {
      const pw = sz * 1.4, ph = _isDb ? sz * 0.7 : _isUI ? sz * 1.0 : sz * 0.8;
      g.append('rect')
        .attr('x', -pw / 2).attr('y', -ph / 2)
        .attr('width', pw).attr('height', ph).attr('rx', 6)
        .attr('fill', 'none').attr('stroke', '#f85149').attr('stroke-width', 2)
        .attr('opacity', 0.5)
        .append('animate')
        .attr('attributeName', 'opacity')
        .attr('values', '0.5;0;0.5').attr('dur', '1.2s').attr('repeatCount', 'indefinite');
    }
  });

  nodeEls.on('click', (ev, d) => showArchInfo(d, data));

  archSim.on('tick', () => {
    linkEls
      .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    linkLabels
      .attr('x', d => (d.source.x + d.target.x) / 2)
      .attr('y', d => (d.source.y + d.target.y) / 2);
    nodeEls.attr('transform', d => `translate(${d.x},${d.y})`);

    const pad = 50;
    boundData.forEach(b => {
      if (!b.rect || !b.members.length) return;
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      b.members.forEach(m => {
        if (m.x < minX) minX = m.x;
        if (m.y < minY) minY = m.y;
        if (m.x > maxX) maxX = m.x;
        if (m.y > maxY) maxY = m.y;
      });
      b.rect.attr('x', minX - pad).attr('y', minY - pad)
        .attr('width', maxX - minX + pad * 2).attr('height', maxY - minY + pad * 2);
      b.lbl.attr('x', minX - pad + 12).attr('y', minY - pad + 18).text(b.name.toUpperCase());
    });
  });

  svg.call(d3.zoom()
    .scaleExtent([0.3, 3])
    .on('zoom', (ev) => {
      nodeG.attr('transform', ev.transform);
      linkG.attr('transform', ev.transform);
      linkLabelG.attr('transform', ev.transform);
      boundsG.attr('transform', ev.transform);
    }));

  $('archUpdated').textContent = `🕐 ${new Date().toLocaleTimeString('ru-RU')}`;

  if (archResult) {
    showArchAnalysisSummary();
  }
}

async function showArchInfo(d, data) {
  selectedArchNode = d;
  const comp = data.components.find(c => c.id === d.id);
  if (!comp) return;
  const conns = data.edges.filter(e => e.source === d.id || e.target === d.id);
  const children = comp.children || [];
  const childrenNames = children.map(cid => {
    const c = data.components.find(n => n.id === cid);
    return c ? c.name : cid;
  }).join(', ');

  // Load saved URLs
  let savedUrls = {};
  try {
    const urlRes = await fetch('/api/architecture/urls');
    savedUrls = (await urlRes.json()).urls || {};
  } catch (_) {}

  $('archInfoTitle').textContent = comp.name;
  let html = '<dl>';
  html += `<dt>Тип</dt><dd>${comp.type}</dd>`;
  if (comp.description) html += `<dt>Описание</dt><dd>${comp.description}</dd>`;
  if (childrenNames) html += `<dt>Включает</dt><dd>${childrenNames}</dd>`;
  html += `<dt>Связей</dt><dd>${conns.length}</dd>`;
  html += '</dl>';

  // Real test results for this component
  if (archRealResults && archRealResults[comp.id]) {
    const rr = archRealResults[comp.id];
    html += '<div style="margin-top:8px;border-top:1px solid var(--border);padding-top:8px">';
    html += '<div style="font-size:10px;font-weight:600;color:var(--text-muted);text-transform:uppercase;margin-bottom:4px">⚡ Реальный тест</div>';
    html += '<dl style="font-size:11px">';
    if (rr.avg_latency_ms !== undefined) html += `<dt>Latency</dt><dd>${rr.avg_latency_ms} ms</dd>`;
    if (rr.error_rate !== undefined) html += `<dt>Ошибки</dt><dd>${rr.error_rate}%</dd>`;
    if (rr.rps !== undefined) html += `<dt>RPS</dt><dd>${rr.rps}</dd>`;
    html += `<dt>Статус</dt><dd style="color:${rr.status === 'critical' ? 'var(--red)' : rr.status === 'warning' ? 'var(--yellow)' : 'var(--green)'}">${rr.status}</dd>`;
    html += '</dl></div>';
  }

  // Per-container settings
  if (comp.type === 'container' || comp.type === 'external') {
    const cap = perContainerCapacities[comp.id] || {};
    html += '<div style="margin-top:8px;border-top:1px solid var(--border);padding-top:8px">';
    html += '<div style="font-size:10px;font-weight:600;color:var(--text-muted);text-transform:uppercase;margin-bottom:4px">⚙️ Параметры контейнера</div>';
    html += '<div class="field"><label>Макс. RPS</label>';
    html += `<input type="number" id="capRpsMax_${comp.id}" class="cap-input" value="${cap.rps_per_container_max || 80}" min="1" step="5"></div>`;
    html += '<div class="field"><label>Норма RPS</label>';
    html += `<input type="number" id="capRpsNorm_${comp.id}" class="cap-input" value="${cap.rps_per_container_normal || 25}" min="1" step="1"></div>`;
    html += '<div class="field"><label>Норма CPU (%)</label>';
    html += `<input type="number" id="capCpu_${comp.id}" class="cap-input" value="${cap.container_cpu_normal || 25}" min="1" max="100" step="1"></div>`;
    html += '<div class="field"><label>Endpoint для реального теста</label>';
    html += `<input type="text" id="archUrl_${comp.id}" class="cap-input" value="${savedUrls[comp.id] || ''}" placeholder="/api/v1/health"></div>`;
    html += `<button id="saveArchUrl_${comp.id}" style="margin-top:4px;font-size:10px;padding:2px 8px;background:var(--accent);color:#fff;border:none;border-radius:var(--radius-sm);cursor:pointer">💾 Сохранить URL</button>`;
    html += '</div>';
  }

  $('archInfoBody').innerHTML = html;
  $('archAnalyzeBtn').textContent = '📊 Анализировать';
  $('archAnalyzeBtn').disabled = false;
  $('archInfo').style.display = 'block';

  // Wire save URL button
  if (comp.type === 'container' || comp.type === 'external') {
    const saveBtn = document.getElementById(`saveArchUrl_${comp.id}`);
    if (saveBtn) {
      saveBtn.addEventListener('click', async () => {
        const urlInput = document.getElementById(`archUrl_${comp.id}`);
        if (!urlInput) return;
        const urls = { [comp.id]: urlInput.value };
        try {
          await fetch('/api/architecture/save-urls', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ component_urls: urls }),
          });
          saveBtn.textContent = '✅ Сохранено';
          setTimeout(() => { saveBtn.textContent = '💾 Сохранить URL'; }, 1500);
        } catch (e) {
          saveBtn.textContent = '❌ Ошибка';
        }
      });
    }
  }
}

function readArchPerContainerCaps(componentId) {
  const cap = {};
  const maxRps = document.getElementById(`capRpsMax_${componentId}`);
  const normRps = document.getElementById(`capRpsNorm_${componentId}`);
  const cpu = document.getElementById(`capCpu_${componentId}`);
  if (maxRps) cap.rps_per_container_max = parseInt(maxRps.value) || 80;
  if (normRps) cap.rps_per_container_normal = parseInt(normRps.value) || 25;
  if (cpu) cap.container_cpu_normal = parseFloat(cpu.value) || 25;
  return Object.keys(cap).length ? cap : undefined;
}

async function runArchAnalysis(componentId, data) {
  try {
    const scenarioName = selectedScenario || 'baseline';
    const scenarioParams = scenariosData[scenarioName] ? { ...scenariosData[scenarioName].params } : {};

    // Collect per-container capacities from UI
    const caps = {};
    if (componentId) {
      const cap = readArchPerContainerCaps(componentId);
      if (cap) caps[componentId] = cap;
    }

    const res = await fetch('/api/architecture/analyze-topology', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scenario: scenarioName,
        params: scenarioParams,
        per_container_capacities: caps,
      }),
    });
    const result = await res.json();
    archResult = result;

    // Update analysis tab with results
    currentResult = result.analysis;
    if (result.analysis && result.analysis.summary) {
      updateUI(result.analysis);
    }

    // Re-render architecture with status overlay
    if (result.node_statuses) {
      archNodeStatuses = result.node_statuses;
      renderArchitecture(data, archNodeStatuses);
    }

    $('archAnalyzeBtn').textContent = '📊 Показать анализ';
    $('archAnalyzeBtn').disabled = false;
    $('archAnalyzeBtn').onclick = () => {
      $('archInfo').style.display = 'none';
      switchTab('analysis');
    };
  } catch (e) {
    console.error('Arch analysis failed:', e);
    $('archAnalyzeBtn').textContent = '❌ Ошибка';
  }
}

function showArchAnalysisSummary() {
  if (!archResult) return;
  const s = archResult.analysis.summary;
  const verdict = archResult.analysis.scenario_explanation?.verdict || '';
  const infoPanel = $('archInfo');
  if (infoPanel.style.display !== 'block') {
    // Show inline summary in graph area
    let existing = document.getElementById('archSummaryBadge');
    if (!existing) {
      existing = document.createElement('div');
      existing.id = 'archSummaryBadge';
      existing.className = 'arch-summary-badge';
      document.getElementById('archGraph').appendChild(existing);
    }
    const cls = s.critical > 0 ? 'fail' : s.warning > 0 ? 'warn' : 'ok';
    existing.className = 'arch-summary-badge ' + cls;
    existing.innerHTML = `
      <div class="asb-row">✅ ${s.healthy} | ⚠ ${s.warning} | ❌ ${s.critical}</div>
      <div class="asb-verdict">${verdict.substring(0, 60)}</div>
      <div class="asb-hint">Нажмите на компонент для деталей</div>
    `;
    existing.style.display = 'block';
  }
}

$('archInfoClose').addEventListener('click', () => {
  $('archInfo').style.display = 'none';
  selectedArchNode = null;
});

$('archAnalyzeAllBtn').addEventListener('click', async () => {
  if (!archData) return;
  const btn = $('archAnalyzeAllBtn');
  btn.textContent = '⏳ Анализ...';
  btn.disabled = true;
  try {
    const scenarioName = selectedScenario || 'baseline';
    const scenarioParams = scenariosData[scenarioName] ? { ...scenariosData[scenarioName].params } : {};
    const res = await fetch('/api/architecture/analyze-topology', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scenario: scenarioName,
        params: scenarioParams,
        per_container_capacities: perContainerCapacities,
      }),
    });
    const result = await res.json();
    archResult = result;
    archNodeStatuses = result.node_statuses;
    renderArchitecture(archData, archNodeStatuses);
    $('archUpdated').textContent = `🕐 ${new Date().toLocaleTimeString('ru-RU')}`;
  } catch (e) {
    console.error(e);
  } finally {
    btn.textContent = '🚀 Анализировать всё';
    btn.disabled = false;
  }
});

// ── Architecture real load test (Locust) ──
let archRealResults = null;

$('archLocustRunBtn').addEventListener('click', async () => {
  if (!archData) return;
  const btn = $('archLocustRunBtn');
  const origText = btn.textContent;
  btn.textContent = '⏳ Тест...';
  btn.disabled = true;

  // Load saved URLs
  let savedUrls = {};
  try {
    const urlRes = await fetch('/api/architecture/urls');
    savedUrls = (await urlRes.json()).urls || {};
  } catch (_) {}

  const targetUrl = $('archLocustUrl').value || 'http://localhost:8000';
  const numUsers = parseInt($('archLocustUsers').value) || 5;
  const duration = parseInt($('archLocustDuration').value) || 10;

  // Only test components that have a URL configured
  const componentEndpoints = {};
  const containers = archData.components.filter(c => c.type === 'container' || c.type === 'external');
  containers.forEach(c => {
    if (savedUrls[c.id]) {
      componentEndpoints[c.id] = savedUrls[c.id];
    }
  });

  if (!Object.keys(componentEndpoints).length) {
    alert('Нет компонентов с настроенными endpoint\'ами. Кликните на компонент и укажите URL.');
    btn.textContent = origText;
    btn.disabled = false;
    return;
  }

  try {
    const res = await fetch('/api/architecture/locust-run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target_url: targetUrl,
        num_users: numUsers,
        duration_sec: duration,
        component_endpoints: componentEndpoints,
      }),
    });
    const result = await res.json();
    archRealResults = result.component_results || {};
    if (result.node_statuses) {
      archNodeStatuses = result.node_statuses;
      renderArchitecture(archData, archNodeStatuses);
    }
    // Show summary
    const entries = Object.entries(archRealResults);
    const okCount = entries.filter(([, v]) => v.status === 'healthy').length;
    const warnCount = entries.filter(([, v]) => v.status === 'warning').length;
    const critCount = entries.filter(([, v]) => v.status === 'critical').length;
    $('archUpdated').textContent = `⚡ Реальный тест: ✅${okCount} ⚠${warnCount} ❌${critCount} (${new Date().toLocaleTimeString('ru-RU')})`;
  } catch (e) {
    console.error(e);
    alert('Ошибка теста: ' + e.message);
  } finally {
    btn.textContent = origText;
    btn.disabled = false;
  }
});

// ── Assertions (JMeter-style checks) ─────────────────────
const ASSERTION_RULES = [
  {
    id: 'status', name: 'Статус', icon: '🟢',
    type: 'builtin', metric: 'status', condition: 'equals', value: 'healthy',
    severity: 'critical', jmeterType: 'Response Assertion',
    desc: 'Компонент должен быть healthy',
    combine: 'all', useRegex: false, ignoreStatus: false, scope: 'all',
    tooltip: 'Аналог Response Assertion в JMeter: проверяет, что HTTP-код ответа равен 200 (у нас — status == "healthy"). Если компонент вернул warning/critical — assertion FAIL.',
    enabled: true,
  },
  {
    id: 'latency', name: 'Длительность', icon: '⏱',
    type: 'builtin', metric: 'latency_ms', condition: 'lt', value: 200,
    severity: 'warning', jmeterType: 'Duration Assertion',
    desc: 'Ответ должен быть < 200ms',
    combine: 'all', useRegex: false, ignoreStatus: false, scope: 'all',
    tooltip: 'Аналог Duration Assertion в JMeter: проверяет, что время ответа не превышает порог (у нас — latency_ms < 200ms). Если ответ дольше — FAIL. В JMeter добавляется к Sampler\'у как дочерний элемент.',
    enabled: true,
  },
  {
    id: 'cpu', name: 'CPU', icon: '🔥',
    type: 'builtin', metric: 'cpu_percent', condition: 'lt', value: 80,
    severity: 'critical', jmeterType: 'Size Assertion',
    desc: 'CPU должен быть < 80%',
    combine: 'all', useRegex: false, ignoreStatus: false, scope: 'all',
    tooltip: 'Аналог Size Assertion в JMeter: проверяет, что размер ответа (у нас — CPU %) не превышает лимит. Size Assertion сравнивает байты через = / > / < / !=.',
    enabled: true,
  },
  {
    id: 'memory', name: 'Память', icon: '💾',
    type: 'builtin', metric: 'memory_percent', condition: 'lt', value: 80,
    severity: 'warning', jmeterType: 'Size Assertion',
    desc: 'Память должна быть < 80%',
    combine: 'all', useRegex: false, ignoreStatus: false, scope: 'all',
    tooltip: 'Аналог Size Assertion в JMeter: проверяет размер ответа (у нас — Memory %) через оператор сравнения. Если порог превышен — FAIL.',
    enabled: true,
  },
  {
    id: 'errors', name: 'Ошибки', icon: '❌',
    type: 'builtin', metric: 'error_rate', condition: 'lt', value: 5,
    severity: 'critical', jmeterType: 'JSON Assertion',
    desc: 'Ошибки должны быть < 5%',
    combine: 'all', useRegex: false, ignoreStatus: false, scope: 'all',
    tooltip: 'Аналог JSON Assertion в JMeter: парсит JSON-ответ, находит значение по JsonPath (у нас — error_rate) и сверяет с ожидаемым (< 5%). Если не совпало — FAIL.',
    enabled: true,
  },
  {
    id: 'load', name: 'Нагрузка', icon: '📈',
    type: 'builtin', metric: 'load_percent', condition: 'lt', value: 80,
    severity: 'warning', jmeterType: 'Response Assertion',
    desc: 'Нагрузка должна быть < 80%',
    combine: 'all', useRegex: false, ignoreStatus: false, scope: 'all',
    tooltip: 'Аналог Response Assertion в JMeter: проверяет текст ответа на совпадение с паттерном (у нас — load_percent < 80%). Используется режим Contains/Matches/Equals.',
    enabled: true,
  },
];

let assertionRules = JSON.parse(JSON.stringify(ASSERTION_RULES));
let assertionResults = null;
let assertViewMode = 'table';
let jsr223Counter = 0;

// ── Render rules in sidebar ──
function renderAssertionRules() {
  const container = $('assertionsRules');
  container.innerHTML = '';
  assertionRules.forEach(rule => {
    const div = document.createElement('div');
    div.className = 'assertion-rule' + (rule.enabled ? ' active' : '');
    div.title = rule.tooltip;

    let statusHtml = '<span class="rule-status none">—</span>';
    if (assertionResults) {
      const ruleResults = assertionResults.filter(r => r.ruleId === rule.id);
      const failed = ruleResults.filter(r => !r.pass).length;
      if (failed > 0) {
        statusHtml = `<span class="rule-status fail">${failed}/${ruleResults.length}</span>`;
      } else if (ruleResults.length > 0) {
        statusHtml = `<span class="rule-status pass">✓ ${ruleResults.length}</span>`;
      }
    }

    const metaParts = [];
    if (rule.type === 'jsr223') {
      metaParts.push('<span class="rule-jmeter">JSR223</span>');
      metaParts.push('<span class="rule-jmeter" style="background:var(--yellow-bg);color:var(--yellow)">📜 script</span>');
    } else {
      metaParts.push(`<span class="rule-jmeter">${rule.jmeterType}</span>`);
      let th = rule.condition === 'equals' ? '=' : '<';
      th += ` ${rule.value}${['latency_ms'].includes(rule.metric) ? 'ms' : ['error_rate','cpu_percent','memory_percent','load_percent'].includes(rule.metric) ? '%' : ''}`;
      metaParts.push(`<span class="rule-threshold">${th}</span>`);
    }
    if (rule.useRegex) metaParts.push('<span class="rule-jmeter" style="background:var(--blue-bg);color:var(--accent)">.*</span>');
    if (rule.ignoreStatus) metaParts.push('<span class="rule-jmeter" style="background:var(--yellow-bg);color:var(--yellow)">ignore</span>');
    if (rule.scope === 'sub') metaParts.push('<span class="rule-jmeter">sub</span>');

    div.innerHTML = `
      <div class="rule-toggle ${rule.enabled ? 'on' : 'off'}">${rule.enabled ? '✓' : ''}</div>
      <div class="rule-body">
        <div class="rule-name">${rule.icon} ${rule.name}</div>
        <div class="rule-meta">${metaParts.join('')}</div>
      </div>
      ${statusHtml}
    `;

    // Left click = toggle, right click (or double click) = edit
    div.addEventListener('click', () => toggleAssertionRule(rule.id));
    div.addEventListener('dblclick', (e) => { e.stopPropagation(); openRuleEditor(rule.id); });
    container.appendChild(div);
  });
}

// ── Toggle rule on/off ──
function toggleAssertionRule(id) {
  const rule = assertionRules.find(r => r.id === id);
  if (rule) {
    rule.enabled = !rule.enabled;
    renderAssertionRules();
    if (assertionResults) runAssertions();
  }
}

// ── Rule editor modal ──
let editingRuleId = null;

function openRuleEditor(id) {
  const rule = assertionRules.find(r => r.id === id);
  if (!rule) return;
  editingRuleId = id;

  const isBuiltin = rule.type === 'builtin';
  let html = '<div class="rule-editor">';

  // Name
  html += '<div class="re-section"><label class="re-label">Название</label>';
  html += `<input type="text" id="reName" value="${rule.name}" style="width:100%"></div>`;

  // JMeter Type (builtin only)
  if (isBuiltin) {
    html += '<div class="re-section"><label class="re-label">Тип JMeter</label>';
    html += `<select id="reJmeterType">
      <option value="Response Assertion" ${rule.jmeterType === 'Response Assertion' ? 'selected' : ''}>Response Assertion</option>
      <option value="Duration Assertion" ${rule.jmeterType === 'Duration Assertion' ? 'selected' : ''}>Duration Assertion</option>
      <option value="Size Assertion" ${rule.jmeterType === 'Size Assertion' ? 'selected' : ''}>Size Assertion</option>
      <option value="JSON Assertion" ${rule.jmeterType === 'JSON Assertion' ? 'selected' : ''}>JSON Assertion</option>
      <option value="JSON JMESPath Assertion" ${rule.jmeterType === 'JSON JMESPath Assertion' ? 'selected' : ''}>JSON JMESPath Assertion</option>
      <option value="XML Assertion" ${rule.jmeterType === 'XML Assertion' ? 'selected' : ''}>XML Assertion</option>
    </select></div>`;

    // Metric + Condition + Value
    html += '<div class="re-section"><label class="re-label">Параметры проверки</label>';
    html += '<div class="re-row">';
    html += `<select id="reMetric">
      <option value="status" ${rule.metric === 'status' ? 'selected' : ''}>status</option>
      <option value="cpu_percent" ${rule.metric === 'cpu_percent' ? 'selected' : ''}>cpu_percent</option>
      <option value="memory_percent" ${rule.metric === 'memory_percent' ? 'selected' : ''}>memory_percent</option>
      <option value="latency_ms" ${rule.metric === 'latency_ms' ? 'selected' : ''}>latency_ms</option>
      <option value="error_rate" ${rule.metric === 'error_rate' ? 'selected' : ''}>error_rate</option>
      <option value="load_percent" ${rule.metric === 'load_percent' ? 'selected' : ''}>load_percent</option>
    </select>`;
    html += `<select id="reCondition">
      <option value="lt" ${rule.condition === 'lt' ? 'selected' : ''}>&lt; (less than)</option>
      <option value="gt" ${rule.condition === 'gt' ? 'selected' : ''}>&gt; (greater than)</option>
      <option value="lte" ${rule.condition === 'lte' ? 'selected' : ''}>&lt;=</option>
      <option value="gte" ${rule.condition === 'gte' ? 'selected' : ''}>&gt;=</option>
      <option value="equals" ${rule.condition === 'equals' ? 'selected' : ''}>== (equals)</option>
    </select>`;
    html += `<input type="text" id="reValue" value="${rule.value}">`;
    html += '</div></div>';
  }

  // JSR223 script
  if (!isBuiltin) {
    html += '<div class="re-section"><label class="re-label">JSR223 Script (JavaScript)</label>';
    html += `<textarea id="reScript" placeholder="// Доступны: component (id, type, status, cpu_percent, memory_percent, latency_ms, rps, error_rate, load_percent)
// Должна вернуть true (PASS) или false (FAIL)
return component.cpu_percent < 50;">${rule.script || ''}</textarea>`;
    html += '<div class="re-help">Функция автоматически оборачивается. Используйте <span class="re-badge">component</span> для доступа к метрикам. Верните <span class="re-badge">true</span> (PASS) или <span class="re-badge">false</span> (FAIL).</div></div>';
  }

  // Advanced options
  html += '<div class="re-section-divider"></div>';
  html += '<div class="re-section"><label class="re-label">Расширенные настройки (JMeter)</label>';

  // Combine (OR/AND)
  html += '<div class="re-row">';
  html += `<label class="re-check">Комбинация:
    <select id="reCombine">
      <option value="all" ${rule.combine === 'all' ? 'selected' : ''}>AND (все должны пройти)</option>
      <option value="any" ${rule.combine === 'any' ? 'selected' : ''}>OR (достаточно одной)</option>
    </select>
  </label></div>`;

  // Scope
  html += '<div class="re-row">';
  html += `<label class="re-check">Scope (область):
    <select id="reScope">
      <option value="all" ${rule.scope === 'all' ? 'selected' : ''}>Main + Sub-samples</option>
      <option value="component" ${rule.scope === 'component' ? 'selected' : ''}>Main sample only</option>
      <option value="sub" ${rule.scope === 'sub' ? 'selected' : ''}>Sub-samples only</option>
    </select>
  </label></div>`;

  // Use Regex
  html += '<div class="re-row">';
  html += `<label class="re-check">
    <input type="checkbox" id="reUseRegex" ${rule.useRegex ? 'checked' : ''}>
    Использовать Regex (для строковых полей)
  </label></div>`;

  // Ignore Status
  html += '<div class="re-row">';
  html += `<label class="re-check">
    <input type="checkbox" id="reIgnoreStatus" ${rule.ignoreStatus ? 'checked' : ''}>
    Ignore Status (принудительно установить success перед проверкой)
  </label></div>`;

  html += '</div>'; // re-section

  // Buttons
  html += '<div class="re-section-divider"></div>';
  html += '<div class="re-btn-row">';
  if (rule.type === 'jsr223') {
    html += `<button class="re-btn-delete" id="reDeleteBtn">🗑 Удалить правило</button>`;
  }
  html += `<button class="re-btn-save" id="reSaveBtn">💾 Сохранить</button>`;
  html += '</div></div>';

  $('ruleModalTitle').textContent = isBuiltin ? `⚙️ ${rule.name} — ${rule.jmeterType}` : `📜 ${rule.name} — JSR223 Assertion`;
  $('ruleModalBody').innerHTML = html;
  $('ruleModal').classList.add('open');

  $('reSaveBtn').addEventListener('click', saveRuleEditor);
  const delBtn = $('reDeleteBtn');
  if (delBtn) delBtn.addEventListener('click', deleteRule);
}

function saveRuleEditor() {
  const rule = assertionRules.find(r => r.id === editingRuleId);
  if (!rule) return;

  rule.name = $('reName').value;
  if (rule.type === 'builtin') {
    rule.jmeterType = $('reJmeterType').value;
    rule.metric = $('reMetric').value;
    rule.condition = $('reCondition').value;
    const rawVal = $('reValue').value;
    rule.value = rule.metric === 'status' ? rawVal : parseFloat(rawVal) || 0;
  } else {
    rule.script = $('reScript').value;
  }
  rule.combine = $('reCombine').value;
  rule.scope = $('reScope').value;
  rule.useRegex = $('reUseRegex').checked;
  rule.ignoreStatus = $('reIgnoreStatus').checked;

  $('ruleModal').classList.remove('open');
  editingRuleId = null;
  renderAssertionRules();
  if (assertionResults) runAssertions();
}

function deleteRule() {
  if (!editingRuleId) return;
  assertionRules = assertionRules.filter(r => r.id !== editingRuleId);
  $('ruleModal').classList.remove('open');
  editingRuleId = null;
  renderAssertionRules();
  if (assertionResults) runAssertions();
}

$('ruleModalClose').addEventListener('click', () => { $('ruleModal').classList.remove('open'); editingRuleId = null; });
$('ruleModal').addEventListener('click', e => { if (e.target === $('ruleModal')) { $('ruleModal').classList.remove('open'); editingRuleId = null; } });

// ── Add JSR223 rule ──
$('addJsr223Btn').addEventListener('click', () => {
  jsr223Counter++;
  const newRule = {
    id: 'jsr223_' + jsr223Counter + '_' + Date.now(),
    name: 'JSR223 Script ' + jsr223Counter,
    icon: '📜',
    type: 'jsr223',
    script: 'return component.cpu_percent < 50;',
    language: 'js',
    severity: 'critical',
    jmeterType: 'JSR223 Assertion',
    desc: 'Пользовательский скрипт',
    combine: 'all', useRegex: false, ignoreStatus: false, scope: 'all',
    enabled: true,
  };
  assertionRules.push(newRule);
  renderAssertionRules();
  openRuleEditor(newRule.id);
});

// ── View toggle ──
document.querySelectorAll('.view-toggle-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.view-toggle-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    assertViewMode = btn.dataset.view;
    if (assertionResults) renderAssertResults();
  });
});

function renderAssertResults() {
  if (!assertionResults) return;
  if (assertViewMode === 'table') {
    $('assertTableWrap').style.display = '';
    $('assertTreeWrap').style.display = 'none';
    renderAssertTable();
  } else {
    $('assertTableWrap').style.display = 'none';
    $('assertTreeWrap').style.display = '';
    renderAssertTree();
  }
}

function renderAssertTable() {
  const tbody = $('assertionsTableBody');
  const failedResults = assertionResults.filter(r => !r.pass);
  if (failedResults.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--green);padding:8px">✅ Все проверки пройдены</td></tr>`;
  } else {
    tbody.innerHTML = failedResults.map(r => {
      const unit = ['latency_ms'].includes(r.metric) ? 'ms' : ['error_rate','cpu_percent','memory_percent','load_percent'].includes(r.metric) ? '%' : '';
      return `<tr>
        <td>${r.componentLabel}</td>
        <td>${r.ruleIcon} ${r.ruleName}</td>
        <td>${r.jmeterType}</td>
        <td>${r.expected}${unit}</td>
        <td>${typeof r.actual === 'number' ? r.actual.toFixed(1) : r.actual}${unit}</td>
        <td class="assert-fail">✕ FAIL</td>
      </tr>`;
    }).join('');
  }
}

// ── Tree View (View Results Tree) ──
let treeExpanded = {};

function renderAssertTree() {
  const container = $('assertTree');
  container.innerHTML = '';
  if (!assertionResults || !currentResult) return;

  // Group results by rule then by component
  const byRule = {};
  assertionResults.forEach(r => {
    if (!byRule[r.ruleId]) byRule[r.ruleId] = { rule: r, components: {} };
    if (!byRule[r.ruleId].components[r.componentId]) {
      byRule[r.ruleId].components[r.componentId] = { label: r.componentLabel, results: [] };
    }
    byRule[r.ruleId].components[r.componentId].results.push(r);
  });

  // Build tree
  Object.entries(byRule).forEach(([ruleId, group]) => {
    const ruleKey = 'rule_' + ruleId;
    if (treeExpanded[ruleKey] === undefined) treeExpanded[ruleKey] = true;

    const ruleNode = createTreeNode(container, ruleKey, {
      icon: group.rule.ruleIcon,
      label: group.rule.ruleName + ` (${group.rule.jmeterType})`,
      value: '',
      expanded: true,
    });

    Object.entries(group.components).forEach(([compId, compGroup]) => {
      const compKey = ruleKey + '_' + compId;
      if (treeExpanded[compKey] === undefined) treeExpanded[compKey] = false;

      const allPass = compGroup.results.every(r => r.pass);
      const compNode = createTreeNode(ruleNode.content, compKey, {
        icon: allPass ? '✅' : '❌',
        label: compGroup.label,
        value: `${compGroup.results.filter(r => r.pass).length}/${compGroup.results.length}`,
        valueClass: allPass ? 'pass' : 'fail',
        expanded: false,
      });

      compGroup.results.forEach(r => {
        const leafKey = compKey + '_' + r.metric;
        createTreeNode(compNode.content, leafKey, {
          icon: r.pass ? '✅' : '❌',
          label: r.ruleName,
          value: `${typeof r.actual === 'number' ? r.actual.toFixed(1) : r.actual} / ${r.expected}`,
          valueClass: r.pass ? 'pass' : 'fail',
          isLeaf: true,
        });
      });
    });
  });
}

function createTreeNode(parent, key, opts) {
  const isExpanded = treeExpanded[key] !== false;
  const nodeDiv = document.createElement('div');
  nodeDiv.className = 'assert-tree-node';

  const row = document.createElement('div');
  row.className = 'assert-tree-row';

  const toggle = document.createElement('span');
  toggle.className = 'assert-tree-toggle ' + (opts.isLeaf ? 'leaf' : isExpanded ? 'expanded' : 'collapsed');
  row.appendChild(toggle);

  if (!opts.isLeaf) {
    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      treeExpanded[key] = !treeExpanded[key];
      renderAssertTree();
    });
  }

  const icon = document.createElement('span');
  icon.className = 'assert-tree-icon';
  icon.textContent = opts.icon || '•';
  row.appendChild(icon);

  const label = document.createElement('span');
  label.className = 'assert-tree-label';
  label.textContent = opts.label;
  row.appendChild(label);

  if (opts.value) {
    const val = document.createElement('span');
    val.className = 'assert-tree-value ' + (opts.valueClass || 'pass');
    val.textContent = opts.value;
    row.appendChild(val);
  }

  nodeDiv.appendChild(row);

  const content = document.createElement('div');
  content.className = 'assert-tree-content';
  content.style.display = isExpanded ? 'block' : 'none';
  nodeDiv.appendChild(content);
  nodeDiv.content = content;

  parent.appendChild(nodeDiv);
  return nodeDiv;
}

// ── Evaluate a single assertion ──
function evaluateAssertion(rule, component) {
  let actual;

  // Ignore Status: force healthy before check
  let effectiveStatus = component.status;
  if (rule.ignoreStatus) effectiveStatus = 'healthy';

  // JSR223: execute user script
  if (rule.type === 'jsr223') {
    try {
      const fn = new Function('component', rule.script || 'return true;');
      const comp = {
        id: component.id,
        type: component.type,
        status: effectiveStatus,
        cpu_percent: component.cpu_percent,
        memory_percent: component.memory_percent,
        latency_ms: component.latency_ms,
        rps: component.rps,
        error_rate: component.error_rate,
        load_percent: component.load_percent,
      };
      const pass = fn(comp) === true;
      return { pass, actual: pass ? 'true' : 'false', expected: 'true' };
    } catch (e) {
      return { pass: false, actual: 'ERROR: ' + e.message, expected: 'true' };
    }
  }

  // Builtin assertion
  if (rule.metric === 'status') {
    actual = effectiveStatus;
    const expected = rule.value;
    if (rule.useRegex) {
      try { return { pass: new RegExp(expected).test(actual), actual, expected }; }
      catch (e) { return { pass: false, actual, expected: 'regex:' + expected }; }
    }
    return { pass: actual === expected, actual, expected };
  }

  actual = component[rule.metric];
  if (actual === undefined || actual === null) return { pass: true, actual: '—', expected: rule.value };

  // Per-app override from K8s manifest normatives
  let threshold = rule.value;
  if (manifestNormatives && rule.id !== 'status') {
    const compLabel = (component.label || '').split('\n')[0].trim().toLowerCase();
    const match = manifestNormatives.find(n =>
      n.app_name.toLowerCase().replace(/[\s-_]/g, '') === compLabel.replace(/[\s-_]/g, '')
    );
    if (match) {
      if (rule.id === 'latency') threshold = match.latency_slo_ms;
      else if (rule.id === 'errors') threshold = match.error_slo_pct;
      else if (rule.id === 'cpu') threshold = match.hpa_cpu_pct ? match.hpa_cpu_pct : 80;
    }
  }

  let pass;
  if (rule.useRegex && typeof actual === 'string') {
    try { pass = new RegExp(threshold).test(actual); }
    catch (e) { pass = false; }
  } else {
    switch (rule.condition) {
      case 'lt': pass = actual < threshold; break;
      case 'gt': pass = actual > threshold; break;
      case 'lte': pass = actual <= threshold; break;
      case 'gte': pass = actual >= threshold; break;
      case 'equals': pass = String(actual) === String(threshold); break;
      default: pass = true;
    }
  }
  return { pass, actual, expected: threshold };
}

// ── Run all assertions ──
function runAssertions() {
  const btn = $('runAssertionsBtn');
  btn.textContent = '⏳ Проверка...';
  btn.disabled = true;

  setTimeout(() => {
    if (!currentResult) {
      btn.textContent = '▶ Запустить проверки';
      btn.disabled = false;
      $('assertionsResults').style.display = 'none';
      $('assertPassCount').textContent = '0';
      $('assertFailCount').textContent = '0';
      $('assertTotalCount').textContent = '0';
      return;
    }

    const activeRules = assertionRules.filter(r => r.enabled);
    const rawResults = [];
    let totalAsserts = 0, passed = 0, failed = 0;

    // Determine which components to check per rule (scope)
    currentResult.components.forEach(comp => {
      activeRules.forEach(rule => {
        // Scope filtering
        if (rule.scope === 'component' && comp.type === 'container') return;
        if (rule.scope === 'sub' && comp.type !== 'container') return;

        const { pass, actual, expected } = evaluateAssertion(rule, comp);
        rawResults.push({
          componentId: comp.id,
          componentLabel: comp.label.split('\n')[0],
          ruleId: rule.id,
          ruleName: rule.name,
          ruleIcon: rule.icon,
          jmeterType: rule.jmeterType,
          metric: rule.metric,
          expected: String(expected),
          actual,
          pass,
          severity: rule.severity,
        });
        totalAsserts++;
        if (pass) passed++;
        else failed++;
      });
    });

    // Apply OR/AND combine logic per rule
    // For 'any' (OR): if at least one component passes, mark all as pass
    // For 'all' (AND): if any fails, the rule fails overall (already computed)
    activeRules.forEach(rule => {
      if (rule.combine === 'any') {
        const ruleResults = rawResults.filter(r => r.ruleId === rule.id);
        const anyPass = ruleResults.some(r => r.pass);
        ruleResults.forEach(r => {
          if (r.pass !== anyPass) {
            r.pass = anyPass;
            if (anyPass) { passed++; failed--; }
            else { passed--; failed++; }
          }
        });
      }
    });

    assertionResults = rawResults;
    $('assertPassCount').textContent = passed;
    $('assertFailCount').textContent = failed;
    $('assertTotalCount').textContent = totalAsserts;
    $('assertLastUpdated').textContent = `🕐 ${new Date().toLocaleTimeString('ru-RU')}`;
    renderAssertionRules();
    renderAssertResults();
    $('assertionsResults').style.display = 'block';
    buildAssertionGraph(currentResult, rawResults);
    updateMainAssertSummary();

    btn.textContent = '▶ Запустить проверки';
    btn.disabled = false;
  }, 100);
}

function updateMainAssertSummary() {
  const el = $('assertMainSummary');
  if (!assertionResults || assertionResults.length === 0) {
    el.style.display = 'none';
    return;
  }
  el.style.display = 'flex';
  const passed = assertionResults.filter(r => r.pass).length;
  const failed = assertionResults.filter(r => !r.pass).length;
  $('mainAssertPass').textContent = `${passed} ✓`;
  $('mainAssertFail').textContent = `${failed} ✗`;
  $('mainAssertTotal').textContent = `${passed + failed}`;
}

$('runAssertionsBtn').addEventListener('click', runAssertions);

// ── Show Details Modal ──
function showDetailsModal() {
  const modalOverlay = $('detailsModal');
  const body = $('detailsModalBody');

  if (!assertionResults || assertionResults.length === 0) {
    body.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px">Сначала запустите проверки (кнопка «▶ Запустить проверки»)</div>';
    modalOverlay.style.display = 'flex';
    return;
  }
  const passed = parseInt($('assertPassCount').textContent);
  const failed = parseInt($('assertFailCount').textContent);
  const total = parseInt($('assertTotalCount').textContent);

  // Group by rule
  const ruleMap = {};
  assertionResults.forEach(r => {
    if (!ruleMap[r.ruleId]) {
      const rule = assertionRules.find(ar => ar.id === r.ruleId);
      ruleMap[r.ruleId] = { rule, results: [] };
    }
    ruleMap[r.ruleId].results.push(r);
  });

  let html = '<div class="details-report">';
  html += '<div class="dr-summary">';
  html += `<div class="dr-summary-item"><strong>${total}</strong>Всего проверок</div>`;
  html += `<div class="dr-summary-item"><strong style="color:var(--green)">${passed}</strong>Пройдено</div>`;
  html += `<div class="dr-summary-item"><strong style="color:var(--red)">${failed}</strong>Провалено</div>`;
  html += '</div>';

  let ruleIdx = 0;
  Object.entries(ruleMap).forEach(([ruleId, group]) => {
    const rule = group.rule;
    const rulePassed = group.results.filter(r => r.pass).length;
    const ruleFailed = group.results.filter(r => !r.pass).length;
    const statusClass = ruleFailed === 0 ? 'pass' : 'fail';
    const statusIcon = ruleFailed === 0 ? '✅' : '❌';

    html += '<div class="dr-rule-group">';
    html += `<div class="dr-rule-header ${statusClass}" data-rule-idx="${ruleIdx}">`;
    html += `<span class="dr-toggle">▼</span>`;
    html += `<span class="dr-label">${rule ? rule.icon + ' ' + rule.name : ruleId}</span>`;
    html += `<span class="dr-badge ${statusClass}">${rulePassed}/${group.results.length}</span>`;
    html += '</div>';
    html += '<div class="dr-rule-body">';

    group.results.forEach(r => {
      html += '<div class="dr-comp-row">';
      html += `<span class="dr-comp-icon">${r.pass ? '✅' : '❌'}</span>`;
      html += `<span class="dr-comp-label">${r.componentLabel}</span>`;
      html += `<span class="dr-comp-expected">exp: ${r.expected}</span>`;
      const actualStr = typeof r.actual === 'number' ? r.actual.toFixed(2) : r.actual;
      html += `<span class="dr-comp-actual" style="color:${r.pass ? 'var(--green)' : 'var(--red)'}">${actualStr}</span>`;
      html += `<span class="dr-comp-status">${r.pass ? '✅' : '❌'}</span>`;
      html += '</div>';
    });

    html += '</div></div>';
    ruleIdx++;
  });

  html += '</div>';
  body.innerHTML = html;
  modalOverlay.style.display = 'flex';

  // Collapse/expand handlers
  body.querySelectorAll('.dr-rule-header').forEach(hdr => {
    hdr.addEventListener('click', () => {
      const toggle = hdr.querySelector('.dr-toggle');
      const bodyEl = hdr.nextElementSibling;
      const isCollapsed = bodyEl.style.display === 'none';
      bodyEl.style.display = isCollapsed ? 'block' : 'none';
      toggle.classList.toggle('collapsed', !isCollapsed);
    });
  });
}

$('showDetailsBtn').addEventListener('click', showDetailsModal);
$('detailsModalClose').addEventListener('click', () => { $('detailsModal').style.display = 'none'; });
$('detailsModal').addEventListener('click', (e) => {
  if (e.target === $('detailsModal')) $('detailsModal').style.display = 'none';
});

document.querySelector('.tab[data-tab="assertions"]').addEventListener('click', () => {
  setTimeout(() => {
    renderAssertionRules();
    if (currentResult) {
      if (!assertionResults) runAssertions();
      else { renderAssertResults(); buildAssertionGraph(currentResult, assertionResults); }
    }
  }, 60);
});

// ── Init ──────────────────────────────────────────────────
loadScenarios();
$('analyzeBtn').addEventListener('click', analyze);
setTimeout(analyze, 400);

window.addEventListener('resize', () => {
  if (currentResult) buildGraph(currentResult);
  if (archData && document.querySelector('.tab[data-tab="architecture"].active')) {
    renderArchitecture(archData, archNodeStatuses);
  }
  if (document.querySelector('.tab[data-tab="assertions"].active') && assertionResults) {
    buildAssertionGraph(currentResult, assertionResults);
  }
});
