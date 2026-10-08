// Toolbar, URL parameters and the WebSocket router. Loaded last; wires the
// other modules to the server's init/update/level messages.
const INTERVALS = [
  { value:'m', label:'1m' }, { value:'5m', label:'5m' },
  { value:'15m', label:'15m' }, { value:'30m', label:'30m' },
  { value:'1h', label:'1h' }, { value:'1d', label:'1d' },
];
let currentSymbol = 'SPX';
let currentInterval = 'm';
let ws = null;
let intentionalClose = false;
let connectTimer = null;

function intervalLabel(intv) { return INTERVALS.find(i => i.value === intv)?.label || intv; }
function setStatus(state) { document.getElementById('statusDot').className = 'status-dot ' + state; }

// Trade arm pairs the chart can show; the server carries the same registry.
const ARMS = [
  { value: 'early', label: 'EARLY' },
  { value: 'close', label: 'ON CLOSE' },
];

function getParams() {
  const p = new URLSearchParams(window.location.search);
  const arm = ARMS.some(a => a.value === p.get('arm')) ? p.get('arm') : 'close';
  return { symbol: p.get('symbol') || 'SPX', interval: p.get('interval') || 'm', date: p.get('date') || '', arm };
}

function renderControls() {
  const seg = document.getElementById('mktExtCtrl');
  seg.innerHTML = `
    <button class="seg-btn ${hasMarketHours ? 'active' : ''}" onclick="toggleMarketHours()">RTH</button>
    <button class="seg-btn ${hasMarketHours ? '' : 'active'}" onclick="toggleMarketHours()">EXT</button>`;
  const current = getParams().arm;
  document.getElementById('armCtrl').innerHTML = ARMS.map(a =>
    `<button class="seg-btn ${a.value === current ? 'active' : ''}" onclick="setArm('${a.value}')">${a.label}</button>`
  ).join('');
}

// The arm choice lives in the URL so a link or reload keeps it; the server
// re-sends markers and the STATS card for the chosen pair on reconnect.
function setArm(arm) {
  if (arm === getParams().arm) return;
  const p = new URLSearchParams(window.location.search);
  p.set('arm', arm);
  history.replaceState(null, '', '?' + p.toString());
  renderControls();
  connect();
}

function renderToolbar() {
  document.getElementById('symbolBtn').textContent = currentSymbol;
  // ThinkorSwim-style timeframe badge: one session at the chosen aggregation.
  document.getElementById('intervalBtn').textContent = `1 D : ${intervalLabel(currentInterval)}`;
}

function initDropdown(btnId, listId, onSelect) {
  const btn = document.getElementById(btnId);
  const list = document.getElementById(listId);
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    document.querySelectorAll('.dropdown-list.open').forEach(el => { if (el.id !== listId) el.classList.remove('open'); });
    list.classList.toggle('open');
  });
  list.addEventListener('click', (e) => {
    const item = e.target.closest('.dropdown-item');
    if (!item) return;
    onSelect(item.dataset.value);
    list.classList.remove('open');
  });
}

function populateIntervals() {
  document.getElementById('intervalList').innerHTML = INTERVALS.map(i =>
    `<div class="dropdown-item ${i.value === currentInterval ? 'active' : ''}" data-value="${i.value}">${i.label}</div>`
  ).join('');
}

async function populateSymbols() {
  try {
    const resp = await fetch('/api/symbols');
    const data = await resp.json();
    document.getElementById('symbolList').innerHTML = (data.symbols || []).map(s =>
      `<div class="dropdown-item ${s === currentSymbol ? 'active' : ''}" data-value="${s}">${s}</div>`
    ).join('');
  } catch (e) { /* unavailable */ }
}

document.addEventListener('click', () => {
  document.querySelectorAll('.dropdown-list.open').forEach(el => el.classList.remove('open'));
});

function setUrlParams(sym, intv) {
  const p = new URLSearchParams(window.location.search);
  p.set('symbol', sym); p.set('interval', intv);
  history.replaceState(null, '', '?' + p.toString());
}

initDropdown('symbolBtn', 'symbolList', (sym) => { currentSymbol = sym; setUrlParams(sym, currentInterval); renderToolbar(); connect(); });
initDropdown('intervalBtn', 'intervalList', (intv) => { currentInterval = intv; setUrlParams(currentSymbol, intv); renderToolbar(); connect(); });

// Studies dropdown opens the toggle panel; row clicks are handled by studies.js.
(function () {
  const btn = document.getElementById('studiesBtn');
  const list = document.getElementById('studiesList');
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    document.querySelectorAll('.dropdown-list.open').forEach(el => { if (el.id !== 'studiesList') el.classList.remove('open'); });
    list.classList.toggle('open');
    btn.classList.toggle('active', list.classList.contains('open'));
  });
  list.addEventListener('click', (e) => e.stopPropagation());
  document.addEventListener('click', () => btn.classList.remove('active'));
})();

function connect(dateOverride) {
  if (connectTimer) clearTimeout(connectTimer);
  connectTimer = setTimeout(() => doConnect(dateOverride), 100);
}

function applyInit(msg) {
  clearAllLevels();
  initOR();
  if (msg.date) {
    document.getElementById('dateInput').value = msg.date;
    try {
      const todayET = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date());
      chartIsLiveToday = (msg.date === todayET);
    } catch (e) { chartIsLiveToday = false; }
  } else {
    chartIsLiveToday = false;
  }

  lastCandles = msg.candles;
  if (msg.candles.length) {
    // Axis precision follows the price level: whole points above 1000, one
    // decimal above 100, cents above 1, four places below.
    const mid = msg.candles[Math.floor(msg.candles.length / 2)].close;
    const prec = mid >= 1000 ? 0 : mid >= 100 ? 1 : mid >= 1 ? 2 : 4;
    const mv = mid >= 1000 ? 1 : mid >= 100 ? 0.1 : mid >= 1 ? 0.01 : 0.0001;
    candleSeries.applyOptions({ priceFormat: { type: 'price', precision: prec, minMove: mv } });
    // Level badges keep cents whatever the axis shows: 7712.30, not 7712.
    levelAxisSeries.applyOptions({ priceFormat: { type: 'price', precision: Math.max(2, prec), minMove: Math.min(0.01, mv) } });
  }
  candleSeries.setData(msg.candles);
  setLevelAxisData(msg.candles);
  updateLastPriceBadge(msg.candles.length ? msg.candles[msg.candles.length - 1] : null);
  setTrades(msg.trades, msg.candles);
  renderPnl(msg.pnl);
  computeBounds(msg.candles);
  if (hasMarketHours) msg.candles.forEach(c => processCandleOR(c));

  if (msg.hma && msg.hma.length) hmaPrimitive.setData(msg.hma); else hmaPrimitive.clear();
  setLowerData('kalVel', msg.kalman || []);
  setLowerData('macd', msg.macd || []);
  setLowerData('ivHv', msg.ivHv || []);
  if (msg.dailyCandle) registerPriorDay(msg.dailyCandle);

  renderControls();
  applyStudyState();
  setTimeout(() => { setTradingHoursView(); sizePanes(); layoutStrips(); renderStrips(); }, 100);
}

function applyUpdate(msg) {
  candleSeries.update(msg.candle);
  levelAxisSeries.update({ time: msg.candle.time, value: msg.candle.close });
  updateLastPriceBadge(msg.candle);
  if (msg.pnl) renderPnl(msg.pnl);
  if (lastCandles.length && lastCandles[lastCandles.length - 1].time === msg.candle.time) {
    lastCandles[lastCandles.length - 1] = msg.candle;
  } else {
    lastCandles.push(msg.candle);
  }
  processCandleOR(msg.candle);
  if (msg.hma) hmaPrimitive.update(msg.hma);
  if (msg.kalman) updateLower('kalVel', msg.kalman);
  if (msg.macd) updateLower('macd', msg.macd);
  applyStudy(msg);
  if (stripBarTime == null) renderStrips();
}

// Lower-study points that arrive on their own clock (the IV index's bars)
// or alongside a candle; each is a partial point for one bar.
function applyStudy(msg) {
  (msg.ivHv || []).forEach(p => updateLower('ivHv', p));
}

function doConnect(dateOverride) {
  setStatus('connecting');
  intentionalClose = true;
  const { symbol, interval, date } = getParams();
  currentSymbol = symbol; currentInterval = interval;
  renderToolbar();
  populateIntervals();

  if (ws) { try { ws.close(); } catch (e) {} ws = null; }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  let url = `${proto}//${location.host}/ws?symbol=${symbol}&interval=${interval}&arm=${getParams().arm}`;
  const chartDate = dateOverride || date;
  if (chartDate) url += `&date=${chartDate}`;
  ws = new WebSocket(url);

  ws.onopen = () => { intentionalClose = false; setStatus('connected'); };
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === 'error') { setStatus('disconnected'); return; }
    if (msg.type === 'init') { applyInit(msg); return; }
    if (msg.type === 'update') { applyUpdate(msg); return; }
    if (msg.type === 'study') { applyStudy(msg); if (stripBarTime == null) renderStrips(); return; }
    if (msg.type === 'level') {
      const id = (msg.label || '').replace(/\s+/g, '').toLowerCase();
      registerLevel(id, [{ price: msg.price, label: msg.label, color: msg.color, lineStyle: msg.lineStyle }], false);
    }
  };
  ws.onclose = () => {
    if (intentionalClose) return;
    setStatus('disconnected');
    setTimeout(() => connect(), 3000);
  };
  ws.onerror = () => setStatus('disconnected');
}

document.getElementById('dateInput').addEventListener('change', (e) => {
  if (!e.isTrusted || !e.target.value) return;
  const p = new URLSearchParams(window.location.search);
  p.set('date', e.target.value);
  history.replaceState(null, '', '?' + p.toString());
  connect(e.target.value);
});

populateSymbols();
populateIntervals();
renderStudiesPanel();
connect();
