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

  sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(d => {
      const s = typeof d.source === 'object' ? d.source : nodes.find(n => n.id === d.source);
      const t = typeof d.target === 'object' ? d.target : nodes.find(n => n.id === d.target);
      if (!s || !t) return 120;
      if (s.type === 'clients' || t.type === 'clients') return 200;
      if (s.type === 'container' || t.type === 'container') return 90;
      return 130;
    }))
    .force('charge', d3.forceManyBody().strength(d => d.type === 'clients' ? -600 : -350))
    .force('center', d3.forceCenter(w / 2, h / 2))
    .force('collision', d3.forceCollide(d => d.type === 'container' ? 40 : 55));

  const linkG = svg.append('g');
  const linkEls = linkG.selectAll('line').data(links).join('line')
    .attr('stroke', d => d.status === 'healthy' ? PROD_GRAY : d.status === 'warning' ? '#d29922' : '#f85149')
    .attr('stroke-dasharray', d => d.status === 'critical' ? '5,3' : d.status === 'warning' ? '3,2' : 'none')
    .attr('stroke-width', d => Math.max(1, Math.min(3.5, (d.value || 1) / 40)))
    .attr('marker-end', d => 'url(#arr-' + (d.status === 'healthy' ? 'gray' : d.status === 'warning' ? 'warn' : 'crit') + ')');

  const linkLabelG = svg.append('g');
  const linkLabels = linkLabelG.selectAll('text')
    .data(links.filter(d => d.label && d.label.length < 12))
    .join('text').attr('class', 'edge-label').text(d => d.label);

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
    const fillColor = typeColors[d.type] || '#23A2D9';
    const strokeColor = statusColors[d.status] || '#666';

    // Background shape — product view style
    if (isDb) {
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
      const pulse = g.append(isDb ? 'rect' : isBox || isContainer ? 'rect' : 'ellipse');
      if (isDb) {
        pulse.attr('x', -sz * 0.55).attr('y', -sz * 0.35)
          .attr('width', sz * 1.1).attr('height', sz * 0.65).attr('rx', 4);
      } else if (isBox || isContainer) {
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
      .attr('cx', isBox || isContainer ? 0 : d.type === 'app' ? 18 : 14)
      .attr('cy', -(isBox || isContainer || isDb ? 14 : d.type === 'app' ? 18 : 14))
      .attr('r', 3.5)
      .attr('fill', statusColors[d.status])
      .attr('stroke', '#0d1117').attr('stroke-width', 1.5);

    // Load bar
    const barW = isBox || isContainer || isDb ? sz * 1.3 : sz * 1.1;
    g.append('rect')
      .attr('x', -barW / 2).attr('y', (isDb ? sz * 0.4 : isBox || isContainer ? sz * 0.5 : sz * 0.5) + 2)
      .attr('width', barW).attr('height', 3).attr('rx', 1.5)
      .attr('fill', '#21262d');

    g.append('rect')
      .attr('x', -barW / 2).attr('y', (isDb ? sz * 0.4 : isBox || isContainer ? sz * 0.5 : sz * 0.5) + 2)
      .attr('width', barW * Math.min(1, d.load / 100)).attr('height', 3).attr('rx', 1.5)
      .attr('fill', statusColors[d.status]);
  });

  nodeGroup.on('click', (ev, d) => showModal(d));

  sim.on('tick', () => {
    // Update edges
    linkEls
      .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y);

    // Update edge labels
    linkLabels
      .attr('x', d => (d.source.x + d.target.x) / 2)
      .attr('y', d => (d.source.y + d.target.y) / 2);

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
      linkLabelG.attr('transform', ev.transform);
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
async function analyze() {
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

  const btn = $('analyzeBtn');
  btn.textContent = '⏳ Анализ...';
  btn.disabled = true;

  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config, scenario }),
    });
    const result = await res.json();
    currentResult = result;
    updateUI(result);
    // Sync Architecture tab with the same scenario
    if (archData) {
      try {
        const syncRes = await fetch('/api/architecture/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            component_id: '',
            scenario: scenario.name,
            params: scenario.params,
          }),
        });
        const archSync = await syncRes.json();
        archResult = archSync;
        archNodeStatuses = archSync.node_statuses;
        renderArchitecture(archData, archNodeStatuses);
        $('archUpdated').textContent = `🕐 ${new Date().toLocaleTimeString('ru-RU')}`;
      } catch (_) { /* architecture sync is best-effort */ }
    }
  } catch (err) {
    console.error(err);
    $('descText').textContent = '❌ Ошибка при выполнении анализа.';
  } finally {
    btn.textContent = '🚀 Запустить анализ';
    btn.disabled = false;
  }
}

function updateUI(result) {
  $('healthyCount').textContent = result.summary.healthy;
  $('warningCount').textContent = result.summary.warning;
  $('criticalCount').textContent = result.summary.critical;
  $('avgLatency').textContent = result.summary.avg_latency_ms;
  $('maxCpu').innerHTML = Math.round(result.summary.max_cpu_percent) + '<span class="unit">%</span>';
  $('totalRps').textContent = Math.round(result.summary.total_rps);
  $('descText').textContent = String(result.summary.description);
  $('lastUpdated').textContent = `🕐 ${new Date().toLocaleTimeString('ru-RU')}`;

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

async function loadArchitecture() {
  try {
    const res = await fetch('/api/architecture/view');
    archData = await res.json();
    renderArchitecture(archData, archNodeStatuses);
  } catch (e) {
    console.error('Failed to load architecture:', e);
  }
}

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

function showArchInfo(d, data) {
  selectedArchNode = d;
  const comp = data.components.find(c => c.id === d.id);
  if (!comp) return;
  const conns = data.edges.filter(e => e.source === d.id || e.target === d.id);
  const children = comp.children || [];
  const childrenNames = children.map(cid => {
    const c = data.components.find(n => n.id === cid);
    return c ? c.name : cid;
  }).join(', ');

  $('archInfoTitle').textContent = comp.name;
  let html = '<dl>';
  html += `<dt>Тип</dt><dd>${comp.type}</dd>`;
  if (comp.description) html += `<dt>Описание</dt><dd>${comp.description}</dd>`;
  if (childrenNames) html += `<dt>Включает</dt><dd>${childrenNames}</dd>`;
  html += `<dt>Связей</dt><dd>${conns.length}</dd>`;
  html += '</dl>';
  $('archInfoBody').innerHTML = html;
  $('archAnalyzeBtn').textContent = '⏳ Анализ...';
  $('archAnalyzeBtn').disabled = true;
  $('archInfo').style.display = 'block';

  // Auto-analyze this component
  setTimeout(() => runArchAnalysis(d.id, data), 100);
}

async function runArchAnalysis(componentId, data) {
  try {
    const scenarioName = selectedScenario || 'baseline';
    const scenarioParams = scenariosData[scenarioName] ? { ...scenariosData[scenarioName].params } : {};

    const res = await fetch('/api/architecture/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        component_id: componentId,
        scenario: scenarioName,
        params: scenarioParams,
      }),
    });
    const result = await res.json();
    archResult = result;

    // Update analysis tab with results
    currentResult = result.analysis;
    updateUI(result.analysis);

    // Re-render architecture with status overlay
    archNodeStatuses = result.node_statuses;
    renderArchitecture(data, archNodeStatuses);

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
    const res = await fetch('/api/architecture/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        component_id: '',
        scenario: scenarioName,
        params: scenarioParams,
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

// ── Init ──────────────────────────────────────────────────
loadScenarios();
$('analyzeBtn').addEventListener('click', analyze);
setTimeout(analyze, 400);

window.addEventListener('resize', () => {
  if (currentResult) buildGraph(currentResult);
  if (archData && document.querySelector('.tab[data-tab="architecture"].active')) {
    renderArchitecture(archData, archNodeStatuses);
  }
});
