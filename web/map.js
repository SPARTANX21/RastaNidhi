/* RastaNidhi ward map — plain SVG, no map library or tiles, so it draws instantly.
   Hover = quick tooltip · click = full ward details · zoom with buttons / scroll / drag · metric chips · hotspot + issue dots. */
'use strict';

const MAP_METRICS = {
  budget_used_pct: { label: 'Budget used', fmt: v => num(v) + '%', stops: ['#e9ebf8', '#b9bde6', '#f2a65a', '#d64545'] },
  money_at_risk_inr: { label: 'Needs review', fmt: v => inr(v), stops: ['#fdf1e6', '#f7c08a', '#e8743b', '#9c2a1a'] },
  reopen_rate: { label: 'Re-open rate', fmt: v => pct(v), stops: ['#eaf6ee', '#a8d8b9', '#f2a65a', '#d64545'] },
  open_complaints: { label: 'Open complaints', fmt: v => num(v), stops: ['#efedfa', '#c4bdf0', '#8a7bd8', '#4a3a9c'] },
  sla_rate: { label: 'SLA met', fmt: v => pct(v), stops: ['#d64545', '#f2a65a', '#b9e0c4', '#1d7a48'] },
  low_lying_index: { label: 'Flood risk', fmt: v => num(v, 2), stops: ['#eef6fb', '#a9d3ea', '#4a9ccc', '#0e5a8a'] },
};
const hex2rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
function ramp(stops, t) {
  t = Math.max(0, Math.min(1, isFinite(t) ? t : 0));
  const s = t * (stops.length - 1), i = Math.min(stops.length - 2, Math.floor(s)), f = s - i, a = hex2rgb(stops[i]), b = hex2rgb(stops[i + 1]);
  return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * f)).join(',')})`;
}
function destroyWardMap() { window._wmap = null; }   // kept for app.js (SVG needs no cleanup)

async function WardMap(host, { height = 560, full = false, compact = false, onSelect = null, initial = null } = {}) {
  host.innerHTML = `<div class="svgmap ${compact ? 'compact' : ''}" style="height:${full ? 'calc(100vh - 160px)' : height + 'px'}"><div class="sm-loading">Loading map…</div></div>`;
  let D;
  try { D = await api('/api/wardmap'); } catch (e) { host.innerHTML = `<div class="note error">⚠️ ${esc(e.message)}</div>`; return null; }
  const W = Object.fromEntries(D.wards.map(w => [w.ward_code, w]));
  const officer = ME.role === 'Ward Officer';
  const st = { metric: 'budget_used_pct', sel: initial || (officer ? D.my_ward : null), dots: { hot: !compact, iss: !compact }, k: 1, x: 0, y: 0 };

  // ---- projection (equirectangular, corrected for Mumbai's latitude)
  const pts = D.geo.features.flatMap(f => f.geometry.coordinates[0]);
  const [x0, x1] = [Math.min(...pts.map(p => p[0])), Math.max(...pts.map(p => p[0]))];
  const [y0, y1] = [Math.min(...pts.map(p => p[1])), Math.max(...pts.map(p => p[1]))];
  const kx = Math.cos(19.07 * Math.PI / 180), VW = 600, sc = VW / ((x1 - x0) * kx), VH = (y1 - y0) * sc;
  const P = (lon, lat) => [(lon - x0) * kx * sc, (y1 - lat) * sc];
  const centroid = ring => { let a = 0, cx = 0, cy = 0; for (let i = 0; i < ring.length - 1; i++) { const [xa, ya] = P(...ring[i]), [xb, yb] = P(...ring[i + 1]), c = xa * yb - xb * ya; a += c; cx += (xa + xb) * c; cy += (ya + yb) * c; }
    return a ? [cx / (3 * a), cy / (3 * a)] : P(...ring[0]); };

  const wrap = host.querySelector('.svgmap');
  wrap.innerHTML = `
    <div class="sm-stage">
      ${compact ? '' : `<div class="sm-chips">${Object.entries(MAP_METRICS).filter(([k]) => !(ME.role === 'Citizen' && k === 'money_at_risk_inr'))
        .map(([k, m]) => `<button class="sm-chip ${k === st.metric ? 'on' : ''}" data-m="${k}">${m.label}</button>`).join('')}</div>`}
      <svg class="sm-svg" viewBox="0 0 ${VW} ${VH.toFixed(0)}" preserveAspectRatio="xMidYMid meet">
        <defs><filter id="sm-shadow" x="-10%" y="-10%" width="120%" height="120%"><feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="#1f2350" flood-opacity=".18"/></filter>
          <pattern id="sm-grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" fill="none" stroke="#3d4280" stroke-opacity=".05"/></pattern></defs>
        <rect x="-2000" y="-2000" width="5000" height="5000" fill="url(#sm-grid)"/>
        <g class="sm-world">
          <g class="sm-land" filter="url(#sm-shadow)">${D.geo.features.map(f => `<path class="sm-ward" data-w="${f.properties.ward_code}" d="M${f.geometry.coordinates[0].map(c => P(...c).map(v => v.toFixed(1)).join(',')).join('L')}Z"/>`).join('')}</g>
          <g class="sm-dots-hot"></g><g class="sm-dots-iss"></g>
          <g class="sm-labels">${D.geo.features.map(f => { const [cx, cy] = centroid(f.geometry.coordinates[0]); const w = W[f.properties.ward_code];
            return `<text x="${cx.toFixed(1)}" y="${cy.toFixed(1)}" data-w="${f.properties.ward_code}"><tspan class="c">${f.properties.ward_code}</tspan>${compact ? '' : `<tspan class="n" x="${cx.toFixed(1)}" dy="11">${esc((w?.ward_name || '').split(',')[0])}</tspan>`}</text>`; }).join('')}</g>
        </g>
      </svg>
      <div class="sm-zoom"><button data-z="in" title="Zoom in">+</button><button data-z="out" title="Zoom out">−</button><button data-z="reset" title="Reset">⟲</button></div>
      ${compact ? '' : `<div class="sm-layers"><label><input type="checkbox" data-d="hot" ${st.dots.hot ? 'checked' : ''}> 💧 Flood hotspots</label>
        ${D.issues.length ? `<label><input type="checkbox" data-d="iss" ${st.dots.iss ? 'checked' : ''}> 📍 Top open issues</label>` : ''}</div>`}
      <div class="sm-legend"></div>
      <div class="sm-tip"></div>
    </div>
    ${compact ? '' : '<aside class="sm-card"></aside>'}`;
  const $ = s => wrap.querySelector(s), svg = $('.sm-svg'), world = $('.sm-world'), tip = $('.sm-tip');

  // ---- colours + legend
  function paint() {
    const m = MAP_METRICS[st.metric], vals = D.wards.map(w => w[st.metric]).filter(v => v !== null && v !== undefined);
    const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
    wrap.querySelectorAll('.sm-ward').forEach(p => { const v = W[p.dataset.w]?.[st.metric];
      p.style.fill = v === null || v === undefined ? '#e4e4e0' : ramp(m.stops, vals.length > 1 ? (v - lo) / span : .7);   // single ward (officer) -> mid-scale colour
      p.classList.toggle('sel', p.dataset.w === st.sel); p.classList.toggle('muted', officer && p.dataset.w !== D.my_ward); });
    wrap.querySelectorAll('.sm-labels text').forEach(t => t.classList.toggle('sel', t.dataset.w === st.sel));
    $('.sm-legend').innerHTML = vals.length > 1 ? `<b>${m.label}</b><i style="background:linear-gradient(90deg,${m.stops.join(',')})"></i><span>${m.fmt(lo)}</span><span>${m.fmt(hi)}</span>`
      : `<b>${m.label}</b><span style="grid-column:1/-1">${officer ? 'Your ward: ' + m.fmt(vals[0]) : ''}</span>`;
  }
  function dots() {
    $('.sm-dots-hot').innerHTML = st.dots.hot ? D.hotspots.map(h => { const [x, y] = P(h.lon, h.lat);
      return `<g class="sm-hot" transform="translate(${x.toFixed(1)},${y.toFixed(1)})" data-tip="💧 <b>${esc(h.name)}</b><br>Floods at ${h.threshold} mm/day · ward ${h.ward_code}"><circle r="7" class="ring"/><circle r="3.6"/></g>`; }).join('') : '';
    $('.sm-dots-iss').innerHTML = st.dots.iss ? D.issues.map(i => { const [x, y] = P(i.lon, i.lat);
      return `<g class="sm-iss" transform="translate(${x.toFixed(1)},${y.toFixed(1)})" data-tip="📍 <b>#${i.rank} ${esc(i.category)}</b><br>${esc(i.locality)} · ${esc(i.road)}<br>Risk ${num(i.risk)}/100"><circle r="${i.rank <= 10 ? 6 : 4.5}"/>${i.rank <= 10 ? `<text dy="2.6">${i.rank}</text>` : ''}</g>`; }).join('') : '';
    scaleMarks();
  }
  const scaleMarks = () => wrap.querySelectorAll('.sm-hot, .sm-iss, .sm-labels text').forEach(g => {
    if (g.tagName === 'text') g.style.fontSize = (11 / Math.sqrt(st.k)) + 'px';
    else g.setAttribute('transform', g.getAttribute('transform').replace(/ scale\([^)]*\)/, '') + ` scale(${(1 / Math.sqrt(st.k)).toFixed(3)})`); });

  // ---- ward details card (instant, no extra request)
  function card(code) {
    const box = $('.sm-card'); if (!box) return;
    const w = code && W[code];
    if (!w || w.spend_inr === null) {
      box.innerHTML = `<div class="sm-empty"><b>${officer ? 'Ward ' + esc(D.my_ward) : 'Pick a ward'}</b><span>${officer ? 'Other wards are shown as outlines only.' : 'Hover for a quick look, click for full details.'}</span>
        <div class="sm-rank">${[...D.wards].filter(x => x[st.metric] !== null).sort((a, b) => (b[st.metric] ?? 0) - (a[st.metric] ?? 0)).slice(0, 6).map((x, i) =>
          `<div data-w="${x.ward_code}"><i>${i + 1}</i>${x.ward_code} · ${esc(x.ward_name.split(',')[0])}<b>${MAP_METRICS[st.metric].fmt(x[st.metric])}</b></div>`).join('')}</div>
        <span class="muted" style="margin-top:6px">Highest ${MAP_METRICS[st.metric].label.toLowerCase()} first.</span></div>`;
      box.querySelectorAll('[data-w]').forEach(el => el.onclick = () => select(el.dataset.w));
      return;
    }
    const over = w.budget_used_pct > 100, iss = D.issues.filter(i => i.ward === code).slice(0, 3), hs = D.hotspots.filter(h => h.ward_code === code);
    box.innerHTML = `<div class="sm-wc">
      <div class="sm-wc-top"><div><b>Ward ${code}</b><span>${esc(w.ward_name)} · ${esc(w.zone)}</span></div>${officer ? '' : '<button class="sm-x" title="Close">×</button>'}</div>
      <div class="sm-meter"><div><i class="${over ? 'over' : ''}" style="width:${Math.min(100, w.budget_used_pct)}%"></i></div>
        <span>${inr(w.spend_inr)} spent of ${inr(w.monsoon_repair_budget_inr_2025)} · <b class="${over ? 'red' : ''}">${num(w.budget_used_pct)}%</b>${over ? ' · over budget' : ' · ' + inr(w.remaining_budget_inr) + ' left'}</span></div>
      <div class="sm-stats">
        ${w.money_at_risk_inr !== null ? `<div><b>${inr(w.money_at_risk_inr)}</b><span>needs review</span></div>` : ''}
        <div><b>${inr(w.failed_fix_spend_inr)}</b><span>on failed fixes</span></div>
        <div><b>${pct(w.reopen_rate)}</b><span>re-opened ≤30d</span></div><div><b>${pct(w.sla_rate)}</b><span>SLA met</span></div>
        <div><b>${num(w.open_complaints)}</b><span>open complaints</span></div><div><b>${num(w.jobs)}</b><span>repair jobs</span></div>
        <div><b>${num(w.population_est / 1e5, 1)} L</b><span>residents</span></div><div><b>${num(w.low_lying_index, 2)}</b><span>flood index</span></div>
        <div><b>${num(w.engineering_crews)}</b><span>crews</span></div></div>
      ${iss.length ? `<div class="sm-h">Top open issues</div>${iss.map(i => `<div class="sm-li"><i>#${i.rank}</i>${esc(i.category)} · ${esc(i.locality)}<b>${num(i.risk)}</b></div>`).join('')}` : ''}
      ${hs.length ? `<div class="sm-h">Flood hotspots</div>${hs.map(h => `<div class="sm-li"><i>💧</i>${esc(h.name)}<b>${h.threshold} mm</b></div>`).join('')}` : ''}
      <div class="sm-h">Biggest contractor</div><div class="sm-li"><i>🏗️</i>${esc(String(w.top_contractor).replace(' (synthetic)', ''))}</div>
      <div class="sm-acts">${['ward:💰 Money trail', 'planner:🧭 Next rupee', 'roads:🛣️ Roads', 'audit:🔍 Flags'].map(s => s.split(':')).filter(([k]) => NAV_KEYS().includes(k))
        .map(([k, l]) => `<button class="btn ghost small" data-go="${k}">${l}</button>`).join('')}</div></div>`;
    const x = box.querySelector('.sm-x'); if (x) x.onclick = () => select(null);
    box.querySelectorAll('[data-go]').forEach(b => b.onclick = () => { WARD_SEL = code; if (b.dataset.go === 'audit') AUDIT_F.ward = code; go(b.dataset.go); });
  }
  function select(code) {
    if (officer && code && code !== D.my_ward) { toast(`You can only open ward ${D.my_ward}`); return; }
    if (onSelect && code) return onSelect(code);
    st.sel = code; paint(); card(code);
  }

  // ---- hover tooltip
  const showTip = (e, html) => { const r = wrap.querySelector('.sm-stage').getBoundingClientRect(); tip.innerHTML = html; tip.classList.add('on');
    tip.style.left = Math.min(e.clientX - r.left + 14, r.width - 230) + 'px'; tip.style.top = (e.clientY - r.top + 14) + 'px'; };
  svg.addEventListener('mousemove', e => {
    const dot = e.target.closest('[data-tip]'); if (dot) return showTip(e, dot.dataset.tip);
    const p = e.target.closest('.sm-ward'); if (!p) return tip.classList.remove('on');
    const w = W[p.dataset.w], m = MAP_METRICS[st.metric];
    showTip(e, w && w.spend_inr !== null ? `<b>Ward ${w.ward_code}</b> · ${esc(w.ward_name.split(',')[0])}<br>${m.label}: <b>${m.fmt(w[st.metric])}</b><br><span>Budget ${num(w.budget_used_pct)}% · re-open ${pct(w.reopen_rate)} · ${num(w.open_complaints)} open</span>`
      : `<b>Ward ${p.dataset.w}</b><br><span>Outside your ward</span>`);
  });
  svg.addEventListener('mouseleave', () => tip.classList.remove('on'));

  // ---- zoom / pan (viewBox transform on the world group)
  const apply = (anim = true) => { world.style.transition = anim ? 'transform .35s cubic-bezier(.2,.7,.2,1)' : 'none';
    world.setAttribute('transform', `translate(${st.x.toFixed(1)},${st.y.toFixed(1)}) scale(${st.k.toFixed(3)})`); world.style.transform = ''; scaleMarks(); };
  const zoomAt = (f, cx = VW / 2, cy = VH / 2) => { const k = Math.max(1, Math.min(6, st.k * f)); st.x = cx - (cx - st.x) * (k / st.k); st.y = cy - (cy - st.y) * (k / st.k); st.k = k; if (k === 1) { st.x = 0; st.y = 0; } apply(); };
  const toSvg = e => { const r = svg.getBoundingClientRect(), s = Math.max(VW / r.width, VH / r.height); return [(e.clientX - r.left - (r.width - VW / s) / 2) * s, (e.clientY - r.top - (r.height - VH / s) / 2) * s]; };
  $('.sm-zoom').onclick = e => { const z = e.target.dataset.z; if (z === 'in') zoomAt(1.5); else if (z === 'out') zoomAt(1 / 1.5); else if (z === 'reset') { st.k = 1; st.x = 0; st.y = 0; apply(); } };
  svg.addEventListener('wheel', e => { e.preventDefault(); const [cx, cy] = toSvg(e); zoomAt(e.deltaY < 0 ? 1.25 : 0.8, cx, cy); }, { passive: false });
  let drag = null, moved = false;
  svg.addEventListener('pointerdown', e => { drag = [e.clientX, e.clientY, st.x, st.y]; moved = false; });
  svg.addEventListener('pointermove', e => { if (!drag || st.k === 1) return; const r = svg.getBoundingClientRect(), s = Math.max(VW / r.width, VH / r.height);
    const dx = (e.clientX - drag[0]) * s, dy = (e.clientY - drag[1]) * s; if (Math.abs(dx) + Math.abs(dy) > 4) moved = true; st.x = drag[2] + dx; st.y = drag[3] + dy; apply(false); });
  window.addEventListener('pointerup', () => { drag = null; }, { once: false });
  svg.addEventListener('click', e => { if (moved) return; const p = e.target.closest('.sm-ward'); if (p) select(p.dataset.w); });

  wrap.querySelectorAll('.sm-chip').forEach(b => b.onclick = () => { wrap.querySelectorAll('.sm-chip').forEach(x => x.classList.toggle('on', x === b)); st.metric = b.dataset.m; paint(); card(st.sel); });
  wrap.querySelectorAll('[data-d]').forEach(c => c.onchange = () => { st.dots[c.dataset.d] = c.checked; dots(); });

  paint(); dots(); card(st.sel);
  if (officer && D.my_ward) {   // zoom the officer straight to their ward
    const f = D.geo.features.find(x => x.properties.ward_code === D.my_ward);
    if (f) { const xy = f.geometry.coordinates[0].map(c => P(...c)), xs = xy.map(p => p[0]), ys = xy.map(p => p[1]);
      const k = Math.min(4, 0.8 * Math.min(VW / (Math.max(...xs) - Math.min(...xs)), VH / (Math.max(...ys) - Math.min(...ys))));
      const cx = (Math.max(...xs) + Math.min(...xs)) / 2, cy = (Math.max(...ys) + Math.min(...ys)) / 2;
      st.k = Math.max(1, k); st.x = VW / 2 - cx * st.k; st.y = VH / 2 - cy * st.k; apply(false); }
  }
  window._wmap = { select };
  return window._wmap;
}
