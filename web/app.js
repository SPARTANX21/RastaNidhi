/* RastaNidhi dashboard – plain JS, no framework. Talks to the FastAPI server in server.py. */
'use strict';

// ------------------------------------------------------------------ state & utils
const TOKEN = sessionStorage.getItem('cp_token');
if (!TOKEN) location.href = '/#login';
let ME = null;
let LANG = sessionStorage.getItem('cp_lang') || 'English';
const view = document.getElementById('view');

let NAV_SEQ = 0;   // bumps on every navigation; stale page loads are dropped instead of overwriting the new page
class StaleNav extends Error { constructor() { super('stale'); this.stale = true; } }
async function api(path, opts = {}) {
  const seq = NAV_SEQ, isRead = !opts.method || opts.method === 'GET';
  const r = await fetch(path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + TOKEN, ...(opts.headers || {}) },
  });
  if (r.status === 401) { sessionStorage.removeItem('cp_token'); location.href = '/#login'; throw new Error('Signed out'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || ('Error ' + r.status));
  if (isRead && seq !== NAV_SEQ && !opts.keep) throw new StaleNav();
  return j;
}
const post = (p, body) => api(p, { method: 'POST', body: JSON.stringify(body || {}) });
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function inr(x) {
  if (x === null || x === undefined || isNaN(x)) return '–';
  const a = Math.abs(x);
  if (a >= 1e7) return '₹' + (x / 1e7).toFixed(2) + ' Cr';
  if (a >= 1e5) return '₹' + (x / 1e5).toFixed(1) + ' L';
  return '₹' + Math.round(x).toLocaleString('en-IN');
}
const pct = (x, d = 0) => (x === null || x === undefined) ? '–' : (x * 100).toFixed(d) + '%';
const num = (x, d = 0) => { d = typeof d === 'number' ? d : 0; return (x === null || x === undefined || isNaN(x)) ? '–' : Number(x).toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d }); };
const date = s => s ? String(s).slice(0, 10) : '–';
const yn = v => v === 'Y' ? '✅' : v === 'N' ? '❌' : esc(v);
const failed = v => v === 'Y' ? '<span class="badge b-High">failed</span>' : '<span class="badge b-Cleared">held</span>';
function toast(msg) { const t = document.getElementById('toast'); t.textContent = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 2600); }
function md(text) {  // tiny markdown → HTML for Claude output
  const lines = esc(text || '').split('\n');
  let html = '', list = null;
  const inline = s => s.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/_(.+?)_/g, '<i>$1</i>').replace(/`(.+?)`/g, '<code>$1</code>');
  for (const ln of lines) {
    const m = ln.match(/^\s*([-*•]|\d+\.)\s+(.*)/);
    if (m) { if (!list) { html += '<ul>'; list = true; } html += '<li>' + inline(m[2]) + '</li>'; continue; }
    if (list) { html += '</ul>'; list = null; }
    const h = ln.match(/^#{1,4}\s+(.*)/);
    if (h) html += '<h4>' + inline(h[1]) + '</h4>';
    else if (ln.startsWith('|')) html += '<div style="font-family:monospace;font-size:12px;white-space:pre">' + inline(ln) + '</div>';
    else if (ln.trim()) html += '<p>' + inline(ln) + '</p>';
  }
  return html + (list ? '</ul>' : '');
}
const kpi = (l, v, s = '', cls = '') => `<div class="kpi ${cls}"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${s}</div></div>`;
const gradeBadge = g => `<span class="grade g-${g}">${g}</span>`;
const prog = (v, max = 100) => `<span style="white-space:nowrap"><span class="prog"><i style="width:${Math.max(0, Math.min(100, v / max * 100))}%"></i></span> ${num(v)}</span>`;
const can = (...roles) => roles.includes(ME.role);

// ------------------------------------------------------------------ components
function bars(items, { label, value, fmt = num, cls = '', ref = null, max = null, highlight = null }) {
  const mx = max ?? Math.max(...items.map(i => +i[value] || 0), ref || 0, 1e-9);
  return '<div class="bars">' + items.map(i => {
    const v = +i[value] || 0;
    const c = typeof cls === 'function' ? cls(i) : cls;
    const lab = typeof label === 'function' ? label(i) : i[label];
    const hl = highlight && highlight(i) ? 'font-weight:700;color:#3d4280' : '';
    return `<div class="bar-row"><div class="lbl" style="${hl}" title="${esc(lab)}">${esc(lab)}</div>
      <div class="bar-track"><div class="bar-fill ${c}" style="width:${v / mx * 100}%"></div>
      ${ref ? `<div class="bar-line" style="left:${ref / mx * 100}%"></div>` : ''}</div>
      <div class="bar-val">${fmt(v)}</div></div>`;
  }).join('') + '</div>';
}
function stackBars(items, label, parts, fmt = num) {
  const mx = Math.max(...items.map(i => parts.reduce((s, p) => s + (+i[p.k] || 0), 0)), 1e-9);
  return '<div class="bars">' + items.map(i => {
    const tot = parts.reduce((s, p) => s + (+i[p.k] || 0), 0);
    return `<div class="bar-row"><div class="lbl" title="${esc(i[label])}">${esc(i[label])}</div><div class="bar-track">` +
      parts.map(p => `<div style="width:${(+i[p.k] || 0) / mx * 100}%;background:${p.color};height:100%" title="${p.name}: ${fmt(+i[p.k] || 0)}"></div>`).join('') +
      `</div><div class="bar-val">${fmt(tot)}</div></div>`;
  }).join('') + '</div><div class="legend">' + parts.map(p => `<span><i style="background:${p.color}"></i>${p.name}</span>`).join('') + '</div>';
}

/* Sortable, searchable table. cols: [{k, l, f?(v,row), num?}] */
function table(el, rows, cols, { onClick = null, rowClass = null, search = true, height = 520, empty = 'Nothing to show.' } = {}) {
  if (typeof el === 'string') el = document.getElementById(el);
  const st = { sort: null, dir: 1, q: '' };
  function render() {
    let r = rows;
    if (st.q) { const q = st.q.toLowerCase(); r = r.filter(x => cols.some(c => String(x[c.k] ?? '').toLowerCase().includes(q))); }
    if (st.sort) r = [...r].sort((a, b) => { const x = a[st.sort], y = b[st.sort]; return (x > y ? 1 : x < y ? -1 : 0) * st.dir; });
    el._rows = r;
    el.querySelector('.tbl-wrap').innerHTML = !r.length ? `<div class="loading">${empty}</div>` : `<table><thead><tr>${cols.map(c =>
      `<th data-k="${c.k}">${c.l}${st.sort === c.k ? (st.dir > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('')}</tr></thead><tbody>${r.slice(0, 1500).map((x, i) =>
      `<tr data-i="${i}" class="${onClick ? 'click' : ''} ${rowClass ? rowClass(x) : ''}">${cols.map(c =>
        `<td class="${c.num ? 'num' : ''}">${c.f ? c.f(x[c.k], x) : esc(x[c.k])}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    el.querySelector('.cnt').textContent = r.length.toLocaleString('en-IN') + ' rows';
  }
  el.innerHTML = `<div class="tbl-tools">${search ? '<input class="inp" placeholder="Search…" style="width:240px">' : '<span></span>'}
    <span><span class="muted cnt"></span> <button class="btn ghost small csv" title="Download these rows as CSV">⬇ Export</button></span></div>
    <div class="tbl-wrap" style="max-height:${height}px"></div>`;
  if (search) el.querySelector('input').oninput = e => { st.q = e.target.value; render(); };
  el.querySelector('.csv').onclick = ev => { ev.stopPropagation(); downloadCSV(el._rows, cols); };
  el.onclick = e => {
    const th = e.target.closest('th');
    if (th) { const k = th.dataset.k; st.dir = st.sort === k ? -st.dir : 1; st.sort = k; render(); return; }
    const tr = e.target.closest('tr[data-i]');
    if (tr && onClick) onClick(el._rows[+tr.dataset.i]);
  };
  render();
}

function downloadCSV(rows, cols) {
  const q = v => { const s = v === null || v === undefined ? '' : (typeof v === 'object' ? JSON.stringify(v) : String(v)); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const csv = [cols.map(c => q(c.l.replace(/<[^>]+>/g, ''))).join(','), ...rows.map(r => cols.map(c => q(r[c.k])).join(','))].join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' }));
  a.download = 'rastanidhi_' + (location.hash.slice(1) || 'export') + '.csv';
  a.click();
}

/* Bars (₹ lakh, left axis) + line (complaints, right axis) by month */
function comboChart(labels, barVals, lineVals, barName = 'Spend (₹ lakh)', lineName = 'Complaints') {
  const W = 620, H = 240, p = 38, n = labels.length, bw = (W - 2 * p) / n;
  const mb = Math.max(...barVals, 1) * 1.15, ml = Math.max(...lineVals, 1) * 1.15;
  const yb = v => H - p - v / mb * (H - 2 * p), yl = v => H - p - v / ml * (H - 2 * p), xc = i => p + bw * i + bw / 2;
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%">
    ${[0, .5, 1].map(t => `<line x1="${p}" x2="${W - p}" y1="${yb(mb * t / 1.15)}" y2="${yb(mb * t / 1.15)}" stroke="#f1f5f9"/>
      <text x="4" y="${yb(mb * t / 1.15) + 4}" font-size="10" fill="#94a3b8">${Math.round(mb * t / 1.15)}</text>
      <text x="${W - 4}" y="${yl(ml * t / 1.15) + 4}" font-size="10" fill="#dc2626" text-anchor="end">${Math.round(ml * t / 1.15)}</text>`).join('')}
    ${barVals.map((v, i) => `<rect x="${xc(i) - bw * .3}" y="${yb(v)}" width="${bw * .6}" height="${H - p - yb(v)}" rx="4" fill="#b9bde6"><title>${labels[i]}: ₹${v} L</title></rect>`).join('')}
    <polyline fill="none" stroke="#dc2626" stroke-width="2.5" points="${lineVals.map((v, i) => xc(i) + ',' + yl(v)).join(' ')}"/>
    ${lineVals.map((v, i) => `<circle cx="${xc(i)}" cy="${yl(v)}" r="3.5" fill="#dc2626"><title>${labels[i]}: ${v} complaints</title></circle>`).join('')}
    ${labels.map((l, i) => `<text x="${xc(i)}" y="${H - 12}" font-size="11" fill="#64748b" text-anchor="middle">${esc(l)}</text>`).join('')}
  </svg><div class="legend"><span><i style="background:#b9bde6"></i>${barName}</span><span><i style="background:#dc2626"></i>${lineName}</span></div>`;
}

function donut(items, colors, total = null, center = 'total') {
  const tot = items.reduce((s, i) => s + i.value, 0) || 1, R = 70, r = 44, c = 90, shown = total ?? tot;
  let a0 = -Math.PI / 2;
  const arcs = items.map((it, k) => {
    const a1 = a0 + it.value / tot * Math.PI * 2, big = a1 - a0 > Math.PI ? 1 : 0;
    const P = (rad, a) => [c + rad * Math.cos(a), c + rad * Math.sin(a)];
    const [x0, y0] = P(R, a0), [x1, y1] = P(R, a1), [x2, y2] = P(r, a1), [x3, y3] = P(r, a0);
    const d = `M${x0},${y0}A${R},${R} 0 ${big} 1 ${x1},${y1}L${x2},${y2}A${r},${r} 0 ${big} 0 ${x3},${y3}Z`;
    a0 = a1;
    return `<path d="${d}" fill="${colors[k]}"><title>${esc(it.label)}: ${num(it.value)}</title></path>`;
  }).join('');
  return `<div class="donut-wrap"><svg viewBox="0 0 180 180" style="width:180px">${arcs}<text x="90" y="88" text-anchor="middle" font-size="20" font-weight="700" fill="#0f172a">${num(shown)}</text>
    <text x="90" y="106" text-anchor="middle" font-size="10" fill="#64748b">${esc(center)}</text></svg>
    <div class="legend" style="flex-direction:column;gap:6px">${items.map((it, k) => `<span><i style="background:${colors[k]}"></i>${esc(it.label)}: <b>${num(it.value)}</b> (${pct(it.value / shown)})</span>`).join('')}</div></div>`;
}

const alertRow = a => `<div class="alert-item"><div class="alert-icn ${a.severity}">${a.severity === 'critical' ? '🚨' : a.severity === 'warning' ? '⚠️' : 'ℹ️'}</div>
  <div style="flex:1"><div class="alert-title">${esc(a.title)}</div><div class="alert-detail">${esc(a.detail)}</div></div>
  <span class="sev ${a.severity}">${a.severity}</span>${a.page ? `<button class="btn ghost small" onclick="alertGo(${esc(JSON.stringify(a))})">Open →</button>` : ''}</div>`;
function alertGo(a) {
  if (a.wo) return openWO(a.wo);
  if (a.ward) WARD_SEL = a.ward;
  const target = NAV_KEYS().includes(a.page) ? a.page : NAV_KEYS()[0];
  go(target);
}

function choropleth(geo, values, fmt, onClick) {
  const pts = geo.features.flatMap(f => f.geometry.coordinates[0]);
  const lons = pts.map(p => p[0]), lats = pts.map(p => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...lons), Math.max(...lons), Math.min(...lats), Math.max(...lats)];
  const k = Math.cos(19.07 * Math.PI / 180), W = 520, sc = W / ((x1 - x0) * k), H = (y1 - y0) * sc;
  const P = ([lon, lat]) => [((lon - x0) * k * sc).toFixed(1), ((y1 - lat) * sc).toFixed(1)];
  const vals = Object.values(values).filter(v => v !== null);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const stops = [[255, 247, 237], [253, 186, 116], [234, 88, 12], [127, 29, 29]];
  const color = v => {
    if (v === null || v === undefined) return '#e2e8f0';
    const t = hi > lo ? (v - lo) / (hi - lo) : 0.5, s = Math.min(2.999, t * 3), i = Math.floor(s), f = s - i;
    const c = stops[i].map((a, j) => Math.round(a + (stops[i + 1][j] - a) * f));
    return `rgb(${c})`;
  };
  window._mapClick = onClick;
  const paths = geo.features.map(f => {
    const w = f.properties.ward_code, ring = f.geometry.coordinates[0];
    const cx = ring.reduce((s, p) => s + p[0], 0) / ring.length, cy = ring.reduce((s, p) => s + p[1], 0) / ring.length;
    const [tx, ty] = P([cx, cy]);
    return `<path d="M${ring.map(P).join('L')}Z" fill="${color(values[w])}" onclick="_mapClick && _mapClick('${w}')">
      <title>${w} – ${esc(f.properties.ward_name)}: ${fmt(values[w])}</title></path><text x="${tx}" y="${ty}" text-anchor="middle">${w}</text>`;
  }).join('');
  return `<div class="map"><svg viewBox="0 0 ${W} ${H.toFixed(0)}">${paths}</svg></div>
    <div class="scale"><span>${fmt(lo)}</span><div class="grad"></div><span>${fmt(hi)}</span></div>`;
}

function lineChart(series, xlabels, h = 220) {
  const W = 640, pad = 34, all = series.flatMap(s => s.values), mx = Math.max(...all, 1) * 1.1;
  const X = i => pad + i * (W - 2 * pad) / Math.max(1, xlabels.length - 1), Y = v => h - pad - v / mx * (h - 2 * pad);
  const grid = [0, .25, .5, .75, 1].map(t => `<line x1="${pad}" x2="${W - pad}" y1="${Y(mx * t / 1.1)}" y2="${Y(mx * t / 1.1)}" stroke="#f1f5f9"/>
    <text x="4" y="${Y(mx * t / 1.1) + 4}" font-size="10" fill="#94a3b8">${Math.round(mx * t / 1.1)}</text>`).join('');
  const lines = series.map(s => `<polyline fill="none" stroke="${s.color}" stroke-width="2.5" points="${s.values.map((v, i) => X(i) + ',' + Y(v)).join(' ')}"/>` +
    s.values.map((v, i) => `<circle cx="${X(i)}" cy="${Y(v)}" r="3.5" fill="${s.color}"><title>${s.name}: ${Math.round(v)}</title></circle>`).join('')).join('');
  const xl = xlabels.map((l, i) => `<text x="${X(i)}" y="${h - 10}" font-size="10" fill="#64748b" text-anchor="middle">${esc(l)}</text>`).join('');
  return `<svg viewBox="0 0 ${W} ${h}" style="width:100%">${grid}${lines}${xl}</svg><div class="legend">${series.map(s => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join('')}</div>`;
}

function scatter(points, xl, yl) {
  const W = 560, H = 360, p = 44, X = v => p + v / 100 * (W - 2 * p), Y = v => H - p - v / 100 * (H - 2 * p);
  const colors = { A: '#059669', B: '#65a30d', C: '#d97706', D: '#ea580c', E: '#dc2626' };
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%">
    <rect x="${p}" y="${p}" width="${W - 2 * p}" height="${H - 2 * p}" fill="#f8fafc" stroke="#e2e8f0"/>
    <line x1="${X(50)}" x2="${X(50)}" y1="${p}" y2="${H - p}" stroke="#e2e8f0" stroke-dasharray="4"/>
    <line y1="${Y(50)}" y2="${Y(50)}" x1="${p}" x2="${W - p}" stroke="#e2e8f0" stroke-dasharray="4"/>
    <text x="${W / 2}" y="${H - 8}" text-anchor="middle" font-size="11" fill="#64748b">${xl} →</text>
    <text x="12" y="${H / 2}" font-size="11" fill="#64748b" transform="rotate(-90 12 ${H / 2})" text-anchor="middle">${yl} →</text>
    ${points.map(pt => `<circle cx="${X(pt.x)}" cy="${Y(pt.y)}" r="${pt.r}" fill="${colors[pt.g]}" fill-opacity=".75" stroke="#fff"><title>${esc(pt.label)}</title></circle>
      <text x="${X(pt.x)}" y="${Y(pt.y) - pt.r - 4}" font-size="10" text-anchor="middle" fill="#0f172a">${esc(pt.label.replace(' (synthetic)', ''))}</text>`).join('')}
  </svg>`;
}

/* Button that asks the server for a Claude narrative and shows it below */
function claudeBox(label, url) {
  const id = 'ai' + Math.random().toString(36).slice(2, 8);
  setTimeout(() => {
    document.getElementById(id + 'b').onclick = async e => {
      const out = document.getElementById(id);
      e.target.disabled = true; e.target.textContent = 'Claude is writing…';
      try {
        const u = url + (url.includes('?') ? '&' : '?') + 'lang=' + encodeURIComponent(LANG);
        const r = await post(u);
        out.innerHTML = r.text ? `<div class="ai">${md(r.text)}</div>` : `<div class="note">${esc(r.error)}</div>`;
      } catch (err) { out.innerHTML = `<div class="note">${esc(err.message)}</div>`; }
      e.target.disabled = false; e.target.textContent = '✨ ' + label;
    };
  });
  return `<button class="btn claude" id="${id}b">✨ ${label}</button><div id="${id}"></div>`;
}

function wardPicker(id, current, onChange) {
  setTimeout(() => { const s = document.getElementById(id); if (s) s.onchange = () => onChange(s.value); });
  return `<label class="f">Ward<select class="sel" id="${id}">${OPTIONS.wards.map(w =>
    `<option value="${w.ward_code}" ${w.ward_code === current ? 'selected' : ''}>${w.ward_code} – ${esc(w.ward_name)}</option>`).join('')}</select></label>`;
}

// ------------------------------------------------------------------ modal: work order
function openModal(html) { document.getElementById('modal').innerHTML = html; document.getElementById('modal-bg').classList.add('open'); }
function closeModal() { document.getElementById('modal-bg').classList.remove('open'); }

async function openWO(id) {
  openModal('<div class="loading">Loading work order…</div>');
  let d;
  try { d = await api('/api/workorder/' + id); } catch (e) { openModal(`<div class="note">${esc(e.message)}</div>`); return; }
  const w = d.wo;
  const trail = [...d.reviews.map(r => ({ ...r, kind: 'review' })), ...d.evidence.map(r => ({ ...r, kind: 'evidence' }))]
    .sort((a, b) => a.at < b.at ? -1 : 1);
  openModal(`
    <div class="page-title">${esc(w.work_order_id)} · ${esc(w.road_name)}</div>
    <div class="page-sub">${esc(w.work_type)} · ${esc(w.repair_method)} · ${esc(w.contractor_name)} · ward ${esc(w.ward_code)}</div>
    <div class="grid2">
      <div class="card"><h3>Bill & timeline</h3><div class="kv">
        <div>Billed</div><div><b>${inr(w.cost_inr)}</b> (rate card ${inr(w.expected_cost_inr)} → ${num(w.cost_ratio, 2)}×)</div>
        <div>Area</div><div>${num(w.area_sqm, 1)} sqm</div>
        <div>Assigned</div><div>${esc(String(w.assigned_at).replace('T', ' ').slice(0, 16))}</div>
        <div>Completed</div><div>${esc(String(w.completed_at).replace('T', ' ').slice(0, 16))}</div>
        <div>SLA</div><div>${w.sla_hours} h target · ${w.hours_to_fix ? num(w.hours_to_fix) + ' h taken' : 'no complaint linked'} · ${yn(w.sla_met)}</div>
        <div>Fix held?</div><div>${failed(w.reopened_within_30d)}</div>
        <div>Road under DLP</div><div>${w.under_dlp === 'Y' ? '⚠️ Yes – resurfaced ' + date(w.last_resurfaced) : 'No'}</div>
        <div>Complaints</div><div>${esc(w.linked_complaint_ids || 'none linked')}</div>
        <div>Engineer remark</div><div>${esc(w.engineer_remark)}</div>
      </div></div>
      <div class="card"><h3>Audit flags</h3>${d.flags.length ? d.flags.map(f =>
        `<p style="margin-bottom:8px"><span class="badge ${f.category === 'Performance' ? 'b-Low' : 'b-High'}">${esc(f.rule)}</span> ${esc(f.reason)}</p>`).join('') :
        '<p class="muted">No flags on this job.</p>'}
        ${can('Admin', 'Ward Officer', 'Auditor / Verifier') && d.flags.some(f => f.category !== 'Performance') ?
          `<button class="btn ghost small" onclick="draftNotice('workorder','${w.work_order_id}')">📨 Draft recovery notice</button>` : ''}
        <h3 style="margin-top:16px">Review & evidence trail</h3>
        ${trail.length ? '<div class="timeline">' + trail.map(t => `<div><div class="t">${esc(t.at.replace('T', ' '))} · ${esc(t.by)}${t.role ? ' (' + esc(t.role) + ')' : ''}</div>
          ${t.kind === 'review' ? `<span class="badge b-${t.status.split(' ')[0]}">${esc(t.status)}</span> ` : '📎 '}${esc(t.note)}</div>`).join('') + '</div>' :
          '<p class="muted">No reviews or evidence yet.</p>'}
        ${can('Admin', 'Auditor / Verifier') ? `<div style="margin-top:14px"><label class="f">Auditor decision
          <select class="sel" id="rv-status"><option>Verified – recover money</option><option>Cleared – explained</option><option>Evidence requested</option><option>Escalated</option><option>Pending</option></select></label>
          <textarea class="inp" id="rv-note" placeholder="Note (e.g. measurement book checked)" style="margin-top:8px"></textarea>
          <button class="btn" style="margin-top:8px" onclick="saveReview('${w.work_order_id}')">Save decision</button></div>` : ''}
        ${can('Contractor', 'Ward Officer', 'Admin') ? `<div style="margin-top:14px"><label class="f">${ME.role === 'Contractor' ? 'Submit evidence / explanation' : 'Add a note for the auditor'}
          <textarea class="inp" id="ev-note" placeholder="e.g. DLP contractor refused; measurement book page 42 attached"></textarea></label>
          <button class="btn ghost" style="margin-top:8px" onclick="saveEvidence('${w.work_order_id}')">Submit</button></div>` : ''}
      </div>
    </div>
    <div class="card"><h3>Every job on this road (${d.same_road.length})</h3><div id="wo-same"></div></div>`);
  table('wo-same', d.same_road, [
    { k: 'work_order_id', l: 'Work order', f: (v) => v === w.work_order_id ? `<b>${v}</b>` : v },
    { k: 'assigned_at', l: 'Assigned', f: v => esc(String(v).replace('T', ' ').slice(0, 16)) },
    { k: 'repair_method', l: 'Method' }, { k: 'contractor_name', l: 'Contractor' },
    { k: 'cost_inr', l: 'Cost', num: true, f: inr }, { k: 'linked_complaint_ids', l: 'Complaints', f: v => v ? esc(v) : '<span class="badge b-High">none</span>' },
  ], { search: false, height: 260 });
}

/* ---------- contractor infographics (replace the old speed-vs-durability scatter) ---------- */
function wilson(k, n, z = 1.96) {   // 95% Wilson score interval for a proportion
  if (!n) return [0, 0];
  const p = k / n, d = 1 + z * z / n, c = p + z * z / (2 * n), m = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n));
  return [Math.max(0, (c - m) / d), Math.min(1, (c + m) / d)];
}
function dumbbell(c, isCon) {
  const rows = c.map(x => { const [lo, hi] = wilson(x.reopens, x.jobs);
    const verdict = lo > x.exp_reopen_rate ? 'worse' : hi < x.exp_reopen_rate ? 'better' : 'normal';
    return { ...x, lo, hi, verdict }; }).sort((a, b) => (b.reopen_rate - b.exp_reopen_rate) - (a.reopen_rate - a.exp_reopen_rate));
  const mx = Math.max(...rows.map(r => r.hi), ...rows.map(r => r.exp_reopen_rate)) * 1.08;
  const X = v => (v / mx * 100).toFixed(2) + '%';
  const col = { worse: '#d64545', better: '#1d7a48', normal: '#3d4280' };
  const lbl = { worse: 'Worse than expected', better: 'Better than expected', normal: 'Within normal range' };
  const ticks = [0, .1, .2, .3, .4, .5].filter(t => t <= mx);
  return `<div class="db">
    <div class="db-axis"><span></span><div class="db-scale">${ticks.map(t => `<i style="left:${X(t)}">${Math.round(t * 100)}%</i>`).join('')}</div><span></span></div>
    ${rows.map(r => `<div class="db-row ${isCon && r.contractor_id === ME.contractor_id ? 'me' : ''}" title="${esc(r.contractor_name)}: ${r.reopens} of ${r.jobs} fixes failed (${pct(r.reopen_rate)}); 95% range ${pct(r.lo)}–${pct(r.hi)}; expected ${pct(r.exp_reopen_rate)} for this job mix">
      <div class="db-name"><span class="grade g-${r.grade}" style="width:20px;height:20px;font-size:11px">${r.grade}</span> ${esc(r.contractor_name.replace(' (synthetic)', ''))}<small>${r.jobs} jobs</small></div>
      <div class="db-track">${ticks.map(t => `<b style="left:${X(t)}"></b>`).join('')}
        <div class="db-ci" style="left:${X(r.lo)};width:calc(${X(r.hi)} - ${X(r.lo)});background:${col[r.verdict]}22;border-color:${col[r.verdict]}55"></div>
        <div class="db-link" style="left:${X(Math.min(r.reopen_rate, r.exp_reopen_rate))};width:calc(${X(Math.max(r.reopen_rate, r.exp_reopen_rate))} - ${X(Math.min(r.reopen_rate, r.exp_reopen_rate))});background:${col[r.verdict]}"></div>
        <div class="db-exp" style="left:${X(r.exp_reopen_rate)}"></div>
        <div class="db-obs" style="left:${X(r.reopen_rate)};background:${col[r.verdict]}"></div></div>
      <div class="db-verdict" style="color:${col[r.verdict]}">${pct(r.reopen_rate)} <span>vs ${pct(r.exp_reopen_rate)}</span><em>${lbl[r.verdict]}</em></div></div>`).join('')}
    <div class="legend" style="margin-top:12px"><span><i class="db-key exp"></i>Expected for their job mix (work type × flood-prone ward × rain after the fix)</span>
      <span><i class="db-key obs"></i>Actual re-open rate</span><span><i class="db-key ci"></i>95% confidence band (wider = fewer jobs)</span></div>
    <p class="muted" style="margin-top:6px">A contractor is only called better or worse when the whole band clears the expected mark, so small samples and bad luck don't decide a verdict. Hover a row for the counts.</p></div>`;
}
function gradeStack(c, isCon) {
  const rows = [...c].sort((a, b) => b.overall_score - a.overall_score).map(x => ({ ...x, lbl: x.contractor_name.replace(' (synthetic)', ''),
    d: x.durability_score * .4, s: x.speed_score * .3, k: x.cost_score * .3 }));
  return `<div class="gs">${rows.map(r => `<div class="gs-row ${isCon && r.contractor_id === ME.contractor_id ? 'me' : ''}">
      <div class="gs-name"><span class="grade g-${r.grade}" style="width:20px;height:20px;font-size:11px">${r.grade}</span> ${esc(r.lbl)}</div>
      <div class="gs-bar"><i style="width:${r.d}%;background:#3d4280" title="Durability ${num(r.durability_score)}/100 × 40%"></i><i style="width:${r.s}%;background:#8b90cf" title="Speed ${num(r.speed_score)}/100 × 30%"></i><i style="width:${r.k}%;background:#c9cbe9" title="Cost ${num(r.cost_score)}/100 × 30%"></i>
        ${[35, 50, 65, 80].map(g => `<b style="left:${g}%"></b>`).join('')}</div>
      <div class="gs-val">${num(r.overall_score)}</div></div>`).join('')}
    <div class="legend"><span><i style="background:#3d4280"></i>Durability (40%)</span><span><i style="background:#8b90cf"></i>Speed (30%)</span><span><i style="background:#c9cbe9"></i>Cost integrity (30%)</span></div>
    <p class="muted" style="margin-top:4px">Dashed lines mark the grade cut-offs: D at 35 · C at 50 · B at 65 · A at 80. Hover a segment for its score.</p></div>`;
}
/* Recovery notice (from the Ward Officer prototype): draft → copy → record as issued */
async function draftNotice(kind, id) {
  openModal('<div class="loading">Drafting notice…</div>');
  try {
    const r = await post(`/api/notice/${kind}/${id}`);
    openModal(`<div class="page-title">📨 Draft recovery notice: ${kind === 'road' ? 'DLP road' : 'flagged work order'} ${esc(id)}</div>
      <div class="page-sub">Generated from the audit evidence. Review it before sending. Recording it as issued adds it to the audit trail that the auditor and contractor see.</div>
      <div class="notice-text" id="notice-text">${esc(r.text)}</div>
      <div class="row" style="margin-top:14px">
        <button class="btn ghost" onclick="navigator.clipboard.writeText(document.getElementById('notice-text').innerText).then(()=>toast('Copied to clipboard'))">📋 Copy</button>
        <button class="btn" onclick="issueNotice('${kind}','${id}')">✅ Record as issued</button>
        ${kind === 'workorder' ? `<button class="btn ghost" onclick="openWO('${id}')">← Back to work order</button>` : ''}
      </div>`);
  } catch (e) { openModal(`<div class="note error">${esc(e.message)}</div>`); }
}
async function issueNotice(kind, id) {
  try { await post(`/api/notice/${kind}/${id}?issue=true`); toast('Notice recorded as issued'); kind === 'workorder' ? openWO(id) : closeModal(); refreshBadges(); }
  catch (e) { toast(e.message); }
}

async function saveReview(id) {
  try { await post(`/api/workorder/${id}/review`, { status: document.getElementById('rv-status').value, note: document.getElementById('rv-note').value });
    toast('Decision saved'); openWO(id); refreshBadges(); } catch (e) { toast(e.message); }
}
async function saveEvidence(id) {
  try { await post(`/api/workorder/${id}/evidence`, { note: document.getElementById('ev-note').value }); toast('Submitted'); openWO(id); } catch (e) { toast(e.message); }
}

// ------------------------------------------------------------------ views
const V = {};

V.overview = async () => {
  const d = await api('/api/city');
  const k = d.kpis;
  const metrics = { budget_used_pct: ['Budget used %', v => num(v) + '%'], money_at_risk_inr: ['Money needing review', inr],
    reopen_rate: ['Re-open rate', pct], open_complaints: ['Open complaints', num], failed_fix_spend_inr: ['Failed-fix spend', inr] };
  view.innerHTML = pageHero('mumbai-marine-drive.jpg', 'Mumbai · 24 wards · monsoon 2025', 'Every rupee from ward budget to road repair', 'A.Savin, FAL') + `<div class="page-title">Where did Mumbai's monsoon road money go?</div>
    <div class="page-sub">All 24 wards, June–October 2025. Click a ward on the map to open its money trail.</div>
    <div class="kpis">${kpi('Spent', inr(k.spend), 'of ' + inr(k.budget) + ' budget')}${kpi('Work orders', num(k.work_orders), pct(k.sla_rate) + ' met SLA')}
      ${kpi('Spent on fixes that failed ≤30d', inr(k.failed_spend), pct(k.reopen_rate) + ' re-opened', 'warn')}
      ${kpi('Money needing review', inr(k.at_risk), k.at_risk_wos + ' work orders', 'warn')}${kpi('Never-fixed issues', num(k.never_fixed), 'open, no work order')}</div>
    <div class="grid2"><div class="card"><h3>Spend vs complaint volume, by month</h3>${comboChart(d.trend.labels, d.trend.spend_lakh, d.trend.complaints)}</div>
      <div class="card"><h3>Flag breakdown <span class="muted">suspicious-billing rules</span></h3>${donut(d.flag_breakdown.map(f => ({ ...f, label: { OVERBILLED: 'Over-billed', DOUBLE_BILLED: 'Double-billed', DLP_PAID: 'Paid on DLP road', Clean: 'No billing flag' }[f.label] || f.label })), ['#d97706', '#3d4280', '#dc2626', '#cbd5e1'], k.work_orders, 'work orders')}
        <p class="muted">A job can carry more than one flag, so the slices add up to slightly more than the total.</p>
        <h3 style="margin-top:16px">Contractor fair score</h3>${bars(d.contractors, { label: c => c.grade + ' · ' + c.contractor_name.replace(' (synthetic)', ''), value: 'overall_score', fmt: v => num(v) + '/100',
          cls: c => c.grade >= 'D' ? 'red' : '' })}</div></div>
    ${d.alerts && d.alerts.length ? `<div class="card"><h3>Top alerts right now ${NAV_KEYS().includes('alerts') ? '<button class="btn ghost small" onclick="go(\'alerts\')">View all →</button>' : ''}</h3>${d.alerts.map(alertRow).join('')}</div>` : ''}
    <div class="card"><h3>Ward map <span><span class="muted">hover for a quick look · click a ward for details · scroll to zoom</span>
      <button class="btn ghost small" onclick="go('map')">⛶ Open full map</button></span></h3><div id="map"></div></div>
    <div class="grid2"><div class="card"><h3>Budget used by ward <span class="muted">dashed line = 100%</span></h3>${bars([...d.wards].sort((a, b) => b.budget_used_pct - a.budget_used_pct),
        { label: w => w.ward_code + ' · ' + w.ward_name, value: 'budget_used_pct', fmt: v => num(v) + '%', ref: 100, cls: w => w.budget_used_pct > 100 ? 'red' : '' })}</div>
      <div class="card"><h3>What the audit found</h3><div id="sum"></div></div></div>`;
  const mapHost = document.getElementById('map');
  WardMap(mapHost, { height: 540 });
  table('sum', d.audit_summary, [{ k: 'category', l: 'Category' }, { k: 'rule', l: 'Rule' }, { k: 'meaning', l: 'Meaning' },
    { k: 'work_orders', l: 'Work orders', num: true, f: num }, { k: 'amount', l: 'Amount', num: true, f: inr }], { search: false });
};

let WARD_SEL = null;
V.ward = async () => {
  const fixed = ME.role === 'Ward Officer';
  const code = fixed ? ME.ward : (WARD_SEL || ME.ward || 'L');
  const d = await api('/api/ward/' + code);
  const w = d.ward, x = d.extras;
  const over = w.budget_used_pct > 100;
  view.innerHTML = `<div class="row" style="justify-content:space-between"><div><div class="page-title">Ward ${esc(code)}: ${esc(w.ward_name)}</div>
      <div class="page-sub">${ME.role === 'Citizen' ? 'Where your ward\'s monsoon road money went, and whether the repairs lasted.' : 'Money trail for the monsoon season.'}</div></div>
      ${fixed ? '' : wardPicker('wp', code, v => { WARD_SEL = v; go('ward'); })}</div>
    ${fixed ? '' : '<div class="card"><h3>Pick a ward on the map <span class="muted">click any ward to switch</span></h3><div id="ward-mini"></div></div>'}
    <div class="kpis">${kpi('Budget', inr(w.monsoon_repair_budget_inr_2025))}${kpi('Spent', inr(w.spend_inr), num(w.budget_used_pct) + '% used', over ? 'warn' : '')}
      ${kpi('Spent on failed fixes', inr(w.failed_fix_spend_inr), pct(w.reopen_rate) + ' re-opened', 'warn')}${kpi('Needs review', inr(w.money_at_risk_inr))}
      ${kpi('SLA met', pct(w.sla_rate), 'low-lying index ' + w.low_lying_index)}${kpi('Open complaints', num(w.open_complaints), x ? 'avg age ' + x.avg_open_age_days + ' days' : '')}</div>
    ${x ? `${over ? `<div class="banner warn"><b>${esc(code)} has no budget headroom left.</b> It has spent ${num(w.budget_used_pct)}% of its monsoon budget (${inr(-w.remaining_budget_inr)} over).
        Recover money from the DLP roads and flagged work orders below before raising new work orders.</div>`
      : `<div class="banner ok">${esc(code)} has <b>${inr(w.remaining_budget_inr)}</b> of headroom left this season. See the Next-rupee planner for where it should go.</div>`}
      <div class="card"><div class="row" style="justify-content:space-between;margin:0"><b>Budget utilisation</b><span class="muted">${inr(w.spend_inr)} spent of ${inr(w.monsoon_repair_budget_inr_2025)}</span></div>
        <div class="util-bar" style="margin-top:8px"><i class="${over ? 'over' : w.budget_used_pct > 90 ? 'warn' : ''}" style="width:${Math.min(100, w.budget_used_pct)}%"></i></div></div>
      <div class="grid2"><div class="card"><h3>Spend vs complaints, by month</h3>${comboChart(x.trend.labels, x.trend.spend_lakh, x.trend.complaints)}</div>
        <div class="card"><h3>Where this ward ranks <span class="muted">budget used vs the other 23 wards</span></h3>${bars(x.rank, { label: 'ward_code', value: 'budget_used_pct', fmt: v => num(v) + '%', ref: 100,
          cls: r => r.ward_code === code ? '' : r.budget_used_pct > 100 ? 'red' : 'alt', highlight: r => r.ward_code === code })}</div></div>
      <div class="grid2"><div class="card"><h3>Top unresolved complaints <span class="muted">most upvoted, still open</span></h3>${x.top_unresolved.length ? x.top_unresolved.map(c => `
          <div class="alert-item"><div class="alert-icn warning">📣</div><div style="flex:1"><div class="alert-title">${esc(c.category_reported)}: ${esc(c.locality_text)}</div>
          <div class="alert-detail">${esc(String(c.description).slice(0, 150))}</div><div class="muted">${esc(c.complaint_id)} · ${esc(c.channel)} · ${esc(c.status)}</div></div>
          <div style="text-align:right"><span class="sev warning">${c.upvotes} upvotes</span><div class="muted" style="margin-top:4px">${c.age_days} days old</div></div></div>`).join('')
          : '<p class="muted">No open complaints right now.</p>'}</div>
        <div class="card"><h3>Recovery: DLP roads BMC paid for <span class="muted">the original contractor owes these fixes</span></h3>${x.recovery_roads.length ? x.recovery_roads.map(r => `
          <div class="plan-item"><div class="plan-rank">₹</div><div style="flex:1"><div class="alert-title">${esc(r.road_name)} <span class="muted">· ${r.road_id} · ${esc(r.surface)}</span></div>
          <div class="alert-detail">Resurfaced ${date(r.last_resurfaced)}, still under DLP. BMC paid for ${num(r.dlp_jobs)} repair(s) worth <b>${inr(r.dlp_paid_inr)}</b>.</div>
          <div class="why-tags">${r.accidents ? `<span class="why-tag">${r.accidents} road-condition accidents</span>` : ''}${r.critical_access ? '<span class="why-tag">hospital/ambulance route</span>' : ''}<span class="why-tag">risk ${num(r.risk_score)}</span></div></div>
          ${can('Admin', 'Ward Officer', 'Auditor / Verifier') ? `<button class="btn small" style="background:#dc2626" onclick="draftNotice('road','${r.road_id}')">Draft notice</button>` : ''}</div>`).join('')
          : '<p class="muted">No DLP payments recorded in this ward.</p>'}</div></div>` : ''}
    ${ME.role === 'Citizen' ? `<div class="info">In ${esc(code)}, BMC spent <b>${inr(w.spend_inr)}</b> on ${num(w.jobs)} monsoon road jobs (${num(w.budget_used_pct)}% of the budget).
      ${pct(w.reopen_rate)} of repairs failed within a month, costing ${inr(w.failed_fix_spend_inr)}. The biggest contractor here was ${esc(w.top_contractor)}.</div>` : ''}
    <div class="grid2"><div class="card"><h3>By contractor</h3>${bars(d.by_contractor, { label: 'contractor_name', value: 'spend_inr', fmt: inr })}
        <div id="t-con" style="margin-top:14px"></div></div>
      <div class="card"><h3>By repair method: held vs failed</h3>${stackBars(d.by_method.map(m => ({ ...m, held: m.spend_inr - m.failed_spend_inr })), 'repair_method',
        [{ k: 'held', name: 'Held', color: '#3d4280' }, { k: 'failed_spend_inr', name: 'Failed within 30 days', color: '#dc2626' }], inr)}
        <h3 style="margin-top:18px">Spend by month</h3>${bars(d.by_month, { label: 'month', value: 'cost_inr', fmt: inr, cls: 'alt' })}</div></div>
    ${can('Admin', 'Ward Officer', 'Researcher') ? `<div class="card"><h3>📝 One-page report for the corporator</h3>${claudeBox('Write ward report', '/api/claude/ward/' + code)}</div>` : ''}
    ${d.work_orders ? `<div class="card"><h3>All ${d.work_orders.length} work orders <span class="muted">click a row for details</span></h3><div id="t-wo"></div></div>` : ''}`;
  if (!fixed) WardMap(document.getElementById('ward-mini'), { height: 320, compact: true, initial: code, onSelect: c => { WARD_SEL = c; go('ward'); } });
  table('t-con', x ? x.contractors : d.by_contractor, [{ k: 'contractor_name', l: 'Contractor', f: v => esc(String(v).replace(' (synthetic)', '')) }, { k: 'jobs', l: 'Jobs', num: true },
    { k: 'spend_inr', l: 'Spend', num: true, f: inr }, { k: 'reopen_rate', l: 'Re-open', num: true, f: v => pct(v) }, { k: 'sla_rate', l: 'SLA met', num: true, f: v => pct(v) },
    ...(x ? [{ k: 'overbilled', l: 'Over-billed', num: true }, { k: 'double_billed', l: 'Double', num: true }, { k: 'dlp_paid', l: 'DLP', num: true },
      { k: 'needs_review_inr', l: 'Needs review', num: true, f: inr }] : [])], { search: false, height: 300 });
  if (d.work_orders) table('t-wo', d.work_orders, [
    { k: 'work_order_id', l: 'Work order' }, { k: 'completed_at', l: 'Completed', f: date }, { k: 'road_name', l: 'Road' },
    { k: 'repair_method', l: 'Method' }, { k: 'contractor_name', l: 'Contractor' }, { k: 'cost_inr', l: 'Cost', num: true, f: inr },
    { k: 'cost_ratio', l: '× rate', num: true, f: v => `<span style="color:${v > 1.4 ? '#dc2626' : 'inherit'}">${num(v, 2)}</span>` },
    { k: 'sla_met', l: 'SLA', f: yn }, { k: 'reopened_within_30d', l: 'Held?', f: failed }],
    { onClick: can('Admin', 'Ward Officer', 'Auditor / Verifier') ? r => openWO(r.work_order_id) : null });
};

let AUDIT_F = { category: 'Suspicious billing', rule: '', ward: '', contractor: '', status: '' };
V.audit = async () => {
  const f = AUDIT_F;
  if (WARD_SEL && ME.role === 'Auditor / Verifier') { f.ward = WARD_SEL; WARD_SEL = null; }
  const q = new URLSearchParams(Object.entries({ category: f.category, rule: f.rule, ward: f.ward, contractor: f.contractor }).filter(([, v]) => v)).toString();
  const d = await api('/api/flags?' + q);
  let rows = d.rows;
  if (f.status) rows = rows.filter(r => r.review_status.startsWith(f.status));
  const title = { Contractor: 'My audit flags & evidence', 'Ward Officer': `Audit flags in ward ${ME.ward}`, 'Auditor / Verifier': 'Audit queue' }[ME.role] || 'Repair auditor';
  const sub = ME.role === 'Contractor' ? 'These are jobs of yours that the rules flagged. Open one and submit an explanation or evidence. An auditor will review it.'
    : 'Rule-based flags. Every flag links to a work order and has a one-line reason. Normal jobs vary 20–30% around the rate card, so we only flag above 1.4×. A flag means the job <b>needs review</b>; it is not an accusation.';
  const sel = (id, label, opts, val) => `<label class="f">${label}<select class="sel" id="${id}"><option value="">All</option>${opts.map(o =>
    `<option value="${esc(o[0])}" ${o[0] === val ? 'selected' : ''}>${esc(o[1])}</option>`).join('')}</select></label>`;
  view.innerHTML = `<div class="page-title">${title}</div><div class="page-sub">${sub}</div>
    <div class="row">
      ${sel('f-cat', 'Category', [['Suspicious billing', 'Suspicious billing'], ['Performance', 'Performance']], f.category)}
      ${sel('f-rule', 'Rule', Object.keys(d.rules).map(r => [r, r]), f.rule)}
      ${ME.role === 'Ward Officer' ? '' : sel('f-ward', 'Ward', OPTIONS.wards.map(w => [w.ward_code, w.ward_code + ' – ' + w.ward_name]), f.ward)}
      ${ME.role === 'Contractor' ? '' : sel('f-con', 'Contractor', OPTIONS.contractors.map(c => [c.contractor_id, c.contractor_name]), f.contractor)}
      ${sel('f-st', 'Review status', [['Pending', 'Pending'], ['Verified', 'Verified'], ['Cleared', 'Cleared'], ['Evidence', 'Evidence requested'], ['Escalated', 'Escalated']], f.status)}
      <a class="btn ghost" href="/api/flags.csv?token=${TOKEN}&${q}">⬇ CSV</a>
    </div>
    <div class="kpis">${kpi('Flags', num(d.total))}${kpi('Work orders', num(d.work_orders))}${kpi('Amount involved', inr(d.amount), '', 'warn')}
      ${kpi('Reviewed so far', num(d.rows.filter(r => r.review_status !== 'Pending').length), 'of ' + num(d.rows.length) + ' shown')}</div>
    <div class="grid2"><div class="card"><h3>By rule</h3>${bars(d.by_rule, { label: r => r.rule + ' (' + r.flags + ')', value: 'amount', fmt: inr, cls: 'red' })}</div>
      <div class="card"><h3>Contractor × rule</h3><div id="heat"></div></div></div>
    <div class="card"><h3>Flags <span class="muted">click a row to review or add evidence</span></h3><div id="t-flags"></div></div>
    ${can('Admin', 'Auditor / Verifier', 'Ward Officer') ? `<div class="card"><h3>🧑‍💼 What should be checked first?</h3>${claudeBox('Explain these flags', '/api/claude/flags?' + q)}</div>` : ''}`;
  const bind = (id, key) => { const el = document.getElementById(id); if (el) el.onchange = () => { AUDIT_F[key] = el.value; go('audit'); }; };
  bind('f-cat', 'category'); bind('f-rule', 'rule'); bind('f-ward', 'ward'); bind('f-con', 'contractor'); bind('f-st', 'status');
  const hm = d.heat, mx = Math.max(1, ...hm.values.flat());
  document.getElementById('heat').innerHTML = hm.rows.length ? `<div class="tbl-wrap"><table><tr><th></th>${hm.cols.map(c => `<th>${esc(c)}</th>`).join('')}</tr>${hm.rows.map((r, i) =>
    `<tr><td>${esc(r.replace(' (synthetic)', ''))}</td>${hm.values[i].map(v => `<td class="num" style="background:rgba(220,38,38,${v / mx * .7})">${v || ''}</td>`).join('')}</tr>`).join('')}</table></div>` : '<p class="muted">No flags.</p>';
  table('t-flags', rows, [
    { k: 'work_order_id', l: 'Work order' }, { k: 'rule', l: 'Rule' }, { k: 'severity', l: 'Severity', f: v => `<span class="badge b-${v}">${v}</span>` },
    { k: 'ward_code', l: 'Ward' }, { k: 'contractor_name', l: 'Contractor', f: v => esc(String(v).replace(' (synthetic)', '')) },
    { k: 'cost_inr', l: 'Billed', num: true, f: inr }, { k: 'amount_at_risk_inr', l: 'At risk', num: true, f: inr },
    { k: 'reason', l: 'Reason' }, { k: 'review_status', l: 'Review', f: v => `<span class="badge b-${v.split(' ')[0]}">${esc(v)}</span>` },
    { k: 'evidence_count', l: '📎', num: true }], { onClick: r => openWO(r.work_order_id) });
};

let CON_SEL = null;
V.scorecards = async () => {
  const d = await api('/api/scorecards');
  const isCon = ME.role === 'Contractor';
  const c = d.contractors;
  const sel = isCon ? c.find(x => x.contractor_id === ME.contractor_id) : (c.find(x => x.contractor_id === CON_SEL) || c[0]);
  view.innerHTML = `<div class="page-title">${isCon ? 'My scorecard' : 'Fair scorecards'}</div>
    <div class="page-sub">Durability and speed compare each contractor with what was expected for its mix of jobs: the same work type, equally flood-prone wards and the same rain. 1.0 means "as expected". Weights: durability 40%, speed 30%, cost 30%.
    ${isCon ? ' Other contractors are shown anonymously.' : ''}</div>
    <div class="card" id="detail"></div>
    <div class="tabs"><div class="tab active" data-t="c">Contractors</div>${isCon ? '' : '<div class="tab" data-t="w">Wards</div>'}</div>
    <div id="tab-c"><div class="grid2"><div class="card"><h3>League table</h3><div id="t-c"></div></div>
      <div class="card"><h3>What makes up each grade <span class="muted">points out of 100</span></h3>${gradeStack(c, isCon)}</div></div>
      <div class="card"><h3>Fix failure: actual vs expected for each contractor's job mix
        <span class="muted">95% confidence band</span></h3>${dumbbell(c, isCon)}</div></div>
    <div id="tab-w" style="display:none"><div class="card"><div id="t-w"></div></div></div>`;
  document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.toggle('active', x === t));
    document.getElementById('tab-c').style.display = t.dataset.t === 'c' ? '' : 'none';
    document.getElementById('tab-w').style.display = t.dataset.t === 'w' ? '' : 'none';
  });
  const showDetail = r => {
    document.getElementById('detail').innerHTML = `<h3>${gradeBadge(r.grade)} <span style="flex:1;margin-left:10px">${esc(r.contractor_name)}</span> <span class="muted">${num(r.overall_score)}/100</span></h3>
      <div class="kpis">${kpi('Jobs', num(r.jobs), inr(r.spend_inr))}${kpi('Re-open rate', pct(r.reopen_rate), 'expected ' + pct(r.exp_reopen_rate) + ' for this job mix', r.reopen_rate > r.exp_reopen_rate * 1.15 ? 'warn' : r.reopen_rate < r.exp_reopen_rate * .85 ? 'good' : '')}
      ${kpi('SLA met', pct(r.sla_rate), 'speed score ' + num(r.speed_score))}${kpi('Median bill vs rate card', num(r.median_cost_ratio, 2) + '×', r.overbilled + ' over-billed · ' + r.double_billed + ' double-billed')}
      ${kpi('DLP payments', num(r.dlp_paid), 'repairs BMC paid on roads under warranty')}${kpi('Needs review', inr(r.money_at_risk_inr), '', r.money_at_risk_inr > 0 ? 'warn' : '')}</div>
      ${r.contractor_id ? claudeBox('Write citizen scorecard', '/api/claude/contractor/' + r.contractor_id) : ''}`;
  };
  showDetail(sel);
  table('t-c', c, [{ k: 'grade', l: 'Grade', f: gradeBadge }, { k: 'contractor_name', l: 'Contractor', f: v => esc(String(v).replace(' (synthetic)', '')) },
    { k: 'overall_score', l: 'Score', f: v => prog(v) }, { k: 'jobs', l: 'Jobs', num: true }, { k: 'reopen_rate', l: 'Re-open', num: true, f: v => pct(v) },
    { k: 'exp_reopen_rate', l: 'Expected', num: true, f: v => pct(v) }, { k: 'sla_rate', l: 'SLA', num: true, f: v => pct(v) },
    { k: 'overbilled', l: 'Over-billed', num: true }, { k: 'double_billed', l: 'Double', num: true }],
    { search: false, onClick: r => { if (r.contractor_id) { CON_SEL = r.contractor_id; showDetail(r); window.scrollTo({ top: 0, behavior: 'smooth' }); } },
      rowClass: r => isCon && r.contractor_id === ME.contractor_id ? 'me' : '' });
  if (!isCon) table('t-w', d.wards, [{ k: 'ward_code', l: 'Ward' }, { k: 'ward_name', l: 'Name' }, { k: 'low_lying_index', l: 'Low-lying', num: true },
    { k: 'monsoon_repair_budget_inr_2025', l: 'Budget', num: true, f: inr }, { k: 'spend_inr', l: 'Spent', num: true, f: inr },
    { k: 'budget_used_pct', l: 'Used', f: v => prog(v, 130).replace(/ [\d,]+<\/span>$/, ' ' + num(v) + '%</span>') }, { k: 'failed_fix_spend_inr', l: 'Failed-fix spend', num: true, f: inr },
    { k: 'money_at_risk_inr', l: 'Needs review', num: true, f: inr }, { k: 'sla_rate', l: 'SLA', num: true, f: v => pct(v) },
    { k: 'reopen_rate', l: 'Re-open', num: true, f: v => pct(v) }, { k: 'open_complaints', l: 'Open', num: true }]);
};

V.jobs = async () => {
  const rows = await api('/api/contractor/jobs');
  const n = rows.length, sla = rows.filter(r => r.sla_met === 'Y').length / n, re = rows.filter(r => r.reopened_within_30d === 'Y').length / n;
  view.innerHTML = `<div class="page-title">My jobs</div><div class="page-sub">${esc(ME.contractor_name)}: every work order assigned to you this monsoon.</div>
    <div class="kpis">${kpi('Jobs', num(n))}${kpi('Billed', inr(rows.reduce((s, r) => s + r.cost_inr, 0)))}${kpi('SLA met', pct(sla))}${kpi('Failed within 30d', pct(re), '', re > .25 ? 'warn' : 'good')}</div>
    <div class="card"><h3>My progress updates <span class="muted">what the ward officer decided</span></h3><div id="t-mysubs"></div></div>
    <div class="card"><h3>All my work orders <span class="muted">use “Update” to report progress for sign-off</span></h3><div id="t-j"></div></div>`;
  const subs = await api('/api/work-submissions', { keep: true });
  const last = Object.fromEntries(subs.slice().reverse().map(x => [x.work_order_id, x]));
  table('t-mysubs', subs, [{ k: 'work_order_id', l: 'Work order' }, { k: 'road', l: 'Road' }, { k: 'status', l: 'You reported' }, { k: 'note', l: 'Note' },
    { k: 'review', l: 'Officer decision', f: v => v ? `<span class="badge ${v === 'Approved' ? 'b-Cleared' : 'b-High'}">${esc(v)}</span>` : '<span class="badge b-Pending">Waiting</span>' },
    { k: 'review_note', l: 'Officer note', f: v => esc(v || '') }], { search: false, height: 240, empty: 'No updates yet. Pick a job below and press Update.', onClick: r => trackId(r.work_order_id) });
  table('t-j', rows, [{ k: 'work_order_id', l: 'Work order' }, { k: 'ward_code', l: 'Ward' }, { k: 'road_name', l: 'Road' }, { k: 'repair_method', l: 'Method' },
    { k: 'completed_at', l: 'Completed', f: date }, { k: 'cost_inr', l: 'Billed', num: true, f: inr }, { k: 'cost_ratio', l: '× rate', num: true, f: v => num(v, 2) },
    { k: 'sla_met', l: 'SLA', f: yn }, { k: 'reopened_within_30d', l: 'Held?', f: failed },
    { k: 'work_order_id', l: 'Sign-off', f: v => last[v] ? `<span class="badge ${last[v].review === 'Approved' ? 'b-Cleared' : last[v].review ? 'b-High' : 'b-Pending'}">${esc(last[v].review || 'Waiting')}</span>` : '' },
    { k: 'work_order_id', l: '', f: v => `<button class="btn small" onclick="event.stopPropagation();submitProgress('${v}')">Update</button> <button class="btn ghost small" onclick="event.stopPropagation();trackId('${v}')">Track</button>` }],
    { onClick: r => openWO(r.work_order_id) });
};

let PLAN_BUDGET = null, PLAN_TAB = 'rank';
V.planner = async () => {
  const fixed = ME.role === 'Ward Officer';
  const code = fixed ? ME.ward : (WARD_SEL || 'L');
  const d = await api(`/api/planner/${code}` + (PLAN_BUDGET !== null ? `?budget=${PLAN_BUDGET}` : ''));
  const p = d.plan || [];
  view.innerHTML = `<div class="row" style="justify-content:space-between"><div><div class="page-title">Where should the next rupee go? · ${esc(code)}</div>
      <div class="page-sub">Open issues ranked by risk, the most durable method for each, fitted to the budget. Roads under DLP go back to the original contractor at no cost.</div></div>
      <div class="row" style="margin:0">${fixed ? '' : wardPicker('wp', code, v => { WARD_SEL = v; PLAN_BUDGET = null; go('planner'); })}
      <label class="f">Budget available (₹)<input class="inp" id="bud" type="number" step="50000" value="${Math.round(d.budget)}" style="width:150px"></label></div></div>
    ${d.remaining < 0 ? `<div class="note">Ward ${esc(code)} has already over-spent its monsoon budget by ${inr(-d.remaining)}. Showing a hypothetical top-up.</div>` :
      `<div class="info">Unspent monsoon budget: <b>${inr(d.remaining)}</b></div>`}
    <div class="tabs">${[['rank', '📊 Risk ranking & budget'], ['methods', '🔧 Methods & chronic roads']]
      .map(([k, l]) => `<div class="tab ${PLAN_TAB === k ? 'active' : ''}" data-t="${k}">${l}</div>`).join('')}</div><div id="ptab"></div>`;
  document.getElementById('bud').onchange = e => { PLAN_BUDGET = +e.target.value; go('planner'); };
  document.querySelectorAll('.tab').forEach(t => t.onclick = () => { PLAN_TAB = t.dataset.t; go('planner'); });
  const el = document.getElementById('ptab');
  const fund = p.filter(x => x.fits_budget);
  if (PLAN_TAB === 'rank') {
    const fk = Object.keys(d.weights), colors = ['#3d4280', '#0ea5e9', '#f59e0b', '#dc2626', '#7c3aed', '#10b981', '#94a3b8', '#0f766e'];
    el.innerHTML = !p.length ? '<div class="info">No open road issues in this ward. 🎉</div>' : `
      <div class="kpis">${kpi('Open issues', num(p.length))}${kpi('Fundable now', num(fund.length), inr(fund.reduce((s, x) => s + x.cost_to_bmc_inr, 0)))}
        ${kpi('Free under DLP', num(p.filter(x => x.under_dlp === 'Y').length), 'send to original contractor')}</div>
      <div class="card"><h3>Ranked plan</h3><div id="t-p"></div></div>
      <div class="card"><h3>What drives the top 10 <span class="muted">risk points out of 100</span></h3>${stackBars(p.slice(0, 10).map(x => ({ ...x, lbl: x.locality + ' · ' + x.category })), 'lbl',
        fk.map((k, i) => ({ k: 'f_' + k, name: k + ' (' + d.weights[k] + ')', color: colors[i] })), v => num(v, 1))}</div>
      <div class="card"><h3>🧑‍⚖️ Explain the plan for the corporator</h3>${claudeBox('Explain the plan', `/api/claude/plan/${code}?budget=${d.budget}`)}</div>`;
    if (p.length) table('t-p', p, [{ k: 'fits_budget', l: 'Fund', f: v => v ? '✅' : '–' }, { k: 'risk_score', l: 'Risk', f: v => prog(v) },
      { k: 'locality', l: 'Locality' }, { k: 'category', l: 'Issue' }, { k: 'road_name', l: 'Road' }, { k: 'repair_method', l: 'Method' },
      { k: 'cost_to_bmc_inr', l: 'Cost to BMC', num: true, f: inr }, { k: 'why', l: 'Why this method' }, { k: 'reasons', l: 'Why this rank' }]);
  } else {
    el.innerHTML = `<div class="grid2"><div class="card"><h3>Which method lasts?</h3><div id="t-m"></div></div>
      <div class="card"><h3>Stop patching: chronic roads in ${esc(code)}</h3><div id="t-ch"></div><p class="muted" style="margin-top:8px">*The resurfacing estimate assumes ₹1,100/sqm and 3.5 m lanes. It is not from the rate card, so treat it as indicative only.</p></div></div>`;
    table('t-m', d.methods, [{ k: 'work_type', l: 'Issue' }, { k: 'repair_method', l: 'Method' }, { k: 'jobs', l: 'Jobs', num: true },
      { k: 'reopen_rate', l: 'Fails', num: true, f: v => pct(v) }, { k: 'standard_cost_inr', l: 'Std cost', num: true, f: inr },
      { k: 'cost_per_lasting_fix', l: 'Per lasting fix', num: true, f: inr }], { search: false });
    table('t-ch', d.chronic, [{ k: 'road_name', l: 'Road' }, { k: 'jobs', l: 'Jobs', num: true }, { k: 'failures', l: 'Failures', num: true },
      { k: 'spend_inr', l: 'Patching spend', num: true, f: inr }, { k: 'under_dlp', l: 'DLP' }, { k: 'resurface_estimate_inr', l: 'Resurface est.*', num: true, f: inr }],
      { search: false, empty: 'No chronic roads in this ward.' });
  }
};

V.models = async () => {
  const d = await api('/api/models');
  const f = d.failure, m = d.demand;
  view.innerHTML = `<div class="page-title">ML model card</div><div class="page-sub">Experimental models, shown for research only. The next-rupee planner does not use them: its ranking, method choice and budget fit are fully rule-based. A third model was tried and dropped because it did no better than a simple baseline.</div>
    <div class="grid2"><div class="card"><h3>1 · Repair failure model</h3>
      <p class="muted">Logistic regression on ${num(f.n)} jobs, using only facts known at assignment time. It predicts the chance a fix fails within 30 days.</p>
      <div class="kpis" style="margin-top:12px">${kpi('CV AUC', num(f.cv_auc, 2), 'vs ' + num(f.baseline_auc, 2) + ' method-only baseline', 'good')}${kpi('Brier score', num(f.cv_brier, 3), 'base rate ' + pct(f.base_rate))}</div>
      <h3>Calibration (cross-validated): predicted vs actual failure</h3>
      <div class="tbl-wrap"><table><tr><th>Risk band</th><th>Jobs</th><th>Predicted</th><th>Actual</th></tr>${d.calibration.map((c, i) =>
        `<tr><td>${i + 1} ${i === 0 ? '(safest)' : i === d.calibration.length - 1 ? '(riskiest)' : ''}</td><td class="num">${c.jobs}</td>
         <td><span class="prog"><i style="width:${c.predicted * 200}%;background:#b9bde6"></i></span> ${pct(c.predicted)}</td>
         <td><span class="prog"><i style="width:${c.observed * 200}%"></i></span> ${pct(c.observed)}</td></tr>`).join('')}</table></div>
      <h3 style="margin-top:16px">What pushes failure up or down</h3>${coefBars(d.coefs)}</div>
    <div class="card"><h3>2 · Rain → demand model</h3><p class="muted">Poisson GLM, ward × week. Trained on June–August, tested on September onward.</p>
      <div class="kpis" style="margin-top:12px">${kpi('Error per ward-week', num(m.mae_ward_week, 2), 'vs ' + num(m.mae_baseline, 2) + ' ward-average baseline', 'good')}
        ${kpi('Poisson deviance', num(m.test_deviance, 2), 'vs ' + num(m.baseline_deviance, 2))}${kpi('City weekly correlation', num(m.city_weekly_corr, 2))}</div>
      ${lineChart([{ name: 'Actual', color: '#0f172a', values: d.backtest.map(b => b.y) }, { name: 'Predicted', color: '#3d4280', values: d.backtest.map(b => b.p) }], d.backtest.map(b => date(b.week).slice(5)))}
      <h3 style="margin-top:18px">3 · Tried and dropped</h3><p class="muted">A road-level "where will the next complaint be" model (gradient boosting on history, rain, tide, hotspots and traffic) ranked roads no better than each road's historical average (Spearman 0.32 vs 0.32). So the planner ranking stays rule-based and transparent.</p>
      <div class="note" style="margin-top:12px">Small synthetic dataset. Contractor effects may partly reflect the billing issues the auditor already flags.</div></div></div>`;
};
function coefBars(co) {
  const mx = Math.max(...co.map(c => Math.abs(c.coef)));
  return '<div class="bars">' + co.map(c => `<div class="bar-row"><div class="lbl" title="${esc(c.feature)}">${esc(c.feature.replace(' (synthetic)', ''))}</div>
    <div class="bar-track" style="background:#f8fafc"><div style="width:50%;display:flex;justify-content:flex-end">${c.coef < 0 ? `<div style="width:${-c.coef / mx * 100}%;background:#059669;height:100%;border-radius:6px 0 0 6px"></div>` : ''}</div>
    <div style="width:50%">${c.coef > 0 ? `<div style="width:${c.coef / mx * 100}%;background:#dc2626;height:100%;border-radius:0 6px 6px 0"></div>` : ''}</div></div>
    <div class="bar-val">${c.coef > 0 ? '+' : ''}${num(c.coef, 2)}</div></div>`).join('') + '</div><div class="legend"><span><i style="background:#059669"></i>lasts longer</span><span><i style="background:#dc2626"></i>fails more</span></div>';
}

let ISS_F = { outcome: 'Never fixed (open)', ward: '' };
V.issues = async () => {
  const q = new URLSearchParams(Object.entries(ISS_F).filter(([k, v]) => v && !(k === 'ward' && ME.role === 'Ward Officer'))).toString();
  const d = await api('/api/issues?' + q);
  const qq = d.quality;
  view.innerHTML = `<div class="page-title">From messy complaints to issues to work orders</div>
    <div class="page-sub">Complaints arrive in English, Hinglish, Marathi and Hindi. We place each one, correct its category, group duplicates into one issue, and link it to the work order that fixed it (or flag it as never fixed).</div>
    <div class="kpis">${kpi('Complaints', num(qq.complaints))}${kpi('Distinct issues', num(qq.issues), Math.round((1 - qq.issues / qq.complaints) * 100) + '% were duplicates')}
      ${kpi('Geocoded', num(qq.geocoded_pct) + '%')}${kpi('Category accuracy', num(qq.category_accuracy_clean_pct, 1) + '%', '+' + num(qq.category_accuracy_clean_pct - qq.category_accuracy_raw_pct, 1) + ' pts vs raw', 'good')}
      ${kpi('BMC duplicates merged', num(qq.bmc_duplicates_merged_pct) + '%')}</div>
    <div class="grid2"><div class="card"><h3>What happened to each issue${ME.role === 'Ward Officer' ? ' in ' + ME.ward : ''}</h3>${bars(Object.entries(d.outcomes).map(([k, v]) => ({ k, v })),
      { label: 'k', value: 'v', cls: i => i.k.startsWith('Never') || i.k.includes('failed') ? 'red' : '' })}</div>
      <div class="card"><h3>Languages</h3><div id="t-lang"></div><p class="muted" style="margin-top:8px">The order of evidence was measured, not assumed. Against the actual work type on the work orders, the photo description agreed 100% of the time, the citizen's category 83% and the free-text keywords 78%.</p></div></div>
    <div class="card"><div class="row">
      <label class="f">Outcome<select class="sel" id="f-out"><option value="">All</option>${['Never fixed (open)', 'Fixed – held', 'Fixed – failed within 30d', 'Rejected / not BMC', 'Forwarded to other agency']
        .map(o => `<option ${o === ISS_F.outcome ? 'selected' : ''}>${o}</option>`).join('')}</select></label>
      ${ME.role === 'Ward Officer' ? '' : `<label class="f">Ward<select class="sel" id="f-w"><option value="">All</option>${OPTIONS.wards.map(w => `<option ${w.ward_code === ISS_F.ward ? 'selected' : ''}>${w.ward_code}</option>`).join('')}</select></label>`}
    </div><div id="t-iss"></div></div>`;
  document.getElementById('f-out').onchange = e => { ISS_F.outcome = e.target.value; go('issues'); };
  const fw = document.getElementById('f-w'); if (fw) fw.onchange = e => { ISS_F.ward = e.target.value; go('issues'); };
  table('t-lang', d.languages, [{ k: 'language', l: 'Language' }, { k: 'complaints', l: 'Complaints', num: true, f: num }, { k: 'recategorised', l: 'Re-categorised', num: true, f: num }], { search: false, height: 200 });
  table('t-iss', d.rows, [{ k: 'issue_id', l: 'Issue' }, { k: 'ward_code', l: 'Ward' }, { k: 'locality', l: 'Locality' }, { k: 'category', l: 'Category' },
    { k: 'reports', l: 'Reports', num: true }, { k: 'channels', l: 'Channels' }, { k: 'languages', l: 'Lang' }, { k: 'first_reported', l: 'First reported', f: date },
    { k: 'work_order_id', l: 'Work order', f: v => v ? esc(v) : '–' }, { k: 'outcome', l: 'Outcome' }], { onClick: r => openIssue(r.issue_id) });
};
async function openIssue(id) {
  openModal('<div class="loading">Loading…</div>');
  const rows = await api('/api/issue/' + id);
  openModal(`<div class="page-title">${esc(id)}: ${rows.length} complaint(s)</div><div class="page-sub">Every report we grouped into this issue, with how its category was decided.</div><div id="t-ic"></div>`);
  table('t-ic', rows, [{ k: 'complaint_id', l: 'Complaint' }, { k: 'received_at', l: 'Received', f: v => esc(String(v).replace('T', ' ').slice(0, 16)) }, { k: 'channel', l: 'Channel' },
    { k: 'language', l: 'Lang' }, { k: 'category_reported', l: 'Citizen picked' }, { k: 'category_clean', l: 'Cleaned' }, { k: 'category_source', l: 'Decided by' },
    { k: 'description', l: 'Description' }, { k: 'locality_clean', l: 'Locality' }, { k: 'status', l: 'Status' }, { k: 'work_order_id', l: 'Work order', f: v => v ? esc(v) : '–' }], { search: false, height: 420 });
}

V.social = async () => {
  const d = await api('/api/social');
  view.innerHTML = `<div class="page-title">Social pulse</div><div class="page-sub">What people say on X, WhatsApp and Instagram. We classify forwards, sarcasm and thank-yous, place the posts, and find <b>blind spots</b>: problems reported online with no official complaint within 2 days.</div>
    <div class="kpis">${kpi('Posts', num(d.n))}${kpi('Located', pct(d.located))}${kpi('Blind spots', num(d.blind_spots), 'reported online only', 'warn')}</div>
    <div class="grid2"><div class="card"><h3>Post types</h3>${bars(Object.entries(d.types).map(([k, v]) => ({ k, v })), { label: 'k', value: 'v' })}</div>
      <div class="card"><h3>Top blind spots by engagement</h3>${bars(d.top_blind, { label: b => b.locality + ' · ' + b.issue_category, value: 'engagement', cls: 'red' })}</div></div>
    <div class="card"><div id="t-s"></div></div>`;
  table('t-s', d.rows, [{ k: 'posted_at', l: 'Posted', f: date }, { k: 'source', l: 'Source' }, { k: 'text', l: 'Text' }, { k: 'post_type', l: 'Type' },
    { k: 'issue_category', l: 'Issue', f: v => esc(v || '–') }, { k: 'locality', l: 'Locality', f: v => esc(v || '–') },
    { k: 'blind_spot', l: 'Blind spot', f: v => v ? '<span class="badge b-High">yes</span>' : '' }, { k: 'likes_or_forwards', l: 'Engagement', num: true }]);
};

const CHAT = [];
V.ask = async () => {
  view.innerHTML = `<div class="page-title">💬 Mera Complaint: what happened to my complaint?</div>
    <div class="page-sub">Ask in English, Hinglish, मराठी or हिंदी, using your complaint ID or locality. ${ME.claude ? 'Claude replies in the language you used.' : 'Claude is off, so replies come from a fixed template.'}</div>
    <div class="card"><div class="chat" id="chat"></div>
      <div class="chat-in"><input class="inp" id="q" placeholder="e.g. BMC25-000005 ka kya hua?"><button class="btn" id="send">Ask</button></div>
      <div class="suggest">${['BMC25-000005 ka kya hua?', 'Hindmata madhe paani complaint keli hoti, kay jhala?', 'What happened to the pothole complaints in Andheri East?', 'Kurla East में गड्ढे की शिकायत का क्या हुआ?']
        .map(s => `<span>${esc(s)}</span>`).join('')}</div></div>`;
  const box = document.getElementById('chat');
  const paint = () => {
    box.innerHTML = CHAT.length ? CHAT.map(m => m.role === 'user' ? `<div class="msg user">${esc(m.text)}</div>` :
      `<div class="msg bot">${md(m.text)}${m.evidence ? `<details><summary>Evidence used</summary><pre>${esc(JSON.stringify(m.evidence, null, 1))}</pre></details>` : ''}</div>`).join('') :
      '<div class="muted" style="text-align:center;padding:40px">Namaste 🙏 Ask about any complaint.</div>';
    box.scrollTop = box.scrollHeight;
  };
  const send = async q => {
    if (!q.trim()) return;
    CHAT.push({ role: 'user', text: q }); CHAT.push({ role: 'bot', text: '_Looking up…_' }); paint();
    try { const r = await post('/api/citizen/ask', { q }); CHAT[CHAT.length - 1] = { role: 'bot', text: r.answer, evidence: r.evidence }; }
    catch (e) { CHAT[CHAT.length - 1] = { role: 'bot', text: '⚠️ ' + e.message }; }
    paint();
  };
  document.getElementById('send').onclick = () => { const i = document.getElementById('q'); send(i.value); i.value = ''; };
  document.getElementById('q').onkeydown = e => { if (e.key === 'Enter') document.getElementById('send').click(); };
  document.querySelectorAll('.suggest span').forEach(s => s.onclick = () => send(s.textContent));
  paint();
};

V.reports = async () => {
  const reps = await api('/api/citizen/reports');
  const isCit = ME.role === 'Citizen';
  view.innerHTML = `<div class="page-title">${isCit ? 'Report a road problem' : 'Citizen reports'}</div>
    <div class="page-sub">${isCit ? 'Your report is placed in a ward automatically and joins the issue queue that ward officers see.' : (ME.role === 'Ward Officer' ? `New reports from citizens in ward ${ME.ward}.` : 'All reports filed through RastaNidhi.')}</div>
    ${isCit || ME.role === 'Admin' ? `<div class="card"><h3>New report</h3><div class="grid3">
      <label class="f">Locality<input class="inp" id="r-loc" placeholder="e.g. Kurla East, Vile, परळ"></label>
      <label class="f">Problem<select class="sel" id="r-cat">${['Pothole', 'Waterlogging', 'Open or broken manhole', 'Road cave-in', 'Choked drain / nullah overflow', 'Broken paver blocks'].map(c => `<option>${c}</option>`).join('')}</select></label>
      <label class="f">&nbsp;<button class="btn" id="r-send">Submit report</button></label></div>
      <label class="f" style="margin-top:12px">Describe it (any language)<textarea class="inp" id="r-desc" placeholder="Bada gaddha near the bus stop, bikes are falling"></textarea></label></div>` : ''}
    <div class="card"><h3>${isCit ? 'My reports' : 'Reports'}</h3><div id="t-r"></div></div>`;
  const s = document.getElementById('r-send');
  if (s) s.onclick = async () => {
    try { const r = await post('/api/citizen/report', { locality: document.getElementById('r-loc').value, category: document.getElementById('r-cat').value, description: document.getElementById('r-desc').value });
      toast(`Report ${r.report_id} received${r.ward_code ? ' · ward ' + r.ward_code : ''}`); go('reports'); } catch (e) { toast(e.message); }
  };
  table('t-r', reps, [{ k: 'report_id', l: 'Report' }, { k: 'at', l: 'Filed', f: v => esc(String(v).replace('T', ' ')) }, { k: 'category', l: 'Problem' },
    { k: 'locality', l: 'Typed locality' }, { k: 'locality_matched', l: 'Matched', f: v => esc(v || '–') }, { k: 'ward_code', l: 'Ward', f: v => esc(v || '?') },
    { k: 'description', l: 'Description' }, ...(isCit ? [] : [{ k: 'by', l: 'By' }]),
    { k: 'status', l: 'Status', f: (v, r) => can('Ward Officer', 'Admin') ? `<select class="sel" onchange="setReportStatus('${esc(r.report_id)}',this.value)">${
      ['Open', 'In Progress', 'Work order linked', 'Resolved', 'Closed', 'Rejected'].map(s => `<option ${s === normStatus(v) ? 'selected' : ''}>${s}</option>`).join('')}</select>` : `<span class="badge b-Pending">${esc(normStatus(v))}</span>` },
    { k: 'report_id', l: '', f: v => `<button class="btn ghost small" onclick="trackId('${v}')">📦 Track</button>` }],
    { search: false, empty: 'No reports yet.' });
};
const normStatus = s => ({ Received: 'Open', Inspected: 'In Progress', 'Work order raised': 'Work order linked', 'Rejected – not BMC road': 'Rejected' }[s] || s);
async function setReportStatus(id, status) {
  let work_order_id = null;
  if (status === 'Work order linked') { work_order_id = prompt('Which work order fixes this report? (e.g. WO25-00012)'); if (!work_order_id) { go('reports'); return; } }
  try { await post(`/api/citizen/reports/${id}/status`, { status, work_order_id }); toast(`${id} → ${status}`); refreshBadges(); go('reports'); } catch (e) { toast(e.message); go('reports'); }
}

V.users = async () => {
  const d = await api('/api/admin/users');
  view.innerHTML = `<div class="page-title">Users & roles</div><div class="page-sub">Everyone who has signed in. Change a role, lock it, or deactivate an account. Deactivating ends that user's sessions immediately.</div>
    <div class="kpis">${kpi('Users', num(d.users.length))}${kpi('Active sessions', num(d.users.reduce((s, u) => s + u.sessions, 0)))}
      ${kpi('Auditor decisions', num(d.counts.reviews))}${kpi('Evidence notes', num(d.counts.evidence))}${kpi('Citizen reports', num(d.counts.reports))}</div>
    <div class="role-grid">${[['🛡️', 'Admin'], ['🏛️', 'Ward Officer'], ['👷', 'Contractor'], ['🔎', 'Auditor / Verifier'], ['👤', 'Citizen'], ['📊', 'Researcher']].map(([i, r]) =>
      `<div class="role-card"><div style="font-size:22px">${i}</div><div class="n">${d.users.filter(u => u.role === r).length}</div><div class="l">${r}</div></div>`).join('')}</div>
    <div class="card"><h3>Users</h3><div id="t-u"></div></div>
    <div class="card"><h3>Role access matrix <span class="muted">enforced by the server on every request</span></h3><div class="tbl-wrap"><table>
      <tr><th>Capability</th><th>Citizen</th><th>Ward Officer</th><th>Contractor</th><th>Auditor</th><th>Researcher</th><th>Admin</th></tr>
      ${[['View ward spending summary', '✓', '✓ own ward', '—', '✓', '✓', '✓'], ['Track / file a complaint', '✓', 'update status', '—', '—', '—', '✓'],
         ['See work-order bills', '—', 'own ward', 'own jobs', '✓', '—', '✓'], ['Review audit flags', '—', 'own ward (notes)', 'submit evidence', '✓ decide', '—', '✓ decide'],
         ['Issue recovery notices', '—', '✓ own ward', '—', '✓', '—', '✓'], ['Next-rupee planner', '—', '✓ own ward', '—', '—', '✓', '✓'],
         ['Scorecards', '—', '—', 'own + anonymised peers', '✓', '✓', '✓'], ['Data health, alerts, ML model card', '—', '—', '—', 'alerts, data health', '✓', '✓'],
         ['Manage accounts & settings', '—', '—', '—', '—', '—', '✓']].map(r => `<tr>${r.map((c, i) => `<td>${i ? c : '<b>' + c + '</b>'}</td>`).join('')}</tr>`).join('')}
    </table></div></div>
    <div class="grid2"><div class="card"><h3>Claude</h3><p class="muted">Status: ${d.claude ? '🟢 on (' + esc(d.model) + ')' : !d.has_key ? '⚪ off: no API key' : '⚪ off: switched off by admin'}. The key is kept in server memory only and is never written to disk.</p>
      <div class="toggle-row"><div><div class="t-title">Use Claude</div><div class="t-sub">Applies to every user. When off, narratives and the assistant fall back to rule-based text; all numbers still work.</div></div>
        <div class="switch ${d.claude_enabled ? 'on' : ''}" id="claude-sw"><div class="knob"></div></div></div>
      <div class="row" style="margin-top:10px"><input class="inp" id="key" type="password" placeholder="sk-ant-…" style="flex:1"><button class="btn" id="key-btn">Save key</button></div></div>
      <div class="card"><h3>Road Audit AI · Gemini</h3><p class="muted" id="gm-status">Checking…</p>
        <div class="row" style="margin-top:10px"><input class="inp" id="gkey" type="password" placeholder="Gemini API key (AIza…)" style="flex:1"><button class="btn" id="gkey-btn">Save key</button></div>
        <p class="muted" style="margin-top:6px">Kept in server memory only, never written to disk. Without it the Road Audit AI answers in retrieval-only mode.</p></div>
      <div class="card"><h3>Recent activity</h3><div class="timeline" style="max-height:300px;overflow:auto">${d.activity.map(a => `<div><div class="t">${esc(a.at.replace('T', ' '))} · ${esc(a.who)}</div>${esc(a.what)}</div>`).join('') || '<p class="muted">Nothing yet.</p>'}</div></div></div>`;
  document.getElementById('claude-sw').onclick = () => setClaude(!d.claude_enabled).then(() => go('users'));
  api('/api/roadbot/status', { keep: true }).then(g => { const el = document.getElementById('gm-status'); if (el) el.innerHTML =
    `Status: ${g.gemini_key ? '🟢 key set' : '⚪ no key (retrieval-only)'} · index ${g.ready ? `ready, ${g.vectors} vectors, ${g.tables} tables` : g.error ? 'failed: ' + esc(g.error) : 'building…'}`; }).catch(() => { });
  document.getElementById('gkey-btn').onclick = async () => { try { const r = await post('/api/admin/geminikey', { key: document.getElementById('gkey').value });
    toast(r.gemini_key ? 'Gemini connected' : 'Key cleared'); go('users'); } catch (e) { toast(e.message); } };
  document.getElementById('key-btn').onclick = async () => { try { const r = await post('/api/admin/apikey', { key: document.getElementById('key').value }); toast(r.claude ? 'Claude connected' : 'Key not set'); boot(); } catch (e) { toast(e.message); } };
  table('t-u', d.users, [{ k: 'email', l: 'Email' },
    { k: 'role', l: 'Role', f: (v, u) => `<select class="sel" onchange="patchUser('${esc(u.email)}',{role:this.value})" onclick="event.stopPropagation()">${OPTIONS.roles.map(r => `<option ${r === v ? 'selected' : ''}>${r}</option>`).join('')}</select>` },
    { k: 'ward', l: 'Ward', f: v => esc(v || '–') }, { k: 'contractor_id', l: 'Company', f: v => esc(v || '–') },
    { k: 'last_login', l: 'Last sign-in', f: v => esc(String(v).replace('T', ' ')) }, { k: 'sessions', l: 'Sessions', num: true },
    { k: 'locked_role', l: 'Role locked', f: (v, u) => `<input type="checkbox" ${v ? 'checked' : ''} onchange="patchUser('${esc(u.email)}',{locked_role:this.checked})">` },
    { k: 'active', l: 'Active', f: (v, u) => u.email === ME.email ? 'you' : `<input type="checkbox" ${v !== false ? 'checked' : ''} onchange="patchUser('${esc(u.email)}',{active:this.checked})">` }], { search: true });
};
async function patchUser(email, changes) {
  try { await api('/api/admin/users/' + encodeURIComponent(email), { method: 'PATCH', body: JSON.stringify(changes) }); toast('Saved'); } catch (e) { toast(e.message); }
}

// ------------------------------------------------------------------ added: Admin prototype pages
V.alerts = async () => {
  const a = await api('/api/alerts');
  const n = s => a.filter(x => x.severity === s).length;
  view.innerHTML = `<div class="page-title">Alerts</div>
    <div class="page-sub">Conditions worth a human look, recomputed from the data and from what users have done in RastaNidhi (pending reviews, new citizen reports) every time this page loads.</div>
    <div class="kpis">${kpi('Critical', n('critical'), '', 'warn')}${kpi('Warning', n('warning'))}${kpi('Info', n('info'))}</div>
    <div class="card">${a.map(alertRow).join('')}</div>`;
};

V.datahealth = async () => {
  const d = await api('/api/datahealth');
  view.innerHTML = `<div class="page-title">Data health & complaints intake</div>
    <div class="page-sub">Completeness and linkage checks on the incoming data. A gap here is not an accusation; it shows where to double-check before trusting a number. For example, helpline calls have no GPS by design.</div>
    <div class="kpis">${kpi('Missing ward code', d.missing_ward_pct + '%', 'of ' + num(d.complaints_total) + ' complaints')}${kpi('Missing GPS', d.missing_gps_pct + '%', 'helpline, portal and walk-in rarely have it')}
      ${kpi('Open, unresolved', num(d.open_unresolved), 'avg age ' + d.avg_open_age_days + ' days', 'warn')}${kpi('Linked after completion', num(d.late_linked), 'complaint logged after the fix: check the link')}
      ${kpi('Work orders unlinked', d.wo_unlinked_pct + '%', 'no complaint attached')}${kpi('DLP tag to verify', num(d.dlp_tag_to_verify), 'resurfaced 2023+ but marked DLP = N')}
      ${kpi('Vague category', d.vague_category_pct + '%', '"Other" / "Road related"')}${kpi('Non-English', d.non_english_pct + '%', 'Hinglish, Marathi or Hindi')}</div>
    <div class="grid2"><div class="card"><h3>Complaints by channel</h3>${bars(Object.entries(d.channels).map(([k, v]) => ({ k, v })), { label: 'k', value: 'v' })}</div>
      <div class="card"><h3>Complaints by language</h3>${bars(Object.entries(d.languages).map(([k, v]) => ({ k, v })), { label: 'k', value: 'v', cls: 'alt' })}</div></div>
    <div class="grid2"><div class="card"><h3>Complaints and spend by month</h3>${comboChart(d.trend.labels, d.trend.spend_lakh, d.trend.complaints)}</div>
      <div class="card"><h3>Complaint status</h3>${bars(Object.entries(d.statuses).map(([k, v]) => ({ k, v })), { label: 'k', value: 'v', cls: i => i.k.startsWith('Open') || i.k.startsWith('In') ? 'red' : '' })}</div></div>`;
};

let SENS = { ratio: 1.5, dup: 7 };
V.settings = async () => {
  const s = await api('/api/admin/settings');
  view.innerHTML = `<div class="page-title">Settings</div><div class="page-sub">Tune the audit sensitivity and platform behaviour.</div>
    <div class="card"><h3>Audit sensitivity: what if?</h3>
      <p class="muted">Move the sliders and every count below is recomputed on the server across all 2,499 work orders. The live audit keeps its calibrated rules
      (over-billing above <b>1.4×</b> the rate card, duplicates within <b>14 days</b>). The admin prototype used 1.5× and 7 days. This lets you compare the two before changing policy.</p>
      <div class="grid2" style="margin-top:12px">
        <label class="f">Over-billing threshold: <span class="slider-val" id="lr">${SENS.ratio.toFixed(2)}×</span> rate card<input type="range" id="sr" min="110" max="300" step="5" value="${SENS.ratio * 100}"></label>
        <label class="f">Duplicate-billing window: <span class="slider-val" id="ld">${SENS.dup}</span> days<input type="range" id="sd" min="1" max="30" value="${SENS.dup}"></label></div>
      <div id="sens-out"><div class="loading">Computing…</div></div></div>
    <div class="card"><h3>Platform toggles <span class="muted">saved for everyone</span></h3>
      ${[['claude_enabled', 'Use Claude', 'Turns all Claude writing on or off for every user. When off, the app uses rule-based text and templates; all numbers still work.', true],
         ['auto_flag_dlp', 'Auto-flag DLP repairs', 'Any paid work order on a road still under warranty is flagged. When off, DLP flags are hidden from audit queues.', true],
         ['human_review_before_publish', 'Require human review before citizens see a flag', 'When on, the citizen bot only mentions audit flags an auditor has marked Verified.', true],
         ['multilingual_parsing', 'Multilingual complaint parsing', 'Hinglish, Marathi and Hindi descriptions are parsed and geocoded.', false],
         ['weekly_digest', 'Weekly ward officer digest email', 'Budget utilisation and new flags every Monday. Saved preference; email sending is not connected in this demo.', false]]
        .map(([k, t, sub, wired]) => `<div class="toggle-row"><div><div class="t-title">${t} ${wired ? '<span class="chip green" style="padding:1px 8px">live</span>' : ''}</div><div class="t-sub">${sub}</div></div>
          <div class="switch ${s[k] ? 'on' : ''}" data-k="${k}"><div class="knob"></div></div></div>`).join('')}</div>`;
  document.querySelectorAll('.switch').forEach(sw => sw.onclick = async () => {
    const on = !sw.classList.contains('on');
    try { await post('/api/admin/settings', { [sw.dataset.k]: on }); sw.classList.toggle('on', on); toast('Saved'); refreshBadges(); if (sw.dataset.k === 'claude_enabled') boot(); } catch (e) { toast(e.message); }
  });
  const run = async () => {
    const r = await api(`/api/sensitivity?ratio=${SENS.ratio}&dup_days=${SENS.dup}`);
    const n = r.now, rows = [['Now (sliders)', r.now], ['Live audit (1.4× · 14 d)', r.app_default], ['Admin prototype (1.5× · 7 d)', r.prototype_default]];
    document.getElementById('sens-out').innerHTML = `<div class="live-box">
        <div><div class="lv" style="color:#d97706">${num(n.over_count)}</div><div class="ll">over-billed jobs</div></div>
        <div><div class="lv" style="color:#d97706">${inr(n.over_excess)}</div><div class="ll">billed above rate card</div></div>
        <div><div class="lv" style="color:#3d4280">${num(n.dup_count)}</div><div class="ll">duplicate bills</div></div>
        <div><div class="lv" style="color:#3d4280">${inr(n.dup_value)}</div><div class="ll">duplicate value</div></div>
        <div><div class="lv" style="color:#dc2626">${inr(n.total_at_risk)}</div><div class="ll">total at risk (incl. ${inr(n.dlp_value)} DLP)</div></div></div>
      <div class="tbl-wrap" style="margin-top:12px"><table class="cmp-tbl"><tr><th>Setting</th><th>Over-billed</th><th>Excess</th><th>Duplicates</th><th>Flagged work orders</th><th>Total at risk</th></tr>
        ${rows.map(([l, x]) => `<tr><td>${l}</td><td>${num(x.over_count)}</td><td>${inr(x.over_excess)}</td><td>${num(x.dup_count)}</td><td>${num(x.flagged_work_orders)}</td><td>${inr(x.total_at_risk)}</td></tr>`).join('')}</table></div>`;
  };
  const sr = document.getElementById('sr'), sd = document.getElementById('sd');
  sr.oninput = () => { document.getElementById('lr').textContent = (sr.value / 100).toFixed(2) + '×'; };
  sd.oninput = () => { document.getElementById('ld').textContent = sd.value; };
  sr.onchange = () => { SENS.ratio = sr.value / 100; run(); };
  sd.onchange = () => { SENS.dup = +sd.value; run(); };
  run();
};

// ------------------------------------------------------------------ added: Ward Officer prototype pages
V.roads = async () => {
  const fixed = ME.role === 'Ward Officer';
  const code = fixed ? ME.ward : (WARD_SEL || 'L');
  const d = await api('/api/roads?ward=' + encodeURIComponent(code));
  const r = d.rows;
  view.innerHTML = `<div class="row" style="justify-content:space-between"><div><div class="page-title">Roads & risk · ${esc(code)}</div>
      <div class="page-sub">Every road segment ranked by risk. Score = ${Object.entries(d.weights).map(([k, v]) => v + '% ' + k.replace('_', ' ')).join(' + ')}.
      Roads under DLP go to recovery, not repair.</div></div>${fixed ? '' : wardPicker('wp', code, v => { WARD_SEL = v; go('roads'); })}</div>
    <div class="kpis">${kpi('Road segments', num(r.length))}${kpi('Under DLP', num(r.filter(x => x.under_dlp === 'Y').length), 'recover, don\'t repair')}
      ${kpi('On ambulance routes', num(r.filter(x => x.critical_access).length))}${kpi('With road-condition accidents', num(r.filter(x => x.accidents > 0).length), '', 'warn')}</div>
    <div class="card"><div id="t-roads"></div></div>`;
  table('t-roads', r, [{ k: 'road_name', l: 'Road', f: (v, x) => `<b>${esc(v)}</b><div class="muted">${x.road_id} · ${esc(x.road_type)}</div>` },
    { k: 'surface', l: 'Surface' }, { k: 'risk_score', l: 'Risk', f: v => prog(v) }, { k: 'accidents', l: 'Accidents', num: true },
    { k: 'flood_dist_km', l: 'Flood hotspot', num: true, f: v => v === null ? '–' : num(v, 2) + ' km' },
    { k: 'critical_access', l: 'Ambulance route', f: v => v ? '<span class="badge b-Escalated">Yes</span>' : '–' },
    { k: 'under_dlp', l: 'DLP', f: v => v === 'Y' ? '<span class="badge b-High">Yes</span>' : 'No' }, { k: 'prior_jobs', l: 'Past jobs', num: true },
    { k: 'reopen_rate', l: 'Re-opened', num: true, f: v => pct(v) }, { k: 'spend', l: 'Spent', num: true, f: inr },
    { k: 'rec_method', l: 'Recommended', f: (v, x) => x.under_dlp === 'Y' ? `<span class="muted">Recovery${x.dlp_jobs ? ' (' + inr(x.dlp_paid_inr) + ' paid)' : ''}</span>` : `${esc(v)} <span class="muted">${pct(x.rec_reopen_rate)} fail · ${inr(x.rec_cost_inr)}/lasting fix</span>` }],
    { onClick: can('Admin', 'Ward Officer', 'Auditor / Verifier') ? x => x.under_dlp === 'Y' && x.dlp_jobs > 0 ? draftNotice('road', x.road_id) : null : null });
};

let CMP_F = { status: '', ward: '' };
V.complaints = async () => {
  const fixed = ME.role === 'Ward Officer';
  const q = new URLSearchParams(Object.entries({ status: CMP_F.status, ward: fixed ? '' : CMP_F.ward }).filter(([, v]) => v)).toString();
  const d = await api('/api/complaints?' + q);
  view.innerHTML = `<div class="page-title">Complaints${fixed ? ' · ward ' + esc(ME.ward) : ''}</div>
    <div class="page-sub">Citizen reports as they arrived, with the cleaned category and the issue and work order they were linked to.</div>
    <div class="row">${['', 'Open', 'In Progress', 'Resolved', 'Closed - Duplicate'].map(s => `<button class="btn ${CMP_F.status === s ? '' : 'ghost'} small" data-s="${s}">${s || 'All'}${s && d.statuses[s] !== undefined && !CMP_F.status ? ' (' + d.statuses[s] + ')' : ''}</button>`).join('')}
      ${fixed ? '' : `<select class="sel" id="cw"><option value="">All wards</option>${OPTIONS.wards.map(w => `<option ${w.ward_code === CMP_F.ward ? 'selected' : ''}>${w.ward_code}</option>`).join('')}</select>`}
      <span class="muted">${num(d.total)} complaints${d.total > d.rows.length ? ', newest ' + d.rows.length + ' shown' : ''}</span></div>
    <div class="card"><div id="t-cmp"></div></div>`;
  document.querySelectorAll('[data-s]').forEach(b => b.onclick = () => { CMP_F.status = b.dataset.s; go('complaints'); });
  const cw = document.getElementById('cw'); if (cw) cw.onchange = () => { CMP_F.ward = cw.value; go('complaints'); };
  const lang = { en: 'English', 'hi-en': 'Hinglish', mr: 'Marathi', hi: 'Hindi' };
  table('t-cmp', d.rows, [{ k: 'complaint_id', l: 'Complaint' }, { k: 'received_at', l: 'Received', f: date }, { k: 'category_clean', l: 'Category',
      f: (v, x) => esc(v) + (v !== x.category_reported ? ` <span class="muted" title="citizen picked ${esc(x.category_reported)}">(was ${esc(x.category_reported)})</span>` : '') },
    { k: 'locality_text', l: 'Locality' }, ...(fixed ? [] : [{ k: 'ward_clean', l: 'Ward' }]), { k: 'language', l: 'Lang', f: v => lang[v] || esc(v) },
    { k: 'channel', l: 'Channel' }, { k: 'upvotes', l: 'Upvotes', num: true }, { k: 'status', l: 'Status' },
    { k: 'work_order_id', l: 'Work order', f: v => v ? esc(v) : '–' }, { k: 'description', l: 'Description', f: v => esc(String(v || '').slice(0, 90)) }],
    { onClick: x => x.issue_id && openIssue(x.issue_id) });
};

V.map = async () => {
  const officer = ME.role === 'Ward Officer';
  view.innerHTML = `<div class="page-title">Ward map${officer ? ' · ward ' + esc(ME.ward) : ''}</div>
    <div class="page-sub">Colour the wards by any measure, hover for a quick look, click a ward for its full picture. Scroll or use + / − to zoom, drag to move.</div>
    <div id="fullmap"></div>`;
  await WardMap(document.getElementById('fullmap'), { full: true, initial: officer ? null : WARD_SEL });
};

// ------------------------------------------------------------------ added: Auditor prototype pages
const ST_CLS = s => s.startsWith('Verified') ? 'b-Verified' : s.startsWith('Cleared') ? 'b-Cleared' : s.startsWith('Evidence') ? 'b-Evidence' : s === 'Escalated' ? 'b-Escalated' : 'b-Pending';
const RULE_LBL = { OVERBILLED: 'Over-billed', DOUBLE_BILLED: 'Double-billed', DLP_PAID: 'DLP', SLA_FLAG_WRONG: 'SLA record' };
const RULE_CLS = { OVERBILLED: 'b-Medium', DOUBLE_BILLED: 'b-Evidence', DLP_PAID: 'b-High', SLA_FLAG_WRONG: 'b-Low' };

V.reviewdash = async () => {
  const d = await api('/api/review/summary');
  const s = Object.fromEntries(d.by_status.map(x => [x.status, x]));
  const colors = ['#d97706', '#d64545', '#1d7a48', '#3d4280', '#7c3aed'];
  view.innerHTML = pageHero('mumbai-cst.jpg', 'Audit desk', 'Turn flags into findings, one decision at a time', 'Joe Ravi, CC BY-SA 3.0') + `<div class="page-title">Review dashboard</div>
    <div class="page-sub">Every suspicious work order, city-wide, and how the review is going. Decisions are shared: what you confirm here is what ward officers recover and contractors answer.</div>
    <div class="kpis">${kpi('Flagged work orders', num(d.total), 'of ' + num(d.work_orders) + ' jobs')}
      ${kpi('Pending review', num(s['Pending'].n), inr(s['Pending'].amount) + ' undecided', 'warn')}
      ${kpi('Confirmed', num(s['Verified – recover money'].n + s['Escalated'].n), inr(s['Verified – recover money'].amount + s['Escalated'].amount) + ' to recover')}
      ${kpi('Dismissed', num(s['Cleared – explained'].n), inr(s['Cleared – explained'].amount) + ' explained', 'good')}
      ${kpi('Evidence requested', num(s['Evidence requested'].n), 'waiting on contractors')}</div>
    <div class="card"><div class="row" style="justify-content:space-between;margin:0"><b>Review progress</b><span class="muted">${num(d.done_pct, 1)}% decided</span></div>
      <div class="util-bar" style="margin-top:8px;height:12px"><i class="grow" style="width:${Math.max(.5, d.done_pct)}%"></i></div>
      <div class="row" style="margin:14px 0 0"><button class="btn" onclick="go('review')">▶ Continue reviewing (${num(s['Pending'].n)} left)</button>
      <button class="btn ghost" onclick="go('auditreport')">📄 Open audit report</button></div></div>
    <div class="grid2"><div class="card"><h3>Decisions so far</h3>${donut(d.by_status.map(x => ({ label: x.status, value: x.n })), colors, d.total, 'flagged jobs')}</div>
      <div class="card"><h3>Flags by type <span class="muted">₹ involved</span></h3>${bars(d.by_rule.map(r => ({ ...r, lbl: (RULE_LBL[r.rule] || r.rule) + ' (' + r.n + ')' })), { label: 'lbl', value: 'amount', fmt: inr, cls: 'red' })}
        ${d.reviewers.length ? `<h3 style="margin-top:16px">Reviewers</h3>${bars(d.reviewers, { label: 'who', value: 'decisions' })}` : ''}</div></div>
    <div class="grid2"><div class="card"><h3>Top wards by flagged jobs</h3>${bars(d.top_wards, { label: 'ward_code', value: 'n' })}</div>
      <div class="card"><h3>Flagged jobs by contractor</h3>${bars(d.by_contractor, { label: c => c.contractor_name.replace(' (synthetic)', ''), value: 'n', cls: 'red' })}</div></div>`;
};

let RQ = { status: 'Pending', rule: '', ward: '', q: '', pick: null };
V.review = async () => {
  const qs = new URLSearchParams(Object.entries({ status: RQ.status, rule: RQ.rule, ward: RQ.ward, q: RQ.q }).filter(([, v]) => v)).toString();
  const d = await api('/api/review/queue?' + qs);
  const rows = d.rows;
  if (!rows.find(r => r.work_order_id === RQ.pick)) RQ.pick = rows.length ? rows[0].work_order_id : null;
  view.innerHTML = `<div class="page-title">Review queue</div>
    <div class="page-sub">Confirm or dismiss each flag with a reason. After each decision the next one opens automatically.
      Keys: <kbd>↑</kbd><kbd>↓</kbd> move · <kbd>C</kbd> confirm · <kbd>D</kbd> dismiss · <kbd>E</kbd> request evidence · <kbd>X</kbd> escalate</div>
    <div class="row">${['Pending', 'Verified – recover money', 'Cleared – explained', 'Evidence requested', 'Escalated', ''].map(s =>
      `<button class="btn small ${RQ.status === s ? '' : 'ghost'}" data-st="${s}">${s ? s.split(' – ')[0] : 'All'} ${s ? '<span class="muted">' + (d.counts[s] || 0) + '</span>' : ''}</button>`).join('')}
      <select class="sel" id="rq-rule"><option value="">All flag types</option>${Object.entries(RULE_LBL).slice(0, 3).map(([k, v]) => `<option value="${k}" ${RQ.rule === k ? 'selected' : ''}>${v}</option>`).join('')}</select>
      <select class="sel" id="rq-ward"><option value="">All wards</option>${OPTIONS.wards.map(w => `<option ${RQ.ward === w.ward_code ? 'selected' : ''}>${w.ward_code}</option>`).join('')}</select>
      <input class="inp" id="rq-q" placeholder="Search work order, contractor, road…" value="${esc(RQ.q)}" style="width:250px"></div>
    <div class="review-grid"><div class="card pick-list" id="rq-list"></div><div class="card" id="rq-detail"></div></div>`;
  document.querySelectorAll('[data-st]').forEach(b => b.onclick = () => { RQ.status = b.dataset.st; RQ.pick = null; go('review'); });
  document.getElementById('rq-rule').onchange = e => { RQ.rule = e.target.value; go('review'); };
  document.getElementById('rq-ward').onchange = e => { RQ.ward = e.target.value; go('review'); };
  let t; document.getElementById('rq-q').oninput = e => { clearTimeout(t); t = setTimeout(() => { RQ.q = e.target.value; go('review'); }, 350); };
  const list = document.getElementById('rq-list');
  const paintList = () => {
    list.innerHTML = rows.length ? rows.slice(0, 200).map(r => `<div class="pick-item ${r.work_order_id === RQ.pick ? 'active' : ''}" data-id="${r.work_order_id}">
        <div class="pick-top"><b>${r.work_order_id}</b><span class="badge ${ST_CLS(r.status)}">${esc(r.status.split(' – ')[0])}</span></div>
        <div class="pick-sub">${esc(r.contractor_name.replace(' (synthetic)', ''))} · ${esc(r.road_name)} · ward ${r.ward_code}</div>
        <div class="pick-foot">${r.rules.map(x => `<span class="badge ${RULE_CLS[x]}">${RULE_LBL[x] || x}</span>`).join('')}<b>${inr(r.amount_at_risk_inr)}</b>${r.evidence_count ? `<span title="evidence notes">📎${r.evidence_count}</span>` : ''}</div></div>`).join('')
      : '<div class="loading">Nothing here. 🎉 Pick another status.</div>';
    list.querySelectorAll('.pick-item').forEach(el => el.onclick = () => { RQ.pick = el.dataset.id; paintList(); paintDetail(); });
    const act = list.querySelector('.active'); if (act) act.scrollIntoView({ block: 'nearest' });
  };
  const paintDetail = async () => {
    const box = document.getElementById('rq-detail');
    const r = rows.find(x => x.work_order_id === RQ.pick);
    if (!r) { box.innerHTML = '<div class="loading">Pick a flagged work order to review it.</div>'; return; }
    box.innerHTML = `<div class="detail-anim">
      <div class="row" style="justify-content:space-between;margin:0"><div><div class="page-title" style="font-size:20px">${r.work_order_id}</div>
        <div class="muted">${esc(r.road_name)} · ward ${r.ward_code} · ${esc(r.contractor_name)}</div></div><span class="badge ${ST_CLS(r.status)}">${esc(r.status)}</span></div>
      <div class="why-tags" style="margin:10px 0">${r.rules.map(x => `<span class="badge ${RULE_CLS[x]}">${RULE_LBL[x] || x}</span>`).join('')}</div>
      <div class="reason-box">${esc(r.reason)}</div>
      <div class="kv" style="margin-top:12px">
        <div>Billed</div><div><b>${inr(r.cost_inr)}</b> vs rate card ${inr(r.expected_cost_inr)}</div>
        <div>Amount at stake</div><div style="color:#d64545;font-weight:700">${inr(r.amount_at_risk_inr)}</div>
        <div>Method</div><div>${esc(r.repair_method)} (${esc(r.work_type)})</div>
        <div>Dates</div><div>${date(r.assigned_at)} → ${date(r.completed_at)}</div>
        <div>Linked complaints</div><div>${r.n_linked || '<span class="badge b-High">none</span>'}</div>
        <div>SLA met / fix held</div><div>${yn(r.sla_met)} / ${r.reopened_within_30d === 'Y' ? '❌ re-opened' : '✅ held'}</div>
        ${r.decided_at ? `<div>Last decision</div><div>${esc(r.status)} by ${esc(r.decided_by)} · ${esc(String(r.decided_at).replace('T', ' '))}</div>` : ''}
      </div>
      <div id="rq-trail" class="muted" style="margin-top:10px"></div>
      <textarea class="inp" id="rq-note" placeholder="Reason for your decision (goes into the audit report)…" style="margin-top:12px">${esc(r.decision_note || '')}</textarea>
      <div class="decision-row">
        <button class="btn dec red" data-dec="Verified – recover money">⚑ Confirm <kbd>C</kbd></button>
        <button class="btn dec green" data-dec="Cleared – explained">✓ Dismiss <kbd>D</kbd></button>
        <button class="btn dec amber" data-dec="Evidence requested">✉ Request evidence <kbd>E</kbd></button>
        <button class="btn dec ghost" data-dec="Escalated">⇪ Escalate <kbd>X</kbd></button></div>
      <div class="row" style="margin:12px 0 0"><button class="btn ghost small" onclick="openWO('${r.work_order_id}')">Open full work order</button>
        <button class="btn ghost small" onclick="draftNotice('workorder','${r.work_order_id}')">📨 Draft recovery notice</button></div></div>`;
    box.querySelectorAll('[data-dec]').forEach(b => b.onclick = () => decide(b.dataset.dec));
    try {
      const w = await api('/api/workorder/' + r.work_order_id);
      const tr = [...w.reviews.map(x => ({ ...x, k: 'r' })), ...w.evidence.map(x => ({ ...x, k: 'e' }))].sort((a, b) => a.at < b.at ? -1 : 1);
      const el = document.getElementById('rq-trail');
      if (el && tr.length) el.innerHTML = '<b>Trail:</b> ' + tr.map(x => `${x.k === 'r' ? '⚖️ ' + esc(x.status) : '📎 ' + esc(x.note)} <span class="muted">(${esc(x.by)})</span>`).join(' → ');
    } catch (e) { }
  };
  const decide = async status => {
    const note = document.getElementById('rq-note').value;
    const idx = rows.findIndex(x => x.work_order_id === RQ.pick);
    try {
      await post(`/api/workorder/${RQ.pick}/review`, { status, note });
      toast(`${RQ.pick} → ${status.split(' – ')[0]}`);
      const row = list.querySelector(`[data-id="${RQ.pick}"]`); if (row) row.classList.add('done-out');
      const filtered = RQ.status && status !== RQ.status;
      rows[idx] = { ...rows[idx], status, decision_note: note, decided_by: ME.email, decided_at: new Date().toISOString() };
      if (filtered) rows.splice(idx, 1);
      const next = rows[filtered ? idx : idx + 1] || rows[idx - 1];
      setTimeout(() => { RQ.pick = next ? next.work_order_id : null; paintList(); paintDetail(); refreshBadges(); }, 260);
    } catch (e) { toast(e.message); }
  };
  paintList(); paintDetail();
  document.onkeydown = e => {
    if (location.hash.slice(1) !== 'review' || ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName) || document.getElementById('modal-bg').classList.contains('open')) return;
    const i = rows.findIndex(x => x.work_order_id === RQ.pick);
    const k = e.key.toLowerCase();
    if (e.key === 'ArrowDown' || k === 'j') { e.preventDefault(); if (rows[i + 1]) { RQ.pick = rows[i + 1].work_order_id; paintList(); paintDetail(); } }
    else if (e.key === 'ArrowUp' || k === 'k') { e.preventDefault(); if (rows[i - 1]) { RQ.pick = rows[i - 1].work_order_id; paintList(); paintDetail(); } }
    else if (RQ.pick && { c: 1, d: 1, e: 1, x: 1 }[k]) decide({ c: 'Verified – recover money', d: 'Cleared – explained', e: 'Evidence requested', x: 'Escalated' }[k]);
  };
};

V.auditreport = async () => {
  const d = await api('/api/review/report');
  const c = d.counts;
  view.innerHTML = `<div class="page-title">Audit report</div>
    <div class="page-sub">Only reviewed and confirmed flags appear here — not every raw flag. That is the difference between an allegation and an audit finding.</div>
    <div class="kpis">${kpi('Confirmed findings', num(d.confirmed.length), inr(d.confirmed_amount) + ' to recover', 'warn')}${kpi('Dismissed', num(c['Cleared – explained']), 'checked, explained', 'good')}
      ${kpi('Awaiting evidence', num(c['Evidence requested']), 'contractor to respond')}${kpi('Still pending', num(c['Pending']), 'not reviewed yet')}</div>
    ${d.by_contractor.length ? `<div class="card"><h3>Confirmed amount by contractor</h3>${bars(d.by_contractor, { label: x => x.contractor_name.replace(' (synthetic)', '') + ' (' + x.n + ')', value: 'amount', fmt: inr, cls: 'red' })}</div>` : ''}
    <div class="card"><h3>Confirmed findings (${d.confirmed.length})
      <span><button class="btn ghost small" id="rep-copy">📋 Copy as text</button> <button class="btn ghost small" id="rep-dl">⬇ Download .txt</button></span></h3>
      ${d.confirmed.length ? d.confirmed.map(r => `<div class="report-block"><div class="rb-head"><span>${r.work_order_id} — ${esc(r.contractor_name)}</span><span style="color:#d64545">${inr(r.amount_at_risk_inr)}</span></div>
        <div class="rb-body">${esc(r.road_name)}, ward ${r.ward_code} · ${r.rules.map(x => RULE_LBL[x] || x).join(', ')} · <span class="badge ${ST_CLS(r.status)}">${esc(r.status)}</span><br>${esc(r.reason)}
        ${r.decision_note ? `<br><i>Auditor note: ${esc(r.decision_note)}</i>` : ''}<div class="muted">${esc(r.decided_by || '')} · ${esc(String(r.decided_at || '').replace('T', ' '))}</div></div></div>`).join('')
        : `<div class="loading">No flags confirmed yet. <button class="btn small" onclick="go('review')">Start reviewing →</button></div>`}</div>`;
  document.getElementById('rep-copy').onclick = () => navigator.clipboard.writeText(d.text).then(() => toast('Report copied'));
  document.getElementById('rep-dl').onclick = () => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([d.text], { type: 'text/plain' })); a.download = 'rastanidhi_audit_report.txt'; a.click(); };
};

// ------------------------------------------------------------------ added: Researcher prototype pages
V.season = async () => {
  const d = await api('/api/research/season');
  const o = d.overview, t = d.trend;
  view.innerHTML = pageHero('mumbai-sealink.jpg', 'The 2025 monsoon season', num(o.population / 1e6, 1) + ' million residents · ' + o.wards + ' wards', 'Capturedmumbai, CC BY-SA 4.0') + `<div class="page-title">Season overview · ${esc(o.season)}</div>
    <div class="page-sub">The 2025 monsoon road-repair season in numbers. Correlations and comparisons do not by themselves prove cause, intent or wrongdoing.</div>
    <div class="kpis">${kpi('Total spend', inr(o.spend), o.season)}${kpi('Complaints filed', num(o.complaints), num(o.open_complaints) + ' still open')}
      ${kpi('Work orders', num(o.work_orders), o.wards + ' wards · ' + o.contractors + ' contractors')}${kpi('SLA met', num(o.sla_pct, 1) + '%', 'city average')}
      ${kpi('Re-open rate', num(o.reopen_pct, 1) + '%', 'failed within 30 days', 'warn')}${kpi('Needs review', inr(o.at_risk), o.flagged + ' work orders', 'warn')}
      ${kpi('DLP payments', num(o.dlp_count), inr(o.dlp_value))}${kpi('Population covered', num(o.population / 1e6, 2) + ' M', 'all 24 wards')}</div>
    <div class="card"><h3>In one paragraph <button class="btn ghost small" id="para-copy">📋 Copy</button></h3><p class="lead-para">${esc(o.paragraph)}</p></div>
    <div class="grid2"><div class="card"><h3>Spend vs complaints, by month</h3>${comboChart(t.labels, t.spend_lakh, t.complaints)}</div>
      <div class="card"><h3>SLA met % vs re-open %, by month</h3>${lineChart([{ name: 'SLA met %', color: '#3d4280', values: t.sla_pct.map(v => v ?? 0) },
        { name: 'Re-open %', color: '#d64545', values: t.reopen_pct.map(v => v ?? 0) }], t.labels)}
        <p class="muted">October has very few jobs (the season ended early in the month), so its rates are noisy.</p></div></div>`;
  document.getElementById('para-copy').onclick = () => navigator.clipboard.writeText(o.paragraph).then(() => toast('Copied'));
};

V.wardcompare = async () => {
  const w = await api('/api/research/wards');
  view.innerHTML = `<div class="page-title">Ward comparisons</div><div class="page-sub">All 24 wards side by side. Click a column header to sort, or a row to open that ward's money trail.</div>
    <div class="grid2"><div class="card"><h3>Budget used <span class="muted">dashed line = 100%</span></h3>${bars([...w].sort((a, b) => b.budget_used_pct - a.budget_used_pct),
      { label: x => x.ward_code + ' · ' + x.ward_name.split(',')[0], value: 'budget_used_pct', fmt: v => num(v) + '%', ref: 100, cls: x => x.budget_used_pct > 100 ? 'red' : '' })}</div>
      <div class="card"><h3>Complaints per 1,000 residents <span class="muted">vs flood risk</span></h3>${bars([...w].sort((a, b) => b.complaints_per_1000 - a.complaints_per_1000),
      { label: x => x.ward_code + ' · flood ' + x.low_lying_index, value: 'complaints_per_1000', fmt: v => num(v, 2), cls: x => x.low_lying_index >= .7 ? 'alt' : '' })}</div></div>
    <div class="card"><div id="t-wc"></div></div>`;
  table('t-wc', w, [{ k: 'ward_code', l: 'Ward', f: (v, x) => `<b>${v}</b><div class="muted">${esc(x.ward_name.split(',')[0])}</div>` },
    { k: 'population_est', l: 'Population', num: true, f: num }, { k: 'low_lying_index', l: 'Flood risk', num: true },
    { k: 'budget_used_pct', l: 'Budget used', num: true, f: v => num(v) + '%' }, { k: 'complaints', l: 'Complaints', num: true, f: num },
    { k: 'complaints_per_1000', l: 'per 1,000', num: true, f: v => num(v, 2) }, { k: 'open_complaints', l: 'Open', num: true },
    { k: 'avg_fix_days', l: 'Avg days to fix', num: true, f: v => num(v, 1) }, { k: 'jobs_per_crew', l: 'Jobs / crew', num: true, f: v => num(v, 1) },
    { k: 'sla_rate', l: 'SLA met', num: true, f: v => pct(v) }, { k: 'reopen_rate', l: 'Re-open', num: true, f: v => pct(v) },
    { k: 'money_at_risk_inr', l: 'Needs review', num: true, f: inr }],
    { onClick: NAV_KEYS().includes('ward') ? x => { WARD_SEL = x.ward_code; go('ward'); } : null });
};

V.findings = async () => {
  const f = await api('/api/research/findings');
  const icon = { correlation: '📈', comparison: '⚖️', concentration: '🎯', share: '🥧', age: '⏳' };
  view.innerHTML = `<div class="page-title">Patterns & findings</div>
    <div class="page-sub">Data-backed observations worth a closer look, computed live from the same engine as every other page. The wording follows the numbers. These are leads for a story, not proof of wrongdoing: check the underlying work orders before naming anyone.</div>
    <div class="findings-grid">${f.map((x, i) => `<div class="finding-card" style="--i:${i}"><div class="finding-kind">${icon[x.kind] || '•'} ${esc(x.kind)}</div>
      <div class="finding-stat">${esc(x.stat)}</div><div class="finding-label">${esc(x.label)}</div><div class="finding-text">${esc(x.text)}</div></div>`).join('')}</div>
    ${NAV_KEYS().includes('brief') ? `<div class="row" style="margin-top:8px"><button class="btn" onclick="go('brief')">✍️ Turn these into a news brief →</button></div>` : ''}`;
};

V.brief = async () => {
  const sn = await api('/api/research/snippets');
  const saved = JSON.parse(sessionStorage.getItem('cp_brief') || 'null') || { on: sn.slice(0, 5).map(s => s.id).concat(['f0', 'f1', 'f5']), h: "Mumbai's monsoon road repair bill: where the money went", b: 'Independent analysis of BMC repair records' };
  view.innerHTML = `<div class="page-title">Report builder</div><div class="page-sub">Pick the numbers that matter and draft a news-ready brief. Every sentence comes from the live data.</div>
    <div class="grid2"><div class="card"><h3>What goes in the brief</h3><div class="checks">${sn.map(s => `<label class="check-row"><input type="checkbox" value="${s.id}" ${saved.on.includes(s.id) ? 'checked' : ''}> ${esc(s.label)}</label>`).join('')}</div>
      <label class="f" style="margin-top:14px">Headline<input class="inp" id="br-h" value="${esc(saved.h)}"></label>
      <label class="f" style="margin-top:10px">Byline<input class="inp" id="br-b" value="${esc(saved.b)}"></label></div>
      <div class="card"><h3>Draft brief <span><button class="btn ghost small" id="br-copy">📋 Copy</button> <button class="btn ghost small" id="br-dl">⬇ .txt</button></span></h3>
        <div class="brief-text" id="br-out"></div><div class="muted" id="br-words"></div></div></div>`;
  const build = () => {
    const on = [...document.querySelectorAll('.checks input:checked')].map(i => i.value);
    const h = document.getElementById('br-h').value, b = document.getElementById('br-b').value;
    sessionStorage.setItem('cp_brief', JSON.stringify({ on, h, b }));
    const body = sn.filter(s => on.includes(s.id)).map(s => s.text);
    const txt = `${h}\n${b}\n\n${body.join('\n\n')}\n\n— Based on BMC-style work order and complaint records (synthetic demo dataset). Figures are computed directly from the data; they are leads for further reporting, not findings of wrongdoing.`;
    document.getElementById('br-out').textContent = txt;
    document.getElementById('br-words').textContent = txt.split(/\s+/).length + ' words';
    return txt;
  };
  document.querySelectorAll('.checks input, #br-h, #br-b').forEach(el => el.oninput = build);
  document.getElementById('br-copy').onclick = () => navigator.clipboard.writeText(build()).then(() => toast('Brief copied'));
  document.getElementById('br-dl').onclick = () => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([build()], { type: 'text/plain' })); a.download = 'rastanidhi_brief.txt'; a.click(); };
  build();
};

// ------------------------------------------------------------------ added: project & work tracking (REQUIREMENTS.md §7)
const STAGE_ICON = { done: '✓', warn: '!', current: '•', todo: '' };
function trackerHTML(t) {
  const n = t.stages.length;
  return `<div class="trk ${t.tone}">
    <div class="trk-head"><div><div class="trk-id">${esc(t.id)} · ${{ work_order: 'Work order', complaint: 'BMC complaint', report: 'RastaNidhi report' }[t.kind] || ''}</div>
      <div class="trk-title">${esc(t.title)}</div><div class="trk-sub">${esc(t.subtitle || '')}</div></div>
      <div class="trk-status"><span class="trk-pill">${esc(t.status)}</span><div class="trk-ring" style="--p:${t.progress}"><b>${t.progress}%</b></div></div></div>
    ${t.description ? `<p class="trk-desc">“${esc(t.description)}”</p>` : ''}
    <div class="trk-steps" style="--n:${n}">${t.stages.map((s, i) => `<div class="trk-step ${s.state}" style="--i:${i}">
      <div class="trk-dot">${STAGE_ICON[s.state]}</div><div class="trk-lbl">${esc(s.label)}</div>
      <div class="trk-at">${esc(s.at || (s.state === 'todo' ? 'Pending' : s.state === 'current' ? 'Now' : ''))}</div>
      ${s.detail ? `<div class="trk-det">${esc(s.detail)}</div>` : ''}</div>`).join('')}</div>
    <div class="trk-next"><b>What happens next</b><span>${esc(t.next || '')}</span></div></div>`;
}

let TRACK_Q = '';
V.track = async () => {
  const sug = await api('/api/track/suggest');
  const chips = (title, list) => list.length ? `<div class="trk-sug"><b>${title}</b>${list.map(x => `<button class="trk-chip" data-q="${esc(x.id)}">${esc(x.id)} <span>${esc(x.label)}</span>${x.status ? `<em>${esc(x.status)}</em>` : ''}</button>`).join('')}</div>` : '';
  view.innerHTML = `<div class="page-title">📦 Track status</div>
    <div class="page-sub">Follow any complaint, citizen report or repair job from the moment it was reported to the 30-day check on whether the fix held — like tracking a parcel.</div>
    <div class="card trk-search"><div class="row" style="margin:0;flex-wrap:nowrap">
      <input class="inp" id="tq" placeholder="Enter an ID: BMC25-000005 · WO25-00012 · CP-00001 · ISS-00012" value="${esc(TRACK_Q)}" style="flex:1;font-size:15px;padding:12px 14px">
      <button class="btn" id="tgo">Track</button></div>
      ${chips(ME.role === 'Citizen' ? 'My reports' : 'Citizen reports', sug.reports)}
      ${chips(ME.role === 'Contractor' ? 'My recent jobs' : 'Recent repair jobs', sug.work_orders)}
      ${chips('Open complaints', sug.complaints)}</div>
    <div id="trk-out"></div>`;
  const run = async q => {
    TRACK_Q = q = (q || '').trim(); if (!q) return;
    document.getElementById('tq').value = q;
    const out = document.getElementById('trk-out'); out.innerHTML = '<div class="skel"><i class="b"></i></div>';
    try {
      const t = await api('/api/track?q=' + encodeURIComponent(q), { keep: true });
      out.innerHTML = trackerHTML(t) + `<div class="grid2">
        <div class="card"><h3>Details</h3>${t.facts ? `<div class="kv">${t.facts.map(([a, b]) => `<div>${esc(a)}</div><div><b>${esc(b)}</b></div>`).join('')}</div>` : '<p class="muted">No work order linked yet.</p>'}
          ${t.flags && t.flags.length ? `<div class="note" style="margin-top:12px"><b>${ME.role === 'Citizen' ? 'Verified audit finding' : 'Audit flags'}:</b><br>${t.flags.map(esc).join('<br>')}</div>` : ''}
          <div class="row" style="margin:14px 0 0">${t.work_order && t.kind !== 'work_order' ? `<button class="btn ghost small" data-q="${esc(t.work_order)}">Track ${esc(t.work_order)} →</button>` : ''}
          ${t.kind === 'work_order' && can('Admin', 'Ward Officer', 'Auditor / Verifier') ? `<button class="btn ghost small" onclick="openWO('${t.id}')">Open full work order</button>` : ''}</div></div>
        <div class="card"><h3>Activity</h3>${(t.events || []).length ? `<div class="timeline">${t.events.map(e => `<div><div class="t">${esc(String(e.at).replace('T', ' ').slice(0, 16))}${e.who ? ' · ' + esc(e.who) : ''}</div>${e.icon || ''} ${esc(e.text)}</div>`).join('')}</div>`
          : '<p class="muted">No actions recorded in RastaNidhi yet. The stages above come from the official work-order record.</p>'}
          ${t.linked ? `<h3 style="margin-top:16px">Linked repair ${esc(t.linked.id)} · ${esc(t.linked.status)}</h3><div class="trk-mini">${t.linked.stages.map(s => `<span class="${s.state}" title="${esc(s.detail || '')}">${esc(s.label)}</span>`).join('')}</div>` : ''}</div></div>`;
      out.querySelectorAll('[data-q]').forEach(b => b.onclick = () => run(b.dataset.q));
      out.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) { if (!e.stale) out.innerHTML = `<div class="note error">⚠️ ${esc(e.message)}</div>`; }
  };
  document.getElementById('tgo').onclick = () => run(document.getElementById('tq').value);
  document.getElementById('tq').onkeydown = e => { if (e.key === 'Enter') run(e.target.value); };
  view.querySelectorAll('.trk-chip').forEach(b => b.onclick = () => run(b.dataset.q));
  const first = TRACK_Q || (sug.reports[0] && sug.reports[0].id) || '';
  if (first) run(first);
};
function trackId(id) { TRACK_Q = id; go('track'); }

// Citizen view: pick a ward → one plain-language summary. No KPI walls, funnels or charts.
let CP_SEL = null, CP_Q = '';
async function citizenProjects() {
  const ps = await api('/api/projects');
  const tone = { 'On track': ['ok', 'Within budget'], 'Near limit': ['warn', 'Almost used up'], 'Over budget': ['bad', 'Over budget'], Closed: ['off', 'Closed'] };
  const pill = p => { const [c, l] = tone[p.health] || ['off', p.health]; return `<span class="cp-pill ${c}">${l}</span>`; };
  const name = p => esc(p.ward_name.split(',')[0]);
  const sel = CP_SEL && ps.find(p => p.id === CP_SEL);

  if (!sel) {
    const mine = ME.ward ? ps.filter(p => p.ward_code === ME.ward) : [];
    view.innerHTML = `<div class="cp">
      <div class="page-title">🏗️ Ward projects</div>
      <div class="page-sub">Pick a ward to see how its road-repair money was used.</div>
      ${mine.length ? `<div class="cp-label">Your ward</div><div class="cp-list">${mine.map(row).join('')}</div>` : ''}
      <div class="cp-search"><span>🔍</span><input id="cp-q" placeholder="Search by ward name or code" value="${esc(CP_Q)}" autocomplete="off"></div>
      <div class="cp-label">All wards</div><div class="cp-list" id="cp-list"></div></div>`;
    const paint = () => {
      const q = CP_Q.trim().toLowerCase();
      const hits = ps.filter(p => !q || p.ward_code.toLowerCase().includes(q) || p.ward_name.toLowerCase().includes(q))
        .sort((a, b) => a.ward_code.localeCompare(b.ward_code));
      const box = document.getElementById('cp-list');
      box.innerHTML = hits.map(row).join('') || '<p class="muted" style="padding:14px">No ward matches that search.</p>';
      bind(box);
    };
    const bind = el => el.querySelectorAll('[data-p]').forEach(r => r.onclick = () => { CP_SEL = r.dataset.p; go('projects'); });
    const qi = document.getElementById('cp-q');
    qi.oninput = () => { CP_Q = qi.value; paint(); };
    bind(view); paint();
    return;
  }
  function row(p) {
    const u = Math.min(100, p.utilization_pct);
    return `<button class="cp-row" data-p="${p.id}"><span class="cp-code">${esc(p.ward_code)}</span>
      <span class="cp-name"><b>${name(p)}</b><small>${esc(p.season)}</small></span>
      <span class="cp-mini"><i class="${tone[p.health]?.[0] || ''}" style="width:${u}%"></i></span>
      ${pill(p)}<span class="cp-go">›</span></button>`;
  }

  // ---- one ward
  view.innerHTML = `<div class="cp"><button class="cp-back" id="cp-back">← All wards</button><div id="cp-body"><div class="skel"><i class="b"></i></div></div></div>`;
  document.getElementById('cp-back').onclick = () => { CP_SEL = null; go('projects'); };
  const d = await api('/api/projects/' + encodeURIComponent(sel.id)), p = d.project;
  const held = p.jobs ? Math.round(p.jobs_held / p.jobs * 100) : null;
  const label = { 'Fix held': ['ok', 'Lasted'], 'Fix failed': ['bad', 'Broke again'], 'Under watch': ['off', 'Being checked'], 'Awaiting sign-off': ['warn', 'Awaiting check'] };
  const verdict = held === null ? 'No repair work has been recorded for this ward yet.'
    : held >= 85 ? 'Most repairs here are lasting. 👍'
    : held >= 70 ? 'Most repairs are lasting, but some broke again within a month.'
    : 'Many repairs here broke again within a month. ⚠️';
  let shown = 5;
  document.getElementById('cp-body').innerHTML = `
    <div class="cp-hero">
      <div class="cp-hero-top"><div><div class="cp-ward">Ward ${esc(p.ward_code)} · ${name(p)}</div><div class="muted">${esc(p.season)}</div></div>${pill(p)}</div>
      <p class="cp-sentence"><b>${inr(p.allocated_inr)}</b> was set aside for road repairs.<br><b>${inr(p.spent_inr)}</b> has been spent so far.</p>
      <div class="cp-bar"><i class="${tone[p.health]?.[0] || ''}" style="width:${Math.min(100, p.utilization_pct)}%"></i></div>
      <div class="cp-bar-cap"><span>${num(p.utilization_pct)}% used</span><span>${p.remaining_inr < 0 ? inr(-p.remaining_inr) + ' over budget' : inr(p.remaining_inr) + ' left'}</span></div>
    </div>
    <div class="cp-tiles">
      <div class="cp-tile"><span>🛠️</span><b>${num(p.jobs)}</b><small>repairs done</small></div>
      <div class="cp-tile"><span>✅</span><b>${held === null ? '–' : held + '%'}</b><small>repairs that lasted a month</small></div>
      <div class="cp-tile ${p.issues_open ? 'warn' : ''}"><span>⏳</span><b>${num(p.issues_open)}</b><small>problems still waiting</small></div>
    </div>
    <div class="cp-verdict">${verdict}</div>
    <div class="card"><h3>Latest repairs <span class="muted">tap one to track it</span></h3><div id="cp-works"></div></div>
    <div class="cp-cta"><span>Something wrong on a road in this ward?</span>
      <button class="btn" onclick="go('reports')">Report a problem</button><button class="btn ghost" onclick="go('track')">Track my complaint</button></div>`;
  const paintWorks = () => {
    const box = document.getElementById('cp-works');
    box.innerHTML = d.works.slice(0, shown).map(w => { const [c, l] = label[w.status] || ['off', w.status];
      return `<button class="cp-work" data-t="${w.work_order_id}"><span><b>${esc(w.road)}</b><small>${esc(w.type)} · ${esc(w.completed)}</small></span><span class="cp-pill ${c}">${l}</span></button>`; }).join('')
      || '<p class="muted">No repairs recorded yet.</p>';
    if (d.works.length > shown) box.insertAdjacentHTML('beforeend', `<button class="btn ghost small cp-more">Show more</button>`);
    box.querySelectorAll('[data-t]').forEach(el => el.onclick = () => trackId(el.dataset.t));
    const m = box.querySelector('.cp-more'); if (m) m.onclick = () => { shown += 10; paintWorks(); };
  };
  paintWorks();
}

let PROJ_SEL = null, PROJ_F = 'all';
V.projects = async () => {
  if (ME.role === 'Citizen') return citizenProjects();
  const ps = await api('/api/projects');
  const isAdmin = ME.role === 'Admin', cit = ME.role === 'Citizen';
  const tot = ps.reduce((a, p) => ({ alloc: a.alloc + p.allocated_inr, spent: a.spent + p.spent_inr, open: a.open + p.issues_open, jobs: a.jobs + p.jobs }), { alloc: 0, spent: 0, open: 0, jobs: 0 });
  const health = { 'On track': 'green', 'Near limit': 'amber', 'Over budget': 'red', Closed: 'grey' };
  const list = ps.filter(p => PROJ_F === 'all' || p.health === PROJ_F).sort((a, b) => b.utilization_pct - a.utilization_pct);
  view.innerHTML = `<div class="row" style="justify-content:space-between"><div><div class="page-title">🏗️ ${cit ? 'Ward projects' : 'Projects'}</div>
      <div class="page-sub">A project is one ward's budget allocation for a season. Live spend, finished work and what is still open — updated from the same records as every other page.</div></div>
      ${isAdmin ? '<button class="btn" id="np-btn">＋ New project</button>' : ''}</div>
    ${isAdmin ? `<div class="card" id="np-form" style="display:none"><h3>New project <span class="muted">a ward budget allocation (REQUIREMENTS §7.1)</span></h3><div class="grid3">
      <label class="f">Ward<select class="sel" id="np-w">${OPTIONS.wards.map(w => `<option value="${w.ward_code}">${w.ward_code} – ${esc(w.ward_name)}</option>`).join('')}</select></label>
      <label class="f">Season<input class="inp" id="np-s" value="2025 Post-monsoon"></label>
      <label class="f">Allocation (₹)<input class="inp" id="np-a" type="number" step="50000" value="2500000"></label></div>
      <label class="f" style="margin-top:10px">Notes<input class="inp" id="np-n" placeholder="e.g. Resurface the chronic roads instead of patching"></label>
      <div class="row" style="margin:12px 0 0"><button class="btn" id="np-save">Create project</button><span class="muted">New-season projects start with ₹0 spent: the dataset only covers the 2025 monsoon.</span></div></div>` : ''}
    <div class="kpis">${kpi(ps.length === 1 ? 'Project' : 'Projects', num(ps.length), ME.role === 'Ward Officer' ? 'your ward' : 'across ' + new Set(ps.map(p => p.ward_code)).size + ' wards')}
      ${kpi('Allocated', inr(tot.alloc))}${kpi('Spent', inr(tot.spent), num(tot.alloc ? tot.spent / tot.alloc * 100 : 0) + '% used', tot.spent > tot.alloc ? 'warn' : '')}
      ${kpi('Repair jobs done', num(tot.jobs))}${kpi('Issues still open', num(tot.open), 'no work order yet', 'warn')}</div>
    ${ps.length > 1 ? `<div class="row">${['all', 'On track', 'Near limit', 'Over budget', 'Closed'].map(h => `<button class="btn small ${PROJ_F === h ? '' : 'ghost'}" data-h="${h}">${h === 'all' ? 'All' : h} <span class="muted">${h === 'all' ? ps.length : ps.filter(p => p.health === h).length}</span></button>`).join('')}</div>` : ''}
    <div class="proj-grid">${list.map((p, i) => `<div class="proj-card ${PROJ_SEL === p.id ? 'sel' : ''}" data-p="${p.id}" style="--i:${i}">
      <div class="proj-top"><div><b>Ward ${esc(p.ward_code)}</b><span>${esc(p.ward_name.split(',')[0])} · ${esc(p.season)}</span></div><span class="chip ${health[p.health]}">${esc(p.health)}</span></div>
      <div class="proj-bar"><i class="${p.utilization_pct > 100 ? 'over' : p.utilization_pct > 90 ? 'warn' : ''}" style="width:${Math.min(100, p.utilization_pct)}%"></i></div>
      <div class="proj-money"><span>${inr(p.spent_inr)} of ${inr(p.allocated_inr)}</span><b>${num(p.utilization_pct)}%</b></div>
      <div class="proj-stats"><div><b>${num(p.jobs)}</b><span>jobs done</span></div><div><b>${p.jobs ? pct(p.jobs_held / p.jobs) : '–'}</b><span>fixes held</span></div>
        <div><b>${num(p.issues_open)}</b><span>open issues</span></div>${!cit ? `<div><b>${num(p.submissions_pending)}</b><span>to sign off</span></div>` : ''}</div>
      ${p.seeded ? '' : '<div class="muted" style="font-size:11px;margin-top:6px">Created in RastaNidhi by ' + esc(p.created_by || '') + '</div>'}</div>`).join('') || '<p class="muted">No projects match.</p>'}</div>
    <div id="proj-detail"></div>`;
  view.querySelectorAll('[data-h]').forEach(b => b.onclick = () => { PROJ_F = b.dataset.h; go('projects'); });
  if (isAdmin) {
    document.getElementById('np-btn').onclick = () => { const f = document.getElementById('np-form'); f.style.display = f.style.display === 'none' ? '' : 'none'; };
    document.getElementById('np-save').onclick = async () => {
      try { const p = await post('/api/projects', { ward_code: document.getElementById('np-w').value, season: document.getElementById('np-s').value,
          allocated_inr: +document.getElementById('np-a').value, notes: document.getElementById('np-n').value });
        toast(`${p.id} created`); PROJ_SEL = p.id; go('projects'); } catch (e) { toast(e.message); }
    };
  }
  const open = async id => {
    PROJ_SEL = id; view.querySelectorAll('.proj-card').forEach(c => c.classList.toggle('sel', c.dataset.p === id));
    const box = document.getElementById('proj-detail'); box.innerHTML = '<div class="skel"><i class="b"></i></div>';
    try {
      const d = await api('/api/projects/' + encodeURIComponent(id), { keep: true }), p = d.project;
      const fmax = Math.max(1, ...d.funnel.map(f => f[1]));
      const st = { 'Fix held': 'b-Cleared', 'Fix failed': 'b-High', 'Under watch': 'b-Evidence', 'Awaiting sign-off': 'b-Medium' };
      box.innerHTML = `<div class="card proj-detail"><h3>${esc(p.id)} · Ward ${esc(p.ward_code)} — ${esc(p.season)}
          <span>${isAdmin ? `<button class="btn ghost small" id="pd-edit">✎ Edit allocation</button> <button class="btn ghost small" id="pd-close">${p.status === 'closed' ? 'Re-open' : 'Close project'}</button>` : ''}</span></h3>
        ${p.notes ? `<p class="muted" style="margin:-4px 0 12px">${esc(p.notes)}</p>` : ''}
        <div class="kpis">${kpi('Allocated', inr(p.allocated_inr))}${kpi('Spent', inr(p.spent_inr), num(p.utilization_pct) + '% used', p.utilization_pct > 100 ? 'warn' : '')}
          ${kpi(p.remaining_inr < 0 ? 'Over by' : 'Remaining', inr(Math.abs(p.remaining_inr)), '', p.remaining_inr < 0 ? 'warn' : 'good')}${kpi('SLA met', num(p.sla_met_pct) + '%')}
          ${kpi('Fixes held 30 days', p.jobs ? pct(p.jobs_held / p.jobs) : '–', p.jobs_failed + ' failed')}${!cit ? kpi('Flags to review', num(p.flags_pending_review)) : ''}</div>
        <div class="grid2"><div><h3>From complaint to lasting fix</h3><div class="funnel">${d.funnel.map(([l, v], i) => `<div style="--w:${v / fmax * 100}%;--i:${i}"><span>${esc(l)}</span><b>${num(v)}</b></div>`).join('')}</div>
            <h3 style="margin-top:16px">Work by month</h3>${d.monthly.length ? stackBars(d.monthly.map(m => ({ ...m, ok: m.jobs - m.failed })), 'month', [{ k: 'ok', name: 'Fix held', color: '#3d4280' }, { k: 'failed', name: 'Fix failed', color: '#d64545' }]) : '<p class="muted">No work yet in this project.</p>'}</div>
          <div><h3>Recent works <span class="muted">click to track</span></h3><div class="proj-works">${d.works.slice(0, 40).map(w => `<div class="pw" data-t="${w.work_order_id}">
            <div><b>${esc(w.work_order_id)}</b> · ${esc(w.type)}<br><span>${esc(w.road)} · ${esc(w.contractor.replace(' (synthetic)', ''))} · ${esc(w.completed)}</span></div>
            <div style="text-align:right"><span class="badge ${st[w.status] || 'b-Low'}">${esc(w.status)}</span><br><span>${inr(w.cost)}</span></div></div>`).join('') || '<p class="muted">No works yet.</p>'}</div></div></div></div>`;
      box.querySelectorAll('[data-t]').forEach(el => el.onclick = () => trackId(el.dataset.t));
      if (isAdmin) {
        document.getElementById('pd-edit').onclick = async () => { const v = prompt('New allocation in ₹', Math.round(p.allocated_inr)); if (!v) return;
          try { await api('/api/projects/' + encodeURIComponent(p.id), { method: 'PATCH', body: JSON.stringify({ allocated_inr: +v }) }); toast('Allocation updated'); go('projects'); } catch (e) { toast(e.message); } };
        document.getElementById('pd-close').onclick = async () => {
          try { await api('/api/projects/' + encodeURIComponent(p.id), { method: 'PATCH', body: JSON.stringify({ status: p.status === 'closed' ? 'active' : 'closed' }) }); toast('Saved'); go('projects'); } catch (e) { toast(e.message); } };
      }
      box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) { if (!e.stale) box.innerHTML = `<div class="note error">⚠️ ${esc(e.message)}</div>`; }
  };
  view.querySelectorAll('.proj-card').forEach(c => c.onclick = () => open(c.dataset.p));
  if (PROJ_SEL && ps.find(p => p.id === PROJ_SEL)) open(PROJ_SEL); else if (ps.length === 1) open(ps[0].id);
};

V.submissions = async () => {
  const subs = await api('/api/work-submissions');
  const pend = subs.filter(s => !s.review), done = subs.filter(s => s.review);
  view.innerHTML = `<div class="page-title">✅ Contractor submissions</div>
    <div class="page-sub">Contractors report progress on their work orders here (REQUIREMENTS §7.2–7.3). Approve the work or send it back — the contractor and the citizen tracker see your decision straight away.</div>
    <div class="kpis">${kpi('Waiting for you', num(pend.length), '', pend.length ? 'warn' : 'good')}${kpi('Approved', num(done.filter(s => s.review === 'Approved').length))}${kpi('Sent back', num(done.filter(s => s.review === 'Sent back').length))}</div>
    <div class="card"><h3>Waiting for sign-off</h3>${pend.length ? pend.map(s => `<div class="sub-row" data-id="${s.id}">
      <div class="sub-main"><b>${esc(s.work_order_id)}</b> · ${esc(s.road || '')} <span class="muted">· ward ${esc(s.ward_code)} · ${esc(String(s.contractor || '').replace(' (synthetic)', ''))}</span>
        <div><span class="badge ${s.status.startsWith('Completed') ? 'b-Cleared' : 'b-Evidence'}">${esc(s.status)}</span> “${esc(s.note)}”</div>
        <div class="muted">${esc(s.by)} · ${esc(s.at.replace('T', ' ').slice(0, 16))}</div></div>
      <div class="sub-act"><input class="inp" placeholder="Note (optional)" data-n="${s.id}">
        <button class="btn small dec green" data-d="Approved" data-s="${s.id}">✓ Approve</button><button class="btn small dec red" data-d="Sent back" data-s="${s.id}">↩ Send back</button>
        <button class="btn ghost small" onclick="trackId('${s.work_order_id}')">Track</button></div></div>`).join('') : '<p class="muted">Nothing waiting. 🎉</p>'}</div>
    <div class="card"><h3>Decided</h3><div id="t-subs"></div></div>`;
  view.querySelectorAll('[data-d]').forEach(b => b.onclick = async () => {
    try { await api('/api/work-submissions/' + b.dataset.s, { method: 'PATCH', body: JSON.stringify({ decision: b.dataset.d, note: view.querySelector(`[data-n="${b.dataset.s}"]`).value }) });
      toast(`${b.dataset.d}`); refreshBadges(); go('submissions'); } catch (e) { toast(e.message); }
  });
  table('t-subs', done, [{ k: 'work_order_id', l: 'Work order' }, { k: 'road', l: 'Road' }, { k: 'status', l: 'Contractor said' }, { k: 'note', l: 'Note' },
    { k: 'review', l: 'Decision', f: v => `<span class="badge ${v === 'Approved' ? 'b-Cleared' : 'b-High'}">${esc(v)}</span>` }, { k: 'review_note', l: 'Officer note' },
    { k: 'reviewed_by', l: 'By' }], { search: false, empty: 'No decisions yet.', onClick: r => trackId(r.work_order_id) });
};

async function submitProgress(wid) {
  openModal(`<div class="page-title">Submit progress · ${esc(wid)}</div><div class="page-sub">Your update goes to the ward officer's sign-off queue and shows on the public tracker.</div>
    <label class="f">Status<select class="sel" id="sp-s"><option>Completed – awaiting sign-off</option><option>In progress</option></select></label>
    <label class="f" style="margin-top:10px">What was done<textarea class="inp" id="sp-n" placeholder="e.g. Patched 6 sqm with hot mix, rolled and compacted. Photos shared with JE."></textarea></label>
    <div class="row" style="margin:12px 0 0"><button class="btn" id="sp-go">Submit</button><span class="muted">Demo: no photo upload (REQUIREMENTS §2).</span></div>`);
  document.getElementById('sp-go').onclick = async () => {
    try { await post('/api/work-submissions', { work_order_id: wid, status: document.getElementById('sp-s').value, note: document.getElementById('sp-n').value });
      toast('Submitted for sign-off'); closeModal(); go('jobs'); } catch (e) { toast(e.message); }
  };
}

// ------------------------------------------------------------------ Aamchi Road Audit AI (ChromaDB RAG + DuckDB SQL + Gemini)
const RB_CHAT = [];
V.roadbot = async () => {
  const st = await api('/api/roadbot/status');
  const persona = sessionStorage.getItem('cp_rb_persona');
  const cur = st.choices.includes(persona) ? persona : st.persona;
  const banner = st.error ? `<div class="note error">⚠️ Index failed to build: ${esc(st.error)}</div>`
    : !st.ready ? `<div class="note">⏳ Building the search index (first start ≈ 30 s)… you can already type; this page refreshes when ready.</div>`
    : !st.gemini_key ? `<div class="note">🔑 No Gemini key yet, so answers are <b>retrieval-only</b> (the most relevant dataset passages). ${ME.role === 'Admin' ? 'Add the key under <a href="#users">Users & roles</a>.' : 'Ask an admin to add the Gemini key.'}</div>` : '';
  const sugg = {
    Citizen: ['What happened to complaint BMC25-000005?', 'Which contractor fixed potholes in Kurla and did they hold?'],
    Corporator: ['Give me the money trail for ward E', 'How much was spent on fixes that failed within 30 days?'],
    'Ward Officer': ['List under-DLP repairs that BMC paid for in my ward', 'Which jobs billed above 1.5x the rate card?'],
    'Judge / Auditor': ['Top 5 duplicate bills without a linked complaint', 'Which ward should get the next rupee and why?'],
  }[cur] || [];
  view.innerHTML = `<div class="page-title">🤖 Road Audit AI</div>
    <div class="page-sub">Ask anything about Mumbai's monsoon road repairs. Answers are grounded in the dataset: semantic search over the docs (ChromaDB) and live SQL over every table (DuckDB), written by Gemini in your role's style.</div>
    ${banner}
    <div class="card"><div class="row" style="justify-content:space-between;margin:0 0 10px">
        <div class="rb-chips">${st.choices.map(c => `<button class="btn small ${c === cur ? '' : 'ghost'}" data-p="${esc(c)}">${esc(c)}</button>`).join('')}</div>
        <span class="muted">${st.ready ? `${num(st.vectors)} vectors · ${st.tables} tables` : 'index building…'} · ${st.gemini_key ? '🟢 Gemini' : '⚪ retrieval-only'}</span></div>
      <div class="chat" id="rb-chat"></div>
      <div class="chat-in"><input class="inp" id="rb-q" placeholder="Ask the road audit… (e.g. Which ward overspent and on what?)"><button class="btn" id="rb-send">Ask</button></div>
      <div class="suggest">${sugg.map(x => `<span>${esc(x)}</span>`).join('')}</div></div>`;
  view.querySelectorAll('[data-p]').forEach(b => b.onclick = () => { sessionStorage.setItem('cp_rb_persona', b.dataset.p); go('roadbot'); });
  const box = document.getElementById('rb-chat');
  const paint = () => {
    box.innerHTML = RB_CHAT.length ? RB_CHAT.map(m => m.role === 'user' ? `<div class="msg user">${esc(m.text)}</div>` :
      `<div class="msg bot">${md(m.text)}${m.meta ? `<details><summary>Grounding · ${esc(m.meta.mode)}${m.meta.model ? ' · ' + esc(m.meta.model) : ''} · ${m.meta.sql_queries.length} SQL · ${m.meta.rag_hits.length} passages</summary>
        ${m.meta.sql_queries.length ? `<b>SQL run</b><pre>${esc(m.meta.sql_queries.join('\n\n'))}</pre>` : ''}<b>Passages</b><pre>${esc(m.meta.rag_hits.join('\n'))}</pre></details>` : ''}</div>`).join('')
      : `<div class="muted" style="text-align:center;padding:40px">Persona: <b>${esc(cur)}</b>. ${cur === 'Citizen' ? 'Answers come in English, हिन्दी and मराठी.' : 'Ask for IDs, numbers and context.'}</div>`;
    box.scrollTop = box.scrollHeight;
  };
  const send = async q => {
    q = (q || '').trim(); if (!q) return;
    RB_CHAT.push({ role: 'user', text: q }); RB_CHAT.push({ role: 'bot', text: '_Searching the data…_' }); paint();
    try {
      const r = await post('/api/roadbot', { message: q, persona: cur });
      RB_CHAT[RB_CHAT.length - 1] = { role: 'bot', text: r.reply, meta: r };
    } catch (e) { RB_CHAT[RB_CHAT.length - 1] = { role: 'bot', text: '⚠️ ' + e.message }; }
    paint();
  };
  document.getElementById('rb-send').onclick = () => { const i = document.getElementById('rb-q'); send(i.value); i.value = ''; };
  document.getElementById('rb-q').onkeydown = e => { if (e.key === 'Enter') document.getElementById('rb-send').click(); };
  view.querySelectorAll('.suggest span').forEach(x => x.onclick = () => send(x.textContent));
  paint();
  if (!st.ready && !st.error) setTimeout(() => { if (location.hash.slice(1) === 'roadbot') go('roadbot'); }, 8000);
};

// ------------------------------------------------------------------ floating assistant (from both prototypes)
const ASSIST_SUGG = {
  'Ward Officer': ['Budget remaining?', 'Top risk road?', 'Recovery total?', 'Worst contractor here?', 'Oldest open complaint?'],
  'Contractor': ['How am I doing?'],
  default: ['Worst ward?', 'Riskiest contractor?', 'How much is at risk?', 'DLP violations?', 'Open complaints?'],
};
function setupAssistant() {
  if (ME.role === 'Citizen' || document.getElementById('cp-bubble')) return;
  document.body.insertAdjacentHTML('beforeend', `<div id="cp-bubble" title="Ask the RastaNidhi assistant">💬</div>
    <div id="cp-panel"><div id="cp-head"><b>RastaNidhi assistant · ${esc(ME.role)}</b><span onclick="toggleAssistant(false)">×</span></div>
      <div id="cp-msgs"></div><div id="cp-sugg">${(ASSIST_SUGG[ME.role] || ASSIST_SUGG.default).map(s => `<span>${esc(s)}</span>`).join('')}</div>
      <div id="cp-in"><input class="inp" id="cp-q" placeholder="Ask about this data…"><button class="btn small" id="cp-send">Ask</button></div></div>`);
  const msgs = document.getElementById('cp-msgs');
  const add = (who, html) => { msgs.insertAdjacentHTML('beforeend', `<div class="cp-msg ${who}">${html}</div>`); msgs.scrollTop = msgs.scrollHeight; };
  add('bot', `Hi! I answer from the live RastaNidhi data${ME.role === 'Ward Officer' ? ' for ward <b>' + esc(ME.ward) + '</b>' : ''}. Try a suggestion below.`);
  const send = async q => {
    if (!q.trim()) return;
    add('user', esc(q)); add('bot', '<i>…</i>');
    try { const r = await post('/api/assistant', { q }); msgs.lastElementChild.innerHTML = md(r.answer); }
    catch (e) { msgs.lastElementChild.textContent = '⚠️ ' + e.message; }
    msgs.scrollTop = msgs.scrollHeight;
  };
  document.getElementById('cp-send').onclick = () => { const i = document.getElementById('cp-q'); send(i.value); i.value = ''; };
  document.getElementById('cp-q').onkeydown = e => { if (e.key === 'Enter') document.getElementById('cp-send').click(); };
  document.querySelectorAll('#cp-sugg span').forEach(s => s.onclick = () => send(s.textContent));
  const bubble = document.getElementById('cp-bubble'), panel = document.getElementById('cp-panel');
  draggable(bubble, () => toggleAssistant(!panel.classList.contains('open')));
  draggable(document.getElementById('cp-head'), null, panel);
}
function toggleAssistant(open) {
  const panel = document.getElementById('cp-panel'), b = document.getElementById('cp-bubble').getBoundingClientRect();
  panel.classList.toggle('open', open);
  if (open && !panel.dataset.moved) {
    panel.style.left = Math.max(10, Math.min(b.right - 340, innerWidth - 350)) + 'px';
    panel.style.top = Math.max(70, b.top - 452) + 'px';
  }
}
function draggable(handle, onClick, target = handle) {
  let sx, sy, ox, oy, moved = false, down = false;
  handle.addEventListener('pointerdown', e => {
    if (e.target.tagName === 'SPAN' && handle.id === 'cp-head') return;
    down = true; moved = false; handle.setPointerCapture(e.pointerId);
    const r = target.getBoundingClientRect(); sx = e.clientX; sy = e.clientY; ox = r.left; oy = r.top; handle.classList.add('dragging');
  });
  handle.addEventListener('pointermove', e => {
    if (!down) return;
    const dx = e.clientX - sx, dy = e.clientY - sy;
    if (Math.abs(dx) + Math.abs(dy) > 5) moved = true;
    if (!moved) return;
    target.style.left = Math.max(4, Math.min(ox + dx, innerWidth - target.offsetWidth - 4)) + 'px';
    target.style.top = Math.max(4, Math.min(oy + dy, innerHeight - target.offsetHeight - 4)) + 'px';
    target.style.right = target.style.bottom = 'auto';
    if (target.id === 'cp-panel') target.dataset.moved = '1';
  });
  handle.addEventListener('pointerup', () => { down = false; handle.classList.remove('dragging'); if (!moved && onClick) onClick(); });
}

// ------------------------------------------------------------------ navigation per role (sectioned, with badges)
const ITEMS = {
  overview: ['🏠', 'City overview'], alerts: ['🚨', 'Alerts'], ward: ['💰', 'Ward money trail'], audit: ['🔍', 'Repair auditor'],
  scorecards: ['📋', 'Scorecards'], jobs: ['🧰', 'My jobs'], planner: ['🧭', 'Next-rupee planner'], roads: ['🛣️', 'Roads & risk'],
  models: ['🤖', 'ML model card'], issues: ['🔗', 'Complaint linker'], complaints: ['📨', 'Complaints'], datahealth: ['🩺', 'Data health'],
  social: ['📣', 'Social pulse'], ask: ['💬', 'Mera Complaint'], reports: ['📝', 'Citizen reports'], users: ['🛡️', 'Users & roles'], settings: ['⚙️', 'Settings'],
  map: ['🗺️', 'Ward map'], track: ['📦', 'Track status'], projects: ['🏗️', 'Projects'], submissions: ['✅', 'Contractor submissions'], reviewdash: ['📊', 'Review dashboard'], review: ['✅', 'Review queue'], auditreport: ['📄', 'Audit report'],
  roadbot: ['🤖', 'Road Audit AI'], season: ['🌧️', 'Season overview'], wardcompare: ['🗺️', 'Ward comparisons'], findings: ['💡', 'Patterns & findings'], brief: ['✍️', 'Report builder'],
};
const NAV = {
  'Admin': [['Overview', ['overview', 'map', 'alerts', 'season']], ['Projects & work', ['projects', 'track', 'submissions']],
    ['Oversight', ['review', 'reviewdash', 'audit', 'auditreport', 'scorecards', 'ward']],
    ['Plan & budget', ['planner', 'roads', 'models']], ['Research', ['findings', 'wardcompare', 'brief']],
    ['Citizens & data', ['roadbot', 'complaints', 'issues', 'reports', 'ask', 'social', 'datahealth']], ['System', ['users', 'settings']]],
  'Ward Officer': [['My ward', ['ward', 'map', 'projects']], ['Plan & budget', ['planner', 'roads']], ['Oversight', ['submissions', 'audit', 'track']],
    ['Citizens', ['roadbot', 'complaints', 'reports', 'issues', 'ask']]],
  'Contractor': [['My work', ['jobs', 'track', 'scorecards', 'audit']]],
  'Auditor / Verifier': [['Overview', ['reviewdash', 'overview', 'map', 'alerts']], ['Work', ['review', 'audit', 'auditreport']],
    ['Context', ['roadbot', 'track', 'projects', 'scorecards', 'complaints', 'issues', 'datahealth']]],
  'Citizen': [['Citizen services', ['track', 'reports', 'roadbot', 'ask', 'projects', 'ward']]],
  'Researcher': [['Season', ['season', 'overview', 'map', 'alerts']], ['Compare', ['wardcompare', 'scorecards']],
    ['Analysis', ['roadbot', 'findings', 'brief', 'planner', 'roads', 'models']], ['Data', ['projects', 'track', 'issues', 'complaints', 'datahealth', 'social']]],
};
const NAV_KEYS = () => NAV[ME.role].flatMap(s => s[1]);
const RENAME = {
  'Ward Officer': { ward: 'My ward dashboard', audit: 'Work orders & recovery', planner: 'Budget & next rupee' },
  'Contractor': { scorecards: 'My scorecard', audit: 'My flags & evidence' },
  'Auditor / Verifier': { audit: 'All flags (table)' },
  'Citizen': { track: 'Track my complaint', ask: 'Ask the help bot', reports: 'Report a problem', projects: 'Ward projects', ward: "My ward's spending" },
};
const BADGE_OF = { submissions: 'submissions', jobs: 'jobs', review: 'queue', audit: 'audit', alerts: 'alerts', reports: 'reports', complaints: 'complaints', ward: 'wards' };
let OPTIONS = null;

async function refreshBadges() {
  try {
    const b = await api('/api/badges', { keep: true });
    document.querySelectorAll('.nav-item').forEach(n => {
      const v = b[BADGE_OF[n.dataset.k]];
      let s = n.querySelector('.nav-badge');
      if (!v) { if (s) s.remove(); return; }
      if (!s) { s = document.createElement('span'); n.appendChild(s); }
      s.className = 'nav-badge' + (['complaints', 'wards'].includes(n.dataset.k) ? ' amber' : '');
      s.textContent = v;
    });
  } catch (e) { }
}

function go(key) { if (location.hash.slice(1) === key) render(); else location.hash = key; }
async function render() {
  const allowed = NAV_KEYS();
  let key = location.hash.slice(1);
  if (!allowed.includes(key)) key = allowed[0];
  document.querySelectorAll('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.k === key));
  const mySeq = ++NAV_SEQ;
  if (window.destroyWardMap) destroyWardMap();   // free the WebGL context when leaving a map page
  view.classList.remove('enter');
  view.innerHTML = SKELETON;
  window.scrollTo({ top: 0, behavior: 'smooth' });
  try { await V[key](); } catch (e) { if (e.stale || mySeq !== NAV_SEQ) return; console.error(e); view.innerHTML = `<div class="note error">⚠️ ${esc(e.message)}</div>`; }
  if (mySeq !== NAV_SEQ) return;
  void view.offsetWidth; view.classList.add('enter');   // replay the page-enter animation
  countUp(view);
}

/* ---------- motion helpers ---------- */
const SKELETON = '<div class="skel"><i class="t"></i><div class="k"><i></i><i></i><i></i><i></i><i></i></div><i class="b"></i><i class="b"></i></div>';
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
function countUp(root) {   // animate the first number in each KPI value, keeping ₹ / Cr / L / % formatting
  if (REDUCED) return;
  root.querySelectorAll('.kpi .v').forEach(el => {
    const txt = el.textContent, m = txt.match(/[\d,]*\.?\d+/);
    if (!m) return;
    const raw = m[0], target = parseFloat(raw.replace(/,/g, '')), dec = (raw.split('.')[1] || '').length;
    if (!isFinite(target) || target === 0) return;
    const t0 = performance.now(), dur = 700;
    const step = now => {
      const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      el.textContent = txt.replace(raw, (target * e).toLocaleString('en-IN', { minimumFractionDigits: dec, maximumFractionDigits: dec }));
      if (p < 1) requestAnimationFrame(step); else el.textContent = txt;
    };
    requestAnimationFrame(step);
  });
}
document.addEventListener('pointerdown', e => {   // click ripple on every button
  const b = e.target.closest('.btn'); if (!b || REDUCED) return;
  const r = b.getBoundingClientRect(), dot = document.createElement('span');
  dot.className = 'ripple-dot'; dot.style.left = (e.clientX - r.left) + 'px'; dot.style.top = (e.clientY - r.top) + 'px';
  b.appendChild(dot); setTimeout(() => dot.remove(), 650);
});
const pageHero = (img, title, sub, credit) => `<div class="page-hero" style="background-image:url('/static/img/${img}')"><div><b>${title}</b><span>${sub}</span></div><small>Photo: ${credit} · Wikimedia Commons</small></div>`;
async function logout() { try { await post('/api/logout'); } catch (e) { } sessionStorage.removeItem('cp_token'); location.href = '/'; }

async function setClaude(on) {
  try { await post('/api/admin/settings', { claude_enabled: on }); toast(on ? 'Claude switched on for everyone' : 'Claude switched off for everyone'); await boot(); }
  catch (e) { toast(e.message); }
}
async function boot() {
  [ME, OPTIONS] = await Promise.all([api('/api/me', { keep: true }), fetch('/api/options').then(r => r.json())]);
  const scope = ME.role === 'Ward Officer' ? ` · Ward ${ME.ward}` : ME.role === 'Contractor' ? ` · ${String(ME.contractor_name).replace(' (synthetic)', '')}` : '';
  document.getElementById('user-chip').textContent = ME.role + scope;
  document.getElementById('who').innerHTML = `<b>${esc(ME.email)}</b>${esc(ME.role)}${ME.ward_name ? '<br>Ward ' + esc(ME.ward) + ': ' + esc(ME.ward_name) : ''}${ME.contractor_name ? '<br>' + esc(ME.contractor_name) : ''}`;
  const cc = document.getElementById('claude-chip');
  cc.className = 'chip ' + (ME.claude ? 'green' : 'grey'); cc.textContent = ME.claude ? '🟢 Claude on' : '⚪ Claude off';
  cc.style.cursor = ME.role === 'Admin' ? 'pointer' : ''; cc.title = ME.role === 'Admin' ? 'Click to switch Claude on or off for everyone' : '';
  cc.onclick = ME.role === 'Admin' ? () => setClaude(!ME.claude_enabled).then(() => render()) : null;
  const lang = document.getElementById('lang'); lang.value = LANG; lang.onchange = () => { LANG = lang.value; sessionStorage.setItem('cp_lang', LANG); };
  const rn = RENAME[ME.role] || {};
  document.getElementById('nav').innerHTML = NAV[ME.role].map(([sec, keys]) => `<div class="sb-label">${sec}</div>` +
    keys.map(k => `<div class="nav-item" data-k="${k}">${ITEMS[k][0]} ${rn[k] || ITEMS[k][1]}</div>`).join('')).join('');
  document.querySelectorAll('.nav-item').forEach(n => n.onclick = () => go(n.dataset.k));
  setupAssistant();
  refreshBadges();
  render();
}
window.addEventListener('hashchange', render);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
boot();
