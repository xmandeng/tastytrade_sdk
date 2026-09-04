// Lower-pane stack manager. Each lower study owns its series factory, a data
// cache and a label strip; toggling one off removes its pane outright so the
// candle pane reclaims the height, and toggling it on remounts it at the
// right index from cache. Pane label strips are HTML overlays positioned
// from each pane's element.
const LOWER_PANE_H = { two: 150, one: 195 };

const lineOpts = (extra) => ({
  priceLineVisible: false, lastValueVisible: false,
  priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
  priceScaleId: 'right', ...extra,
});

const LOWER_STUDIES = [
  {
    key: 'macd', label: 'MACD', params: '(12, 26, 9)',
    mount(paneIndex) {
      const hist = chart.addSeries(LightweightCharts.HistogramSeries, lineOpts({}), paneIndex);
      const value = chart.addSeries(LightweightCharts.LineSeries, lineOpts({ color: C.macdValue, lineWidth: 1 }), paneIndex);
      const signal = chart.addSeries(LightweightCharts.LineSeries, lineOpts({ color: C.macdSignal, lineWidth: 1 }), paneIndex);
      value.createPriceLine({ price: 0, color: C.macdZero, lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: false });
      const mirror = mirrorOnLeftScale(hist, paneIndex);
      return { hist, value, signal, mirror, all: [hist, value, signal, mirror] };
    },
    load(objs, points) {
      objs.hist.setData(points.map(p => ({ time: p.time, value: p.histogram, color: p.histogramColor })));
      objs.value.setData(points.map(p => ({ time: p.time, value: p.value })));
      objs.signal.setData(points.map(p => ({ time: p.time, value: p.signal })));
      objs.mirror.setData(points.map(p => ({ time: p.time, value: p.histogram })));
    },
    update(objs, p) {
      objs.hist.update({ time: p.time, value: p.histogram, color: p.histogramColor });
      objs.value.update({ time: p.time, value: p.value });
      objs.signal.update({ time: p.time, value: p.signal });
      objs.mirror.update({ time: p.time, value: p.histogram });
    },
    values(p) {
      return p ? [
        { text: fmtPx(p.value), color: C.macdValue },
        { text: fmtPx(p.signal), color: C.macdSignal },
        { text: fmtPx(p.histogram), color: p.histogramColor || C.text },
      ] : [];
    },
  },
  {
    key: 'kalVel', label: 'Kalman velocity', params: '(q/r 0.025)',
    mount(paneIndex) {
      const vel = chart.addSeries(LightweightCharts.HistogramSeries, lineOpts({}), paneIndex);
      vel.createPriceLine({ price: 0, color: C.macdZero, lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: false });
      const mirror = mirrorOnLeftScale(vel, paneIndex);
      return { vel, mirror, all: [vel, mirror] };
    },
    load(objs, points) {
      objs.vel.setData(points.map(p => ({ time: p.time, value: p.velocity, color: p.velColor })));
      objs.mirror.setData(points.map(p => ({ time: p.time, value: p.velocity })));
    },
    update(objs, p) {
      if (p.velocity == null) return;
      objs.vel.update({ time: p.time, value: p.velocity, color: p.velColor });
      objs.mirror.update({ time: p.time, value: p.velocity });
    },
    values(p) {
      return p ? [{ text: fmtPx(p.velocity, 3), color: p.velColor || C.text }] : [];
    },
  },
];

const lowerStudy = key => LOWER_STUDIES.find(s => s.key === key);
const paneObjs = {};                       // key -> series handles while mounted
const paneCache = {};                      // key -> { points: [], byTime: Map }
LOWER_STUDIES.forEach(s => { paneCache[s.key] = { points: [], byTime: new Map() }; });
let mountedKeys = [];

function lowerVisibleKeys() {
  return LOWER_STUDIES.filter(s => studyState[s.key]).map(s => s.key);
}

function cacheLowerInit(key, points) {
  const c = paneCache[key];
  c.points = (points || []).slice();
  c.byTime = new Map(c.points.map(p => [p.time, p]));
}

function cacheLowerUpdate(key, p) {
  const c = paneCache[key];
  const last = c.points[c.points.length - 1];
  if (last && last.time === p.time) c.points[c.points.length - 1] = p; else c.points.push(p);
  c.byTime.set(p.time, p);
}

function lowerPointAt(key, time) {
  const c = paneCache[key];
  if (time != null && c.byTime.has(time)) return c.byTime.get(time);
  return c.points.length ? c.points[c.points.length - 1] : null;
}

// Removes every lower pane and remounts the visible ones in registry order.
function mountLowerPanes() {
  const wanted = lowerVisibleKeys();
  if (wanted.join() === mountedKeys.join()) return;
  for (const key of mountedKeys) {
    const objs = paneObjs[key];
    if (objs) objs.all.forEach(s => { try { chart.removeSeries(s); } catch (e) {} });
    delete paneObjs[key];
  }
  // A pane emptied of series may linger; drop any beyond the candle pane.
  try { while (chart.panes().length > 1) chart.removePane(chart.panes().length - 1); } catch (e) {}
  wanted.forEach((key, i) => {
    const study = lowerStudy(key);
    const objs = study.mount(i + 1);
    paneObjs[key] = objs;
    study.load(objs, paneCache[key].points);
  });
  mountedKeys = wanted;
  ensureStripElements();
  sizePanes();
  observePanes();
  layoutStrips();
  renderStrips();
}

// Pane geometry settles a frame after mounting or a separator drag; the
// strips follow each pane's element so they never sit on a stale edge.
const paneObserver = new ResizeObserver(() => { layoutStrips(); });
function observePanes() {
  paneObserver.disconnect();
  for (const pane of chart.panes()) {
    if (typeof pane.getHTMLElement !== 'function') continue;
    const el = pane.getHTMLElement();
    if (!el) continue;
    // The pane element is a table row, which ResizeObserver does not report
    // on; its cells do resize-observe, so watch those (and the row itself).
    paneObserver.observe(el);
    Array.from(el.children).forEach(cell => paneObserver.observe(cell));
  }
  requestAnimationFrame(layoutStrips);
}
// A separator drag ends with a pointer release over the chart; settle the
// strips once the new pane heights have been applied.
chartEl.addEventListener('pointerup', () => requestAnimationFrame(layoutStrips));

function setLowerData(key, points) {
  cacheLowerInit(key, points);
  const objs = paneObjs[key];
  if (objs) lowerStudy(key).load(objs, paneCache[key].points);
}

function updateLower(key, p) {
  if (!p) return;
  cacheLowerUpdate(key, p);
  const objs = paneObjs[key];
  if (objs) lowerStudy(key).update(objs, p);
}

// Candle pane takes whatever the lower panes leave: 150 px each when two
// are shown, 195 px when one, the full height when none.
function sizePanes() {
  const panes = chart.panes();
  if (!panes.length) return;
  const n = panes.length - 1;
  const lowerH = n >= 2 ? LOWER_PANE_H.two : LOWER_PANE_H.one;
  let axisH = 0;
  try { axisH = chart.timeScale().height(); } catch (e) {}
  const total = chartEl.clientHeight - axisH - n;
  if (total < 120) return;
  // Stretch factors are relative, so setting all of them at once lands the
  // exact proportions; sequential setHeight calls interfere with each other.
  const candleH = Math.max(120, total - n * lowerH);
  if (typeof panes[0].setStretchFactor === 'function') {
    panes[0].setStretchFactor(candleH);
    for (let i = 1; i < panes.length; i++) panes[i].setStretchFactor(lowerH);
  } else {
    for (let i = 1; i < panes.length; i++) panes[i].setHeight(lowerH);
    panes[0].setHeight(candleH);
  }
}

// ============================================================================
// Pane label strips (ThinkorSwim-style): name, parameters and live values at
// the top-left of each pane; lower strips carry a close control.
// ============================================================================
const stripsEl = document.getElementById('paneStrips');
let stripBarTime = null;   // hovered bar, or null for the latest bar

function ensureStripElements() {
  const want = ['candle', ...mountedKeys];
  Array.from(stripsEl.children).forEach(el => { if (!want.includes(el.dataset.pane)) el.remove(); });
  want.forEach(key => {
    if (!stripsEl.querySelector(`[data-pane="${key}"]`)) {
      const el = document.createElement('div');
      el.className = 'pane-strip';
      el.dataset.pane = key;
      stripsEl.appendChild(el);
    }
  });
}

function paneTop(i) {
  const panes = chart.panes();
  const pane = panes[i];
  if (!pane) return null;
  if (typeof pane.getHTMLElement === 'function') {
    const el = pane.getHTMLElement();
    if (el) return el.getBoundingClientRect().top - chartEl.getBoundingClientRect().top;
  }
  let top = 0;
  for (let k = 0; k < i; k++) top += panes[k].getHeight() + 1;
  return top;
}

function layoutStrips() {
  const left = axisLeftWidth() + 10;
  ['candle', ...mountedKeys].forEach((key, i) => {
    const el = stripsEl.querySelector(`[data-pane="${key}"]`);
    const top = paneTop(i);
    if (!el || top == null) return;
    el.style.top = `${top + 6}px`;
    el.style.left = `${left}px`;
  });
}

function stripValue(text, color) {
  return `<span class="ps-val" style="color:${color}">${escapeHtml(text)}</span>`;
}

function renderCandleStrip() {
  const el = stripsEl.querySelector('[data-pane="candle"]');
  if (!el) return;
  const bar = (stripBarTime != null && candleAt(stripBarTime)) || (lastCandles.length ? lastCandles[lastCandles.length - 1] : null);
  const up = bar ? bar.close >= bar.open : true;
  const line1 = [
    `<span class="ps-title">${escapeHtml(currentSymbol)}</span>`,
    `<span class="ps-params">${escapeHtml(intervalLabel(currentInterval))}</span>`,
    bar ? `<span class="ps-key">O</span>${stripValue(fmtPx(bar.open), '#d1d4dc')}` : '',
    bar ? `<span class="ps-key">H</span>${stripValue(fmtPx(bar.high), '#d1d4dc')}` : '',
    bar ? `<span class="ps-key">L</span>${stripValue(fmtPx(bar.low), '#d1d4dc')}` : '',
    bar ? `<span class="ps-key">C</span>${stripValue(fmtPx(bar.close), up ? C.candleUpBorder : C.candleDownBorder)}` : '',
  ].filter(Boolean).join('');
  const parts = [];
  if (studyState.hma) {
    const h = (bar && hmaPrimitive.at(bar.time)) || hmaPrimitive.last();
    if (h) parts.push(`<span class="ps-key">HMA (20)</span>${stripValue(fmtPx(h.value), h.color || C.hmaUp)}`);
  }
  const lv = levelSummary();
  if (studyState.priorOHLC && lv.priorClose != null) {
    parts.push(`<span class="ps-key">Prior</span>` +
      (studyState.priorClose ? stripValue(fmtPx(lv.priorClose), 'rgba(255,183,77,0.9)') : '') +
      (studyState.priorHigh ? stripValue(fmtPx(lv.priorHigh), 'rgba(76,175,80,0.9)') : '') +
      (studyState.priorLow ? stripValue(fmtPx(lv.priorLow), 'rgba(244,67,54,0.9)') : ''));
  }
  if (studyState.openingRange && lv.orLocked.length) {
    const on = OR_WINDOWS.filter(w => studyState[w.id] && lv.orLocked.includes(w.label)).map(w => w.label.replace('m', ''));
    if (on.length) parts.push(`<span class="ps-key">OR</span>${stripValue(on.join(' · '), 'rgba(76,175,80,0.9)')}`);
  }
  el.innerHTML = `<div class="ps-line">${line1}</div>` + (parts.length ? `<div class="ps-line">${parts.join('')}</div>` : '');
  // Top-gutter chips sit below the strip (strip top 6 px + its height + a gap).
  tradeMarkers.setTopInset(6 + el.offsetHeight + 16);
}

function renderLowerStrip(key) {
  const el = stripsEl.querySelector(`[data-pane="${key}"]`);
  if (!el) return;
  const study = lowerStudy(key);
  const vals = study.values(lowerPointAt(key, stripBarTime));
  el.innerHTML = `<div class="ps-line">` +
    `<span class="ps-title">${escapeHtml(study.label)}</span>` +
    `<span class="ps-params">${escapeHtml(study.params)}</span>` +
    vals.map(v => stripValue(v.text, v.color)).join('') +
    `<span class="pane-x" data-study="${key}" title="Hide pane">` +
    `<svg width="8" height="8" viewBox="0 0 8 8"><path d="M1 1 L7 7 M7 1 L1 7" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"></path></svg></span>` +
    `</div>`;
}

function renderStrips() {
  renderCandleStrip();
  mountedKeys.forEach(renderLowerStrip);
}

stripsEl.addEventListener('click', (e) => {
  const x = e.target.closest('.pane-x');
  if (!x) return;
  setStudy(x.dataset.study, false);
});

// Strips follow the crosshair bar, falling back to the latest bar.
chart.subscribeCrosshairMove(param => {
  const t = param && param.time != null ? param.time : null;
  if (t === stripBarTime) return;
  stripBarTime = t;
  renderStrips();
});
