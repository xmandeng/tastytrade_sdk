// Trade pins: numbered chips, click-to-pin cards and dot-toggled profit
// zones. The server sends one marker per order event; this module snaps
// them to bars, owns the pinned card and keeps the zone primitive in step.
const tradeCard = document.getElementById('tradeCard');
let pinnedTrade = null;   // { m, hit } for the open card
let tradesVisible = true;

// Event timestamps fall inside bars; snap each to the last bar at or before
// it (works at any interval). barClose is the price fallback for events
// that don't carry their own spot (closes).
function snapMarkersToCandles(markers, candles) {
  if (!markers || !markers.length || !candles.length) return [];
  const snapped = [];
  for (const m of markers) {
    let bar = null;
    for (const c of candles) { if (c.time <= m.time) bar = c; else break; }
    if (bar) snapped.push({
      ...m, time: bar.time, eventTime: m.time,
      barClose: bar.close, barHigh: bar.high, barLow: bar.low,
      id: `${m.kind}-${m.n}-${m.time}`,
    });
  }
  return snapped;
}

function setTrades(markers, candles) {
  tradeMarkers.setData(snapMarkersToCandles(markers, candles));
  profitZones.clear();
  pinnedTrade = null;
  renderTradeCard();
}

function setTradePinsVisible(v) {
  tradesVisible = v;
  tradeMarkers.setVisible(v);
  if (!v) { profitZones.clear(); pinnedTrade = null; renderTradeCard(); }
  else syncProfitZones();
}

function syncProfitZones() {
  const ids = new Set(tradeMarkers.zoneIds());
  profitZones.setZones(tradeMarkers._data
    .filter(m => ids.has(m.id) && m.breakEvens && m.breakEvens.length === 2)
    .map(m => ({ id: m.id, tStart: m.time, lo: m.breakEvens[0], hi: m.breakEvens[1] })));
}

// Chip click pins the card; a fly dot click toggles its zone; a click on
// bare chart unpins. Hit lists are in pane-0 media coordinates.
chart.subscribeClick(param => {
  if (!tradesVisible) return;
  const p = param.point;
  if (!p || (param.paneIndex !== undefined && param.paneIndex !== 0)) return;
  const nearest = (hits, radius) => {
    let best = null, bestD = Infinity;
    for (const h of hits) {
      const d = Math.hypot(p.x - h.x, p.y - h.y);
      if (d < bestD) { bestD = d; best = h; }
    }
    return bestD <= radius ? best : null;
  };
  // Generous hit radius: the dot is a 7 px target sitting among candles.
  const dot = nearest(tradeMarkers._dotHits, 14);
  if (dot) {
    const on = !tradeMarkers.zoneIds().includes(dot.m.id);
    tradeMarkers.setZoneActive(dot.m.id, on);
    syncProfitZones();
    return;
  }
  const chip = nearest(tradeMarkers._hits, 11);
  if (chip && pinnedTrade && pinnedTrade.m.id === chip.m.id) pinnedTrade = null;
  else pinnedTrade = chip ? { m: chip.m, hit: chip } : null;
  tradeMarkers.setPinned(pinnedTrade ? pinnedTrade.m.id : null);
  renderTradeCard();
});

function cardHeader(m) {
  const hue = tradeHue(m);
  const title = m.kind === 'entry' ? `ENTRY ${m.dir}`
    : m.kind === 'close' ? 'CLOSE'
    : m.kind === 'fly' ? `FLY ${m.arm}` : `EOD FLY ${m.arm}`;
  const sub = m.kind === 'close' ? (m.reason || '')
    : m.kind === 'fly' ? (m.lossless ? 'lossless' : 'deficit')
    : m.kind === 'eod_fly' ? 'long' : '';
  return `<div class="tc-head">` +
    `<span class="tc-num" style="background:${hue}">${m.n}</span>` +
    `<span class="tc-time">${fmtClock(m.eventTime != null ? m.eventTime : m.time)}</span>` +
    `<span class="tc-title" style="color:${hue}">${escapeHtml(title)}</span>` +
    `<span class="tc-sub">${escapeHtml(sub)}</span></div>`;
}

function netCell(net) {
  const cls = !net ? 'flat' : net.startsWith('-') ? 'neg' : (net === '$0' ? 'flat' : 'pos');
  return `<span class="tc-net ${cls}">${escapeHtml(net || '—')}</span>`;
}

function cardBody(m) {
  if (m.kind === 'entry' || m.kind === 'close') {
    const close = m.kind === 'close';
    const legs = m.legs || [];
    return `<div class="tc-grid ${close ? 'close' : 'entry'}">` +
      `<span class="tc-hdr">ARM</span><span class="tc-hdr">SPREAD</span><span class="tc-hdr r">CREDIT</span>` +
      (close ? `<span class="tc-hdr r">DEBIT</span><span class="tc-hdr r">NET</span>` : '') +
      legs.map(l =>
        `<span class="tc-arm">${escapeHtml(l.arm)}</span><span>${escapeHtml(l.spread)}</span><span class="r">${fmtPx(l.credit)}</span>` +
        (close ? `<span class="r">${fmtPx(l.cost)}</span>${netCell(l.net)}` : '')
      ).join('') + `</div>`;
  }
  const amtHdr = m.kind === 'fly' ? 'CREDIT' : 'DEBIT';
  const amt = m.kind === 'fly' ? m.credit : m.debit;
  const be = (m.breakEvens || []).map(v => String(v)).join(' / ');
  return `<div class="tc-lines">` +
    `<div><span class="tc-hdr">STRIKES</span><span>${(m.strikes || []).map(v => String(v)).join(' / ')}</span></div>` +
    `<div><span class="tc-hdr">${amtHdr}</span><span>${fmtPx(amt)}</span></div>` +
    `<div><span class="tc-hdr">B/E</span><span>${be || '—'}</span></div>` +
    `<div><span class="tc-hdr">NET</span>${netCell(m.net)}</div></div>`;
}

function renderTradeCard() {
  if (!pinnedTrade) { tradeCard.classList.remove('on'); return; }
  const { m, hit } = pinnedTrade;
  tradeCard.innerHTML = cardHeader(m) + cardBody(m);
  tradeCard.classList.add('on');
  const host = chartEl.clientWidth;
  const left = Math.max(4, Math.min(axisLeftWidth() + hit.x - 10, host - tradeCard.offsetWidth - 4));
  const above = TradeMarkersPrimitive.side(m) === 'above';
  const top = above ? hit.y + 14 : Math.max(4, hit.y - tradeCard.offsetHeight - 14);
  tradeCard.style.left = `${left}px`;
  tradeCard.style.top = `${top}px`;
}
