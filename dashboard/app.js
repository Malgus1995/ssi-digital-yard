'use strict';
const $ = id => document.getElementById(id);
const fmt = n => Math.round(n).toLocaleString('ko-KR');
const colors = { '입고': '#12a38b', '출고': '#eb8e45', '직행': '#9473d0' };
const zoneNames = { '1dock': '1도크', '2dock': '2도크', wharf: '안벽', texaco: '텍사코', e4: 'E4' };
let D, shared, slots = [], currentSlot = 0, dates = [], day = 0;
let nodes = {}, yards = [], events = [], active = [], occupancy = {}, placements = [];
let selected = null, tab = 'moves', playing = false, replayOnly = false;
let phase = 0, elapsed = 0, last = 0, dirty = true;
// Display metres per playback second, shared across dates, routes and algorithms.
// This is an animation scale, not a claim about real transporter operating speed.
const TRANSPORT_METERS_PER_SECOND = 200;
let dayDuration = 3000;
let zoom = 1, offset = { x: 0, y: 0 }, W = 0, H = 0;
let drag = null, moved = false, pinch = null, expanded = false;
let hit = [], routeCache = new Map(), graph = {};
const pointers = new Map();
const canvas = $('map'), ctx = canvas.getContext('2d');

function world(p) {
  return { x: (p.lon - 128.69) * 111320 * Math.cos(34.87 * Math.PI / 180), y: -(p.lat - 34.87) * 111320 };
}
function screen(p) { return { x: p.x * zoom + offset.x, y: p.y * zoom + offset.y }; }
function path(a, b) {
  const key = a + '|' + b;
  if (routeCache.has(key)) return routeCache.get(key);
  const dist = { [a]: 0 }, prev = {}, queue = new Set(Object.keys(nodes));
  while (queue.size) {
    let u = null;
    for (const v of queue) if (u === null || (dist[v] ?? Infinity) < (dist[u] ?? Infinity)) u = v;
    if (!Number.isFinite(dist[u])) break;
    queue.delete(u);
    if (u === b) break;
    for (const e of graph[u] || []) if (dist[u] + e.time < (dist[e.to] ?? Infinity)) {
      dist[e.to] = dist[u] + e.time;
      prev[e.to] = u;
    }
  }
  let result = null;
  if (Number.isFinite(dist[b])) {
    result = [b];
    while (result[0] !== a) {
      result.unshift(prev[result[0]]);
      if (result.length > Object.keys(nodes).length) { result = null; break; }
    }
  }
  routeCache.set(key, result);
  return result;
}
function bounds(all = Object.values(nodes)) {
  return all.reduce((b, n) => ({ x0: Math.min(b.x0, n.x - n.width / 2),
    y0: Math.min(b.y0, n.y - n.depth / 2), x1: Math.max(b.x1, n.x + n.width / 2),
    y1: Math.max(b.y1, n.y + n.depth / 2) }), { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity });
}
function fit(target) {
  const all = target ? (Array.isArray(target) ? target : [target]) : Object.values(nodes);
  if (!all.length || W < 1 || H < 1) return;
  const b = bounds(all);
  zoom = Math.max(.035, Math.min(10, (W - 120) / (b.x1 - b.x0 + 70), (H - 150) / (b.y1 - b.y0 + 70)));
  offset = { x: W / 2 - (b.x0 + b.x1) / 2 * zoom, y: H / 2 - (b.y0 + b.y1) / 2 * zoom };
  dirty = true;
}
function zoomAt(factor, x = W / 2, y = H / 2) {
  const old = zoom;
  zoom = Math.min(16, Math.max(.035, zoom * factor));
  offset = { x: x - (x - offset.x) * zoom / old, y: y - (y - offset.y) * zoom / old };
  dirty = true;
}
function resize() {
  const r = canvas.getBoundingClientRect(), dpr = devicePixelRatio || 1;
  if (W && H) { offset.x += (r.width - W) / 2; offset.y += (r.height - H) / 2; }
  W = r.width; H = r.height;
  canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  dirty = true;
  if (D && dates.length) drawActivity();
}

// Disjoint free rectangles preserve scale and prevent block footprints from overlapping.
// Unplaced blocks stay in inventory and all occupancy calculations.
function packBlocks() {
  placements = [];
  for (const y of yards) {
    const free = [{ x: 0, y: 0, w: y.width, h: y.depth }];
    const codes = [...occupancy[y.code].blocks].sort((a, b) =>
      D.blocks[b].length * D.blocks[b].width - D.blocks[a].length * D.blocks[a].width || a.localeCompare(b));
    let unplaced = 0;
    for (const code of codes) {
      const b = D.blocks[code];
      let choice = null;
      for (let j = 0; j < free.length; j++) {
        for (const [w, h] of [[b.length, b.width], [b.width, b.length]]) {
          if (w <= free[j].w && h <= free[j].h) {
            const score = free[j].w * free[j].h - w * h;
            if (!choice || score < choice.score) choice = { j, w, h, score };
          }
        }
      }
      if (!choice) { unplaced++; continue; }
      const { j, w, h } = choice, r = free.splice(j, 1)[0];
      placements.push({ code, yard: y.code, x: y.x - y.width / 2 + r.x, y: y.y - y.depth / 2 + r.y, w, h });
      if (r.w > w) free.push({ x: r.x + w, y: r.y, w: r.w - w, h });
      if (r.h > h) free.push({ x: r.x, y: r.y + h, w: r.w, h: r.h - h });
    }
    occupancy[y.code].unplaced = unplaced;
  }
}
function setDay(index) {
  if (!D || !dates.length) return;
  day = Math.max(0, Math.min(dates.length - 1, index));
  phase = 0; elapsed = 0; dirty = true;
  const date = dates[day];
  events = D.daily_moves[date] || [];
  const longestRoute = Math.max(0, ...events.map(e => {
    const route = path(e.from, e.to);
    return route ? routeLength(route.map(code => nodes[code])) : 0;
  }));
  // Let the longest trip finish; never accelerate it to fit a fixed day length.
  dayDuration = Math.max(3000, longestRoute / TRANSPORT_METERS_PER_SECOND * 1000 + 300);
  active = Object.entries(D.assignment).filter(([code]) => D.blocks[code].start <= date && date < D.blocks[code].end);
  occupancy = Object.fromEntries(yards.map(y => [y.code, { area: 0, blocks: [] }]));
  for (const [code, yard] of active) {
    const b = D.blocks[code];
    occupancy[yard].area += b.length * b.width;
    occupancy[yard].blocks.push(code);
  }
  packBlocks();
  $('date').value = date; $('slider').value = day;
  $('slider').setAttribute('aria-valuetext', date);
  $('dayinfo').textContent = `${day + 1} / ${dates.length}일`;
  $('asideDate').textContent = date;
  $('moveCount').textContent = events.length;
  const area = Object.values(occupancy).reduce((s, o) => s + o.area, 0);
  const total = yards.reduce((s, y) => s + y.area, 0);
  const stats = [
    ['보관 중인 블록', fmt(active.length), '개', '선택 날짜 마감 재고'],
    ['블록 점유면적', fmt(area), 'm²', '블록 길이 × 폭 합계'],
    ['전체 적치장 면적', fmt(total), 'm²', `${yards.length}개 · 면적 미상 ${Object.values(nodes).filter(n => n.kind === '적치장' && !n.area).length}개 별도 표식`],
    ['공간 점유율', (area / total * 100).toFixed(1), '%', `간격 반영 ${(area * D.spacing_factor / total * 100).toFixed(1)}%`],
    ['오늘의 이동', fmt(events.length), '건', `입고 ${events.filter(e => e.action === '입고').length} · 출고 ${events.filter(e => e.action === '출고').length} · 직행 ${events.filter(e => e.action === '직행').length}`]
  ];
  const [start, end] = slotRange(D), inRange = start <= date && date <= end;
  $('stats').innerHTML = stats.map(([label, value, unit, note]) =>
    `<div class="stat"><small>${label}</small><strong>${inRange ? value : '—'}<span>${inRange ? unit : ''}</span></strong><em>${inRange ? note : '현재 슬롯의 결과 기간 밖'}</em></div>`).join('');
  const unplaced = Object.values(occupancy).reduce((s, o) => s + o.unplaced, 0);
  $('mapSummary').textContent = inRange
    ? `${date} 마감 · 도형 ${placements.length}개 / 재고 ${active.length}개${unplaced ? ` · 미배치 ${unplaced}개` : ''}`
    : `${date} · 현재 결과 기간 밖`;
  renderList(); showDetail(); renderComparison(); drawActivity();
}
function setPlaying(value, onlyDay = false) {
  if (!D || !dates.length) return;
  playing = value; replayOnly = onlyDay;
  if (value) {
    if (onlyDay || phase >= 1) { elapsed = 0; phase = 0; }
    last = 0;
  }
  $('play').textContent = value ? '일시정지' : '재생';
  $('play').setAttribute('aria-pressed', String(value));
  dirty = true;
}
function select(code) {
  selected = code;
  showDetail(); renderList(); dirty = true;
  if (nodes[code]) fit(nodes[code]);
  else {
    const ev = events.find(e => e.block === code);
    const route = ev && path(ev.from, ev.to);
    if (tab === 'moves' && route) fit(route.map(c => nodes[c]));
    else if (D.assignment[code]) fit(nodes[D.assignment[code]]);
    else if (ev) fit([nodes[ev.from], nodes[ev.to]]);
  }
}
function showDetail() {
  const root = $('details');
  root.style.whiteSpace = 'pre-line';
  if (!selected) {
    root.textContent = '적치장이나 블록을 선택하면\n면적과 이동 경로를 확인할 수 있습니다.';
    return;
  }
  if (nodes[selected]) {
    const n = nodes[selected], o = occupancy[selected];
    const distance = Math.hypot(n.offset_x || 0, n.offset_y || 0);
    root.textContent = `${n.code} · ${n.kind}\n${n.area ? `${fmt(n.area)} m² · 등면적 도형 ${n.width.toFixed(1)} × ${n.depth.toFixed(1)} m` : '면적 미상 · 위치 표식'}\n원본 치수 ${n.original_width || '미상'} × ${n.original_depth || '미상'} m${o ? `\n보관 ${o.blocks.length}개 · 점유 ${fmt(o.area)} m² (${(o.area / n.area * 100).toFixed(1)}%)\n간격 반영 ${fmt(o.area * D.spacing_factor)} m²\n도형 미배치 ${o.unplaced}개 · 재고와 면적에는 포함` : ''}\n원본 GPS 대비 지도 좌표 ${distance.toFixed(1)} m 보정`;
    if (o && o.blocks.length) {
      const button = document.createElement('button');
      button.textContent = '이 적치장의 보관 블록 보기';
      button.style.cssText = 'margin-top:9px;font-size:12px';
      button.onclick = () => { tab = 'blocks'; $('search').value = selected; renderList(); };
      root.append(document.createTextNode('\n'), button);
    }
  } else {
    const b = D.blocks[selected];
    if (!b) { selected = null; showDetail(); return; }
    const placement = placements.find(p => p.code === selected);
    const ev = events.filter(e => e.block === selected);
    root.textContent = `${selected} · ${(b.length * b.width).toFixed(1)} m²\n${b.length} × ${b.width} × ${b.height} m (길이 × 폭 × 높이)\n입고 ${b.start} / 출고 ${b.end}\n배정 ${D.assignment[selected] || '당일 직행'}\n${placement ? '실제 치수 비례 도형 · 내부 배치는 시각화용' : active.some(([c]) => c === selected) ? '공간 부족으로 도형 미배치 · 점유면적에는 포함' : '선택 날짜의 보관 블록이 아닙니다.'}${ev.map(e => `\n${e.action}: ${e.from} → ${e.to}${path(e.from, e.to) ? '' : ' (연결 경로 없음)'}`).join('')}`;
    if (ev.some(e => path(e.from, e.to))) {
      const button = document.createElement('button');
      button.textContent = '이 날짜의 이동 다시 재생';
      button.style.cssText = 'margin-top:9px;font-size:12px';
      button.onclick = () => setPlaying(true, true);
      root.append(document.createTextNode('\n'), button);
    }
  }
}
function renderList() {
  const q = $('search').value.trim().toLowerCase(), list = $('list');
  for (const [id, name] of [['movesTab', 'moves'], ['yardsTab', 'yards'], ['blocksTab', 'blocks']]) {
    $(id).classList.toggle('active', tab === name);
    $(id).setAttribute('aria-selected', String(tab === name));
  }
  list.replaceChildren();
  function item(code, title, badge, lines, color, rate) {
    const button = document.createElement('button');
    button.className = 'item' + (selected === code ? ' chosen' : '');
    const row = document.createElement('div'); row.className = 'row';
    const bold = document.createElement('b'); bold.textContent = title;
    const tag = document.createElement('span'); tag.className = 'tag'; tag.textContent = badge;
    if (color) tag.style.color = color;
    row.append(bold, tag); button.append(row);
    for (const text of lines) { const small = document.createElement('small'); small.textContent = text; button.append(small); }
    if (rate !== undefined) {
      const bar = document.createElement('div'); bar.className = 'bar';
      const fill = document.createElement('i'); fill.style.width = Math.min(100, rate) + '%';
      if (rate > 85) fill.style.background = '#df9b4d';
      bar.append(fill); button.append(bar);
    }
    button.onclick = () => select(code); list.append(button);
  }
  if (tab === 'moves') {
    for (const e of events.filter(e => `${e.block} ${e.from} ${e.to} ${e.action}`.toLowerCase().includes(q))) {
      item(e.block, e.block, e.action, [`${e.from} → ${e.to}`,
        `${(D.blocks[e.block].length * D.blocks[e.block].width).toFixed(1)} m² · ${path(e.from, e.to) ? '도로 경로' : '연결 경로 없음'}`], colors[e.action]);
    }
  } else if (tab === 'yards') {
    for (const y of yards.filter(y => `${y.code} ${zoneNames[y.zone] || ''}`.toLowerCase().includes(q))
      .sort((a, b) => occupancy[b.code].area / b.area - occupancy[a.code].area / a.area)) {
      const o = occupancy[y.code], rate = o.area / y.area * 100;
      item(y.code, y.code, rate.toFixed(1) + '%', [`${o.blocks.length}개 · ${fmt(o.area)} / ${fmt(y.area)} m²`,
        o.unplaced ? `도형 미배치 ${o.unplaced}개 · 집계 포함` : '모든 보관 블록 도형 표시'], null, rate);
    }
  } else {
    for (const [code, yard] of active.filter(([c, y]) => `${c} ${y}`.toLowerCase().includes(q))) {
      const b = D.blocks[code];
      item(code, code, (b.length * b.width).toFixed(1) + ' m²', [yard, `${b.length} × ${b.width} m · 출고 ${b.end}`]);
    }
  }
  $('listFooter').textContent = `${list.children.length}개 항목 · 선택하면 지도에서 위치를 보여줍니다.`;
  if (!list.children.length) {
    const empty = document.createElement('div'); empty.className = 'empty';
    empty.textContent = q ? '검색 결과가 없습니다.\n다른 탭에서도 검색해 보세요.' : '선택 날짜에 표시할 항목이 없습니다.';
    list.append(empty);
  }
}

function line(points, color, width, dash = []) {
  if (points.length < 2) return;
  ctx.beginPath();
  points.forEach((p, i) => { const s = screen(p); i ? ctx.lineTo(s.x, s.y) : ctx.moveTo(s.x, s.y); });
  ctx.strokeStyle = color; ctx.lineWidth = width; ctx.setLineDash(dash); ctx.stroke(); ctx.setLineDash([]);
}
function occupancyColor(rate) {
  return rate > .85 ? '#e9ad68' : rate > .6 ? '#68a5cc' : rate > .3 ? '#91bdd8' : '#c5dcea';
}
function drawBackground() {
  ctx.fillStyle = '#edf2f5'; ctx.fillRect(0, 0, W, H);
  const grid = [10, 20, 50, 100, 200, 500, 1000].find(n => n * zoom >= 38) || 1000;
  const step = grid * zoom;
  ctx.strokeStyle = '#e0e8ee'; ctx.lineWidth = .7; ctx.beginPath();
  for (let x = ((offset.x % step) + step) % step; x < W; x += step) { ctx.moveTo(x, 0); ctx.lineTo(x, H); }
  for (let y = ((offset.y % step) + step) % step; y < H; y += step) { ctx.moveTo(0, y); ctx.lineTo(W, y); }
  ctx.stroke();
  if ($('labels').checked && zoom < 1.25) {
    for (const zone of Object.keys(zoneNames)) {
      const all = Object.values(nodes).filter(n => n.zone === zone);
      if (!all.length) continue;
      const b = bounds(all);
      const s = screen({ x: (b.x0 + b.x1) / 2, y: b.y0 - 46 });
      ctx.font = '600 14px sans-serif'; ctx.textAlign = 'center'; ctx.fillStyle = '#93a8bb';
      ctx.fillText(zoneNames[zone].toUpperCase(), s.x, s.y);
    }
  }
  for (const r of D.roads) {
    const a = nodes[r.source], b = nodes[r.target];
    if (a && b) { line([a, b], '#d6e0e7', 5); line([a, b], '#f8fbfc', 2.5); }
  }
}
function drawFacilities() {
  const mode = $('viewMode').value, labelBoxes = [];
  const all = Object.values(nodes).sort((a, b) => (a.code === selected) - (b.code === selected));
  const labels = [];
  for (const n of all) {
    const s = screen({ x: n.x - n.width / 2, y: n.y - n.depth / 2 });
    const w = n.width * zoom, h = n.depth * zoom, o = occupancy[n.code], chosen = selected === n.code;
    if (s.x + w < -100 || s.x > W + 100 || s.y + h < -100 || s.y > H + 100) continue;
    ctx.fillStyle = o ? (mode === 'occupancy' ? occupancyColor(o.area / n.area) : '#f9fcff') : '#dae3ec';
    ctx.strokeStyle = chosen ? '#3169e7' : o ? '#7da5c4' : '#b8c9d8';
    ctx.lineWidth = chosen ? 2.5 : 1;
    if (!n.area) {
      const c = screen(n); ctx.setLineDash([3, 3]); ctx.strokeRect(c.x - 5, c.y - 5, 10, 10); ctx.setLineDash([]);
    } else { ctx.fillRect(s.x, s.y, w, h); ctx.strokeRect(s.x, s.y, w, h); }
    hit.push({ x: s.x, y: s.y, w: Math.max(6, w), h: Math.max(6, h), code: n.code });
    if ($('labels').checked && (o || chosen || zoom > .9)) {
      const short = n.code.replace(/^(1dock|2dock|wharf|texaco|e4)-s-no-/, (_, z) => zoneNames[z] + ' · S');
      const text = zoom > 1 ? n.code : short;
      labels.push({ n, o, s, w, h, chosen, text });
    }
    if (mode === 'occupancy' && o && w > 42 && h > 25) {
      ctx.font = `600 ${Math.min(22, Math.max(12, w / 4))}px sans-serif`;
      ctx.fillStyle = '#285a80'; ctx.textAlign = 'center';
      ctx.fillText((o.area / n.area * 100).toFixed(0) + '%', s.x + w / 2, s.y + h / 2 + 5);
    }
  }
  // Selected labels have priority; other labels are suppressed when their text collides.
  labels.sort((a, b) => Number(b.chosen) - Number(a.chosen) || Number(!!b.o) - Number(!!a.o));
  for (const { n, o, s, w, h, chosen, text } of labels) {
    ctx.font = `${o || chosen ? 600 : 400} ${zoom > 1 ? 12 : 11}px sans-serif`;
    const tw = ctx.measureText(text).width + 10;
    const box = { x: s.x + w / 2 - tw / 2, y: s.y - 19, w: tw, h: 17 };
    if (!chosen && labelBoxes.some(b => box.x < b.x + b.w && box.x + box.w > b.x && box.y < b.y + b.h && box.y + box.h > b.y)) continue;
    labelBoxes.push(box);
    ctx.fillStyle = '#f9fcffed'; ctx.fillRect(box.x, box.y, box.w, box.h);
    ctx.fillStyle = chosen ? '#235ac7' : o ? '#456987' : '#859aae';
    ctx.textAlign = 'center'; ctx.fillText(text, s.x + w / 2, s.y - 6);
    if (o && zoom > .75) {
      ctx.font = '11px sans-serif'; ctx.fillStyle = '#6e8a9f';
      ctx.fillText(`${fmt(n.area)} m² · ${(o.area / n.area * 100).toFixed(0)}%`, s.x + w / 2, s.y + h + 14);
    }
  }
}
function drawBlocks() {
  if ($('viewMode').value === 'occupancy') return;
  for (const p of placements) {
    const s = screen(p), w = p.w * zoom, h = p.h * zoom;
    if (s.x + w < 0 || s.x > W || s.y + h < 0 || s.y > H) continue;
    const inbound = D.blocks[p.code].start === dates[day];
    ctx.fillStyle = p.code === selected ? '#315fe0' : inbound ? '#3cae9b' : '#649ac5';
    ctx.fillRect(s.x + .25, s.y + .25, Math.max(.2, w - .5), Math.max(.2, h - .5));
    ctx.strokeStyle = p.code === selected ? '#143cc2' : '#ffffffbd'; ctx.lineWidth = p.code === selected ? 2 : .45;
    ctx.strokeRect(s.x, s.y, w, h);
    hit.push({ x: s.x, y: s.y, w, h, code: p.code });
    if (w > 51 && h > 15) {
      ctx.fillStyle = '#fff'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center';
      ctx.fillText(p.code, s.x + w / 2, s.y + h / 2 + 4);
    }
  }
}
function routeLength(points) {
  return points.slice(1).reduce((sum, p, i) => sum + Math.hypot(p.x - points[i].x, p.y - points[i].y), 0);
}
function transportProgress(points, animationMs = elapsed) {
  const length = routeLength(points);
  return length > 0 ? Math.min(1, Math.max(0, animationMs) / 1000 * TRANSPORT_METERS_PER_SECOND / length) : 1;
}
function movePoint(points, t) {
  const lengths = points.slice(1).map((p, i) => Math.hypot(p.x - points[i].x, p.y - points[i].y));
  let distance = lengths.reduce((a, b) => a + b, 0) * Math.max(0, Math.min(1, t)), index = 0;
  while (index < lengths.length - 1 && distance > lengths[index]) distance -= lengths[index++];
  const f = lengths[index] ? distance / lengths[index] : 0, a = points[index], b = points[index + 1];
  return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, angle: Math.atan2(b.y - a.y, b.x - a.x) };
}
function drawMoves() {
  if (!$('routes').checked) return;
  const focused = events.filter(e => e.block === selected);
  const renderEvents = focused.length ? [...events.filter(e => e.block !== selected), ...focused] : events;
  for (let i = 0; i < renderEvents.length; i++) {
    const e = renderEvents[i], route = path(e.from, e.to);
    if (!route || route.length < 2) continue;
    const points = route.map(code => nodes[code]), focus = e.block === selected;
    ctx.globalAlpha = focus ? .95 : selected ? .07 : .16;
    line(points, colors[e.action], focus ? 3 : 1.3);
    ctx.globalAlpha = 1;
    if (playing || elapsed > 0 || focus) {
      const t = transportProgress(points);
      const point = movePoint(points, t), s = screen(point);
      const b = D.blocks[e.block];
      const w = Math.max(7, Math.min(28, b.length * zoom)), h = Math.max(4, Math.min(16, b.width * zoom));
      ctx.save(); ctx.translate(s.x, s.y); ctx.rotate(point.angle);
      ctx.fillStyle = colors[e.action]; ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.2;
      ctx.fillRect(-w / 2, -h / 2, w, h); ctx.strokeRect(-w / 2, -h / 2, w, h); ctx.restore();
      if (focus) {
        ctx.font = '600 12px sans-serif'; ctx.textAlign = 'center'; ctx.fillStyle = colors[e.action];
        ctx.fillText(e.block + ' · ' + e.action, s.x, s.y - h / 2 - 8);
      }
    }
  }
}
function drawMinimap() {
  const mini = $('minimap'), c = mini.getContext('2d'), b = bounds();
  const mw = mini.width, mh = mini.height, z = Math.min((mw - 14) / (b.x1 - b.x0), (mh - 23) / (b.y1 - b.y0));
  const ox = (mw - (b.x1 - b.x0) * z) / 2 - b.x0 * z, oy = (mh - (b.y1 - b.y0) * z) / 2 - b.y0 * z + 5;
  c.clearRect(0, 0, mw, mh);
  for (const n of Object.values(nodes)) {
    c.fillStyle = occupancy[n.code] ? '#7bacca' : '#d0dce6';
    c.fillRect((n.x - n.width / 2) * z + ox, (n.y - n.depth / 2) * z + oy, Math.max(1.5, n.width * z), Math.max(1.5, n.depth * z));
  }
  c.fillStyle = '#3978eb12'; c.strokeStyle = '#5281df'; c.lineWidth = 1;
  const x = -offset.x / zoom * z + ox, y = -offset.y / zoom * z + oy;
  c.fillRect(x, y, W / zoom * z, H / zoom * z); c.strokeRect(x, y, W / zoom * z, H / zoom * z);
}
function drawActivity() {
  const chart = $('activity'), c = chart.getContext('2d'), r = chart.getBoundingClientRect();
  const dpr = devicePixelRatio || 1, width = r.width || 900, height = 38;
  chart.width = Math.round(width * dpr); chart.height = height * dpr; c.setTransform(dpr, 0, 0, dpr, 0, 0);
  const counts = dates.map(date => (D.daily_moves[date] || []).length), maximum = Math.max(1, ...counts);
  const bw = width / dates.length;
  for (let i = 0; i < counts.length; i++) {
    const h = counts[i] / maximum * (height - 5);
    c.fillStyle = i === day ? '#3169e7' : i < day ? '#b4c9f3' : '#e1e8f3';
    c.fillRect(i * bw, height - h, Math.max(.5, bw - .65), h);
  }
  c.fillStyle = '#3169e7'; c.fillRect(day / Math.max(1, dates.length - 1) * (width - 2), 0, 2, height);
}
function draw(now) {
  if (!D) return;
  const dt = last ? Math.min(now - last, 100) : 0; last = now;
  if (playing) {
    elapsed += dt * (3000 / Number($('speed').value || 3000));
    phase = Math.min(1, elapsed / dayDuration);
    if (phase >= 1) {
      if (!replayOnly && day < dates.length - 1) setDay(day + 1);
      else setPlaying(false);
    }
  }
  if (dirty || playing) {
    ctx.clearRect(0, 0, W, H); hit = [];
    drawBackground(); drawFacilities(); drawBlocks(); drawMoves(); drawMinimap();
    const meters = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000].find(n => n * zoom >= 55) || 2000;
    $('scale').style.width = meters * zoom + 'px'; $('scale').textContent = meters >= 1000 ? meters / 1000 + ' km' : meters + ' m';
    $('zoomLevel').textContent = `1 m = ${zoom.toFixed(2)} px · 면적 비례`;
    dirty = false;
  }
  requestAnimationFrame(draw);
}

function eventPosition(e) { const r = canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
function hitAt(x, y) { return [...hit].reverse().find(p => x >= p.x && x <= p.x + p.w && y >= p.y && y <= p.y + p.h); }
canvas.addEventListener('wheel', e => { e.preventDefault(); const p = eventPosition(e); zoomAt(Math.exp(-e.deltaY * .0015), p.x, p.y); $('tooltip').hidden = true; }, { passive: false });
canvas.onpointerdown = e => {
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY }); canvas.setPointerCapture(e.pointerId);
  $('tooltip').hidden = true;
  if (pointers.size === 1) { drag = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y }; moved = false; }
  else if (pointers.size === 2) {
    const [a, b] = [...pointers.values()];
    pinch = { distance: Math.hypot(a.x - b.x, a.y - b.y), x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; moved = true;
  }
};
canvas.onpointermove = e => {
  if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (pinch && pointers.size === 2) {
    const [a, b] = [...pointers.values()], r = canvas.getBoundingClientRect();
    const distance = Math.hypot(a.x - b.x, a.y - b.y), x = (a.x + b.x) / 2, y = (a.y + b.y) / 2;
    if (pinch.distance > 0) zoomAt(distance / pinch.distance, pinch.x - r.left, pinch.y - r.top);
    offset.x += x - pinch.x; offset.y += y - pinch.y; pinch = { distance, x, y }; dirty = true;
  } else if (drag && pointers.size === 1) {
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.hypot(dx, dy) > 4) moved = true;
    offset = { x: drag.ox + dx, y: drag.oy + dy }; dirty = true;
  } else if (!pointers.size) {
    const p = eventPosition(e), target = hitAt(p.x, p.y), tip = $('tooltip');
    canvas.style.cursor = target ? 'pointer' : 'grab';
    if (!target) { tip.hidden = true; return; }
    const n = nodes[target.code], b = D?.blocks[target.code];
    tip.textContent = n ? `${n.code} · ${n.kind}\n${n.area ? fmt(n.area) + ' m²' : '면적 미상'}${occupancy[n.code] ? ` · 보관 ${occupancy[n.code].blocks.length}개` : ''}`
      : b ? `${target.code} · ${(b.length * b.width).toFixed(1)} m²\n${b.length} × ${b.width} m` : '';
    tip.style.left = Math.max(6, Math.min(W - 235, p.x + 14)) + 'px';
    tip.style.top = Math.max(6, Math.min(H - 75, p.y + 14)) + 'px'; tip.hidden = false;
  }
};
canvas.onpointerup = e => {
  if (!moved && !pinch) {
    const p = eventPosition(e), target = hitAt(p.x, p.y);
    selected = target?.code || null; showDetail(); renderList(); dirty = true;
  }
  pointers.delete(e.pointerId); pinch = null;
  if (pointers.size === 1) { const p = [...pointers.values()][0]; drag = { ...p, ox: offset.x, oy: offset.y }; }
  else drag = null;
};
canvas.onpointercancel = () => { pointers.clear(); drag = null; pinch = null; };
canvas.onpointerleave = () => { $('tooltip').hidden = true; };
canvas.ondblclick = e => { const p = eventPosition(e); zoomAt(1.7, p.x, p.y); };
canvas.onkeydown = e => {
  const actions = { '+': () => zoomAt(1.4), '=': () => zoomAt(1.4), '-': () => zoomAt(1 / 1.4), '0': () => fit(),
    ArrowLeft: () => { offset.x += 60; }, ArrowRight: () => { offset.x -= 60; }, ArrowUp: () => { offset.y += 60; }, ArrowDown: () => { offset.y -= 60; } };
  if (actions[e.key]) { e.preventDefault(); actions[e.key](); dirty = true; }
};
$('plus').onclick = () => zoomAt(1.4); $('minus').onclick = () => zoomAt(1 / 1.4);
$('fit').onclick = () => { $('zone').value = ''; fit(); };
$('zone').onchange = e => fit(e.target.value ? Object.values(nodes).filter(n => n.zone === e.target.value) : undefined);
$('viewMode').onchange = () => { dirty = true; };
$('algorithm').onchange = e => activateSlot(Number(e.target.value));
$('routes').onchange = () => { dirty = true; }; $('labels').onchange = () => { dirty = true; };
function toggleExpanded(value = !expanded) {
  expanded = value; $('workspace').classList.toggle('expanded', expanded);
  document.body.style.overflow = expanded ? 'hidden' : '';
  $('expand').setAttribute('aria-label', expanded ? '지도 원래 크기로' : '지도 크게 보기');
  $('expand').textContent = expanded ? '×' : '⛶'; resize();
}
$('expand').onclick = () => toggleExpanded();
document.addEventListener('keydown', e => { if (e.key === 'Escape' && expanded) toggleExpanded(false); });
$('search').oninput = renderList;
for (const [id, name] of [['movesTab', 'moves'], ['yardsTab', 'yards'], ['blocksTab', 'blocks']]) $(id).onclick = () => { tab = name; renderList(); };
$('slider').oninput = e => setDay(+e.target.value);
$('activity').onclick = e => { const r = $('activity').getBoundingClientRect(); setDay(Math.round((e.clientX - r.left) / r.width * (dates.length - 1))); };
$('date').onchange = e => { const i = dates.indexOf(e.target.value); if (i >= 0) setDay(i); else e.target.value = dates[day]; };
$('prev').onclick = () => setDay(day - 1); $('next').onclick = () => setDay(day + 1);
$('play').onclick = () => { if (day === dates.length - 1 && !playing) setDay(0); setPlaying(!playing); };
$('speed').onchange = () => { dirty = true; };
$('compareLink').onclick = () => { $('comparison').open = true; };
$('comparison').addEventListener('toggle', drawConvergence);

function validDate(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value + 'T00:00:00Z'))
    && new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value;
}
function validateResult(result) {
  if (!result || typeof result !== 'object' || !result.assignment || typeof result.assignment !== 'object' || Array.isArray(result.assignment)
    || !result.daily_moves || typeof result.daily_moves !== 'object' || Array.isArray(result.daily_moves)) throw Error('assignment와 daily_moves 객체가 필요합니다.');
  if (typeof result.total_cost !== 'number' || !Number.isFinite(result.total_cost)) throw Error('total_cost는 유한한 숫자여야 합니다.');
  for (const [code, yard] of Object.entries(result.assignment)) {
    if (!Object.hasOwn(shared.blocks, code)) throw Error(`알 수 없는 블록: ${code}`);
    if (!yards.some(y => y.code === yard)) throw Error(`알 수 없는 적치장: ${yard}`);
  }
  const days = Object.keys(result.daily_moves).sort();
  if (!days.length) throw Error('daily_moves에 날짜가 필요합니다.');
  for (const date of days) {
    if (!validDate(date) || !Array.isArray(result.daily_moves[date])) throw Error(`잘못된 날짜/이동 목록: ${date}`);
    for (const e of result.daily_moves[date]) {
      if (!e || !Object.hasOwn(shared.blocks, e.block) || !Object.hasOwn(nodes, e.from) || !Object.hasOwn(nodes, e.to) || !Object.hasOwn(colors, e.action)) throw Error(`${date}: 블록·출발지·도착지·action을 확인하세요.`);
      if (e.action === '입고' && result.assignment[e.block] !== e.to || e.action === '출고' && result.assignment[e.block] !== e.from) throw Error(`${e.block}: 이동과 assignment의 적치장이 다릅니다.`);
      const b = shared.blocks[e.block];
      if ((e.action === '입고' || e.action === '직행') && date !== b.start || e.action === '출고' && date !== b.end) throw Error(`${e.block}: 공통 스케줄의 입출고일과 다릅니다.`);
    }
  }
  return result;
}
function slotRange(result) {
  const days = Object.keys(result.daily_moves);
  for (const code of Object.keys(result.assignment)) days.push(shared.blocks[code].start, shared.blocks[code].end);
  days.sort(); return [days[0], days.at(-1)];
}
function rebuildDates(preferred) {
  const ranges = slots.filter(s => s.result).flatMap(s => slotRange(s.result)).sort(); dates = [];
  for (let t = new Date(ranges[0] + 'T00:00:00Z'); t.toISOString().slice(0, 10) <= ranges.at(-1); t.setUTCDate(t.getUTCDate() + 1)) dates.push(t.toISOString().slice(0, 10));
  $('slider').max = dates.length - 1; $('date').min = dates[0]; $('date').max = dates.at(-1);
  $('start').textContent = dates[0]; $('end').textContent = dates.at(-1);
  day = Math.max(0, dates.indexOf(preferred));
}
function activateSlot(index) {
  if (!slots[index]?.result) return;
  const preferred = dates[day]; currentSlot = index; D = { ...shared, ...slots[index].result }; selected = null;
  rebuildDates(preferred); $('sourcePath').textContent = slots[index].path;
  $('mapTitle').textContent = slots[index].name + ' · 야드 공간 지도';
  $('algorithmStatus').textContent = slots[index].name;
  const range = slotRange(D);
  $('period').textContent = `${range[0]} — ${range[1]} · 총 비용 ${fmt(D.total_cost)} (원본 단위)`;
  renderSlots(); setDay(day);
}
function renderSlots() {
  const root = $('slots'); root.replaceChildren();
  const selector = $('algorithm'); selector.replaceChildren();
  slots.forEach((s, i) => {
    if (s.result) {
      const option = document.createElement('option'); option.value = i; option.textContent = s.name;
      selector.append(option);
    }
    const card = document.createElement('div'); card.className = 'slot' + (i === currentSlot ? ' chosen' : '');
    const name = document.createElement('input'); name.className = 'slot-name'; name.value = s.name; name.maxLength = 40;
    name.setAttribute('aria-label', `슬롯 ${i + 1} 이름`);
    name.onchange = () => { s.name = name.value.trim() || s.id; renderComparison(); renderSlots(); if (i === currentSlot) { $('mapTitle').textContent = s.name + ' · 야드 공간 지도'; $('algorithmStatus').textContent = s.name; } };
    card.append(name);
    const info = document.createElement('small');
    const metrics = benchmarkMetrics(s), seconds = metrics?.timing?.solver_seconds;
    info.textContent = s.result ? `${s.path} · ${slotRange(s.result).join(' ~ ')}\n${s.metrics_status || '실행 정보 없음'}${metrics?.selected_method ? ` · 선택 ${metrics.selected_method.toUpperCase()}` : ''}${Number.isFinite(seconds) ? ` · 풀이 ${seconds.toFixed(3)}s` : ''}` : `미등록 · ${s.path}`; card.append(info);
    const actions = document.createElement('div'); actions.className = 'slot-actions';
    const view = document.createElement('button'); view.textContent = i === currentSlot ? '보는 중' : '지도 보기'; view.disabled = !s.result;
    view.onclick = () => activateSlot(i); actions.append(view);
    const label = document.createElement('label'); label.className = 'upload'; label.append(document.createTextNode(s.result ? 'JSON 교체' : 'JSON 등록'));
    const file = document.createElement('input'); file.type = 'file'; file.accept = '.json,application/json'; file.setAttribute('aria-label', s.name + ' 결과 JSON 업로드');
    file.onchange = async () => {
      const uploaded = file.files[0]; if (!uploaded) return;
      try {
        const candidate = validateResult(JSON.parse(await uploaded.text()));
        s.result = candidate; s.path = uploaded.name; s.metrics = null; s.metrics_status = '업로드 결과 · 실행 정보 없음'; $('slotStatus').textContent = s.name + ' 결과를 등록했습니다.'; activateSlot(i);
      } catch (error) { $('slotStatus').textContent = '등록 실패: ' + error.message; file.value = ''; }
    };
    label.append(file); actions.append(label); card.append(actions); root.append(card);
  });
  selector.value = String(currentSlot);
}
function benchmarkMetrics(slot) {
  const m = slot?.metrics, r = slot?.result;
  if (!m || !r || m.problem_fingerprint !== shared.environment?.problem_fingerprint) return null;
  if (m.feasibility?.valid !== true) return null;
  if (!Number.isFinite(m.cost?.total) || Math.abs(m.cost.total - r.total_cost) > Math.max(1e-4, Math.abs(r.total_cost) * 1e-9)) return null;
  return m;
}
function renderComparison() {
  if (!slots.length) return;
  const root = $('comparisonBody'); root.replaceChildren();
  const reference = benchmarkMetrics(slots.find(slot => slot.id === 'milp'));
  $('benchmarkContext').textContent = reference?.solver?.termination_status
    ? `동일 입력의 결과를 비교합니다. 최신 MILP 종료 상태: ${reference.solver.termination_status} · ${reference.solver.optimality_proven ? '최적성 확인' : '최적성 미확인'}. 완료한 실행 결과가 자동 반영됩니다.`
    : 'MILP 기준선은 종료 상태·실행 시간이 기록되지 않은 과거 해입니다. 새 MILP 계산은 상단의 실행 버튼으로 시작하세요.';

  const total = yards.reduce((s, y) => s + y.area, 0);
  for (let i = 0; i < slots.length; i++) {
    const s = slots[i], row = document.createElement('tr'); row.className = i === currentSlot ? 'current' : '';
    const solverStatus = s.metrics?.solver;
    const milpLabel = s.id === 'milp' || s.id === 'milp_audit';
    const statusNote = milpLabel ? (solverStatus?.optimality_proven ? ' · 최적성 확인' : solverStatus?.termination_status === 'FEASIBLE' ? ' · 가능해 / 최적성 미확인' : ' · 과거 해 / 종료 상태 미기록') : '';
    const values = [s.name + statusNote];
    if (!s.result) values.push('미등록', '—', '—', '—', '—', '—', '—', '—', '—', '—');
    else {
      const r = s.result, [first, end] = slotRange(r), date = dates[day], within = first <= date && date <= end;
      const stored = Object.entries(r.assignment).filter(([c]) => shared.blocks[c].start <= date && date < shared.blocks[c].end), areas = {};
      for (const [c, y] of stored) areas[y] = (areas[y] || 0) + shared.blocks[c].length * shared.blocks[c].width;
      const area = Object.values(areas).reduce((a, b) => a + b, 0), max = Math.max(0, ...yards.map(y => (areas[y.code] || 0) / y.area * 100));
      const moves = r.daily_moves[date] || [];
      const metrics = benchmarkMetrics(s), baseline = slots.find(slot => slot.id === 'milp');
      const comparable = metrics && benchmarkMetrics(baseline) && baseline.result.total_cost > 0;
      const gap = comparable ? (r.total_cost / baseline.result.total_cost - 1) * 100 : null;
      const seconds = metrics?.timing?.solver_seconds, improvement = metrics?.improvement_percent;
      values.push(fmt(r.total_cost), gap === null ? '환경 미확인' : (gap > 0 ? '+' : '') + gap.toFixed(3) + '%',
        Number.isFinite(seconds) && seconds >= 0 ? seconds.toFixed(3) + ' s' : '—',
        Number.isFinite(improvement) ? improvement.toFixed(3) + '%' : '—',
        Number.isFinite(metrics?.iterations) ? fmt(metrics.iterations) : '—',
        fmt(Object.keys(r.assignment).length), within ? fmt(stored.length) : '기간 밖',
        within ? `${fmt(area)} m² (${(area / total * 100).toFixed(1)}%)` : '—', within ? max.toFixed(1) + '%' : '—',
        within ? `${moves.length} / ${moves.filter(e => e.action === '입고').length} / ${moves.filter(e => e.action === '출고').length} / ${moves.filter(e => e.action === '직행').length}` : '—');
    }
    for (const text of values) { const cell = document.createElement('td'); cell.textContent = text; row.append(cell); } root.append(row);
  }
  const current = slots[currentSlot];
  if (current?.result) { const [first, end] = slotRange(current.result); if (dates[day] < first || dates[day] > end) $('dayinfo').textContent += ' · 현재 슬롯의 결과 기간 밖'; }
  drawConvergence();
}

function drawConvergence() {
  if (!shared) return;
  const chart = $('convergence'), c = chart.getContext('2d'), rect = chart.getBoundingClientRect();
  const width = rect.width || 900, height = 190, dpr = devicePixelRatio || 1;
  chart.width = Math.round(width * dpr); chart.height = height * dpr; c.setTransform(dpr, 0, 0, dpr, 0, 0);
  const palette = ['#8c9daf', '#3169e7', '#13a58e', '#9374ce'];
  const series = slots.filter(s => s.id !== 'meta').map(s => ({ slot: s, metrics: benchmarkMetrics(s) }))
    .filter(s => s.metrics?.history?.length).map((s, i) => ({ ...s, color: palette[i % palette.length],
      points: s.metrics.history.filter(p => Number.isFinite(p.seconds) && p.seconds >= 0 && Number.isFinite(p.best_cost)) }))
    .filter(s => s.points.length);
  const legend = $('convergenceLegend'); legend.replaceChildren();
  if (!series.length) { $('convergenceStatus').textContent = '메타휴리스틱 실행 후 탐색 이력이 표시됩니다.'; return; }
  const baselineSlot = slots.find(s => s.id === 'milp'), baseline = benchmarkMetrics(baselineSlot);
  const costs = series.flatMap(s => s.points.map(p => p.best_cost));
  if (baseline) costs.push(baseline.cost.total);
  const min = Math.min(...costs), max = Math.max(...costs), pad = Math.max(1, (max - min) * .12);
  const low = min - pad, high = max + pad;
  const duration = Math.max(.1, ...series.map(s => s.points.at(-1).seconds));
  const left = 72, right = width - 18, top = 12, bottom = height - 29;
  const px = t => left + t / duration * (right - left), py = value => bottom - (value - low) / (high - low) * (bottom - top);
  c.font = '11px sans-serif'; c.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const value = low + (high - low) * i / 4, y = py(value);
    c.strokeStyle = '#e7edf5'; c.beginPath(); c.moveTo(left, y); c.lineTo(right, y); c.stroke();
    c.fillStyle = '#8a9bb0'; c.textAlign = 'right'; c.fillText(Math.abs(value) >= 1e6 ? (value / 1e6).toFixed(1) + '백만' : fmt(value), left - 10, y + 4);
    c.textAlign = 'center'; c.fillText((duration * i / 4).toFixed(1) + 's', px(duration * i / 4), height - 8);
  }
  function label(text, color) { const span = document.createElement('span'); span.textContent = text; span.style.color = color; legend.append(span); }
  if (baseline) {
    c.strokeStyle = '#496079'; c.setLineDash([5, 4]); c.beginPath();
    c.moveTo(left, py(baseline.cost.total)); c.lineTo(right, py(baseline.cost.total)); c.stroke(); c.setLineDash([]);
    label(baseline.solver?.optimality_proven ? 'MILP · 최적성 확인' : 'MILP 저장해 · 최적성 미확인', '#496079');
  }
  for (const s of series) {
    c.strokeStyle = s.color; c.lineWidth = 2; c.beginPath();
    s.points.forEach((p, i) => i ? c.lineTo(px(p.seconds), py(p.best_cost)) : c.moveTo(px(p.seconds), py(p.best_cost)));
    if (s.points.length === 1) c.lineTo(right, py(s.points[0].best_cost));
    c.stroke(); label(s.slot.name, s.color);
  }
  $('convergenceStatus').textContent = '가로: 메타휴리스틱 탐색 경과 시간 (공통 그리디 구축 별도) · MILP 점선은 최종 저장값이며 시간별 탐색 이력이 아닙니다.';
}

async function refreshResults() {
  const response = await fetch('assets/data.json', { cache: 'no-store' });
  if (!response.ok) throw Error('새 결과를 불러오지 못했습니다.');
  const data = await response.json();
  if (!D) return;
  const chosen = slots[currentSlot]?.id;
  setPlaying(false);
  shared = data;
  nodes = Object.fromEntries(data.nodes.map(n => [n.code, { ...n, ...(Number.isFinite(n.x) && Number.isFinite(n.y) ? {} : world(n)) }]));
  yards = Object.values(nodes).filter(n => n.kind === '적치장' && n.area > 0);
  graph = {}; routeCache.clear();
  for (const r of data.roads) {
    (graph[r.source] ??= []).push({ to: r.target, time: r.time });
    if (r.both) (graph[r.target] ??= []).push({ to: r.source, time: r.time });
  }
  slots = data.slots.map(slot => ({ ...slot }));
  for (const slot of slots) if (slot.result) validateResult(slot.result);
  let index = slots.findIndex(slot => slot.id === chosen && slot.result);
  if (index < 0) index = slots.findIndex(slot => slot.result);
  activateSlot(index);
}

fetch('assets/data.json').then(r => {
  if (!r.ok) throw Error(`데이터 요청 실패 (${r.status})`);
  return r.json();
}).then(data => {
  shared = data;
  nodes = Object.fromEntries(data.nodes.map(n => [n.code, { ...n, ...(Number.isFinite(n.x) && Number.isFinite(n.y) ? {} : world(n)) }]));
  yards = Object.values(nodes).filter(n => n.kind === '적치장' && n.area > 0);
  for (const r of data.roads) {
    (graph[r.source] ??= []).push({ to: r.target, time: r.time });
    if (r.both) (graph[r.target] ??= []).push({ to: r.source, time: r.time });
  }
  slots = (data.slots || [{ id: 'milp', name: 'MILP', path: 'runs/milp/result.json', result: data }]).map(s => ({ ...s }));
  for (const s of slots) if (s.result) validateResult(s.result);
  const layout = data.layout;
  $('layoutStatus').textContent = layout ? `시설 겹침 ${layout.corrected_overlaps} · 최소 간격 ${layout.minimum_gap_m} m · 면적 비례` : '면적 비례 · GPS 기반 도식';
  resize(); fit(); activateSlot(slots.findIndex(s => s.result));
  new ResizeObserver(resize).observe($('mapwrap'));
  new ResizeObserver(drawConvergence).observe($('convergenceWrap'));
  requestAnimationFrame(draw);
}).catch(error => {
  $('error').textContent = error.message + ' · python3 dashboard/build_data.py 실행 후 HTTP 서버로 열어주세요.';
  $('stats').textContent = '데이터를 불러오지 못했습니다.';
});
