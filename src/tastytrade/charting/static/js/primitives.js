// lightweight-charts v5 primitives owned by the candle pane: the Hull MA
// polyline, time-bounded level lines, trade chips and the pinned-fly profit
// zone. Each keeps its own data and contributes to autoscale where relevant.

// ============================================================================
// Series Primitive: HMA as a colored polyline on the candle series.
// ============================================================================
class HmaPrimitive {
  constructor() {
    this._data = [];
    this._series = null;
    this._chart = null;
    this._visible = true;
    this._paneView = { renderer: () => ({ draw: (target) => this.drawPolyline(target) }) };
  }
  attached({ series, chart }) { this._series = series; this._chart = chart; }
  detached() { this._series = null; this._chart = null; }
  paneViews() { return [this._paneView]; }
  updateAllViews() {}

  requestRedraw() {
    // Primitives don't trigger redraws on data mutation — nudge the host
    // series so the chart repaints. applyOptions({}) is a no-op options change.
    if (this._series) this._series.applyOptions({});
  }
  setData(arr) {
    this._data = (arr || []).slice().sort((a, b) => a.time - b.time);
    this.requestRedraw();
  }
  update(point) {
    if (!point || point.value == null) return;
    const last = this._data[this._data.length - 1];
    if (last && last.time === point.time) this._data[this._data.length - 1] = point;
    else this._data.push(point);
    this.requestRedraw();
  }
  clear() { this._data = []; this.requestRedraw(); }
  setVisible(v) { this._visible = v; this.requestRedraw(); }
  last() { return this._data.length ? this._data[this._data.length - 1] : null; }
  at(time) { return this._data.find(p => p.time === time) || null; }

  autoscaleInfo() {
    if (!this._visible || !this._data.length) return null;
    let lo = Infinity, hi = -Infinity;
    for (const p of this._data) {
      if (p.value == null) continue;
      if (p.value < lo) lo = p.value;
      if (p.value > hi) hi = p.value;
    }
    return lo === Infinity ? null : { priceRange: { minValue: lo, maxValue: hi } };
  }

  drawPolyline(target) {
    if (!this._visible || !this._series || !this._chart || this._data.length < 2) return;
    const series = this._series;
    const ts = this._chart.timeScale();
    target.useBitmapCoordinateSpace(scope => {
      const ctx = scope.context;
      const xR = scope.horizontalPixelRatio, yR = scope.verticalPixelRatio;
      ctx.lineWidth = Math.max(1, Math.round(yR));
      ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      for (let i = 0; i < this._data.length - 1; i++) {
        const p1 = this._data[i], p2 = this._data[i + 1];
        if (p1.value == null || p2.value == null) continue;
        const x1 = ts.timeToCoordinate(p1.time), x2 = ts.timeToCoordinate(p2.time);
        const y1 = series.priceToCoordinate(p1.value), y2 = series.priceToCoordinate(p2.value);
        if (x1 == null || x2 == null || y1 == null || y2 == null) continue;
        ctx.strokeStyle = p1.color || '#888';
        ctx.beginPath();
        ctx.moveTo(x1 * xR, y1 * yR);
        ctx.lineTo(x2 * xR, y2 * yR);
        ctx.stroke();
      }
    });
  }
}

// Resolve a bound time to a bitmap x, clamping to the pane edge when the
// time is outside the renderable range. Shared by the bounded primitives.
function resolveBoundX(ts, time, width, xR, sideFallback) {
  if (time == null) return sideFallback;
  const x = ts.timeToCoordinate(time);
  if (x != null) return x * xR;
  const range = ts.getVisibleRange();
  if (range) {
    if (time <= range.from) return 0;
    if (time >= range.to) return width;
  }
  return sideFallback;
}

// ============================================================================
// Series Primitive: horizontal level line clipped to a [tStart, tEnd] window
// (prior-day OHLC during the session, opening range during RTH). Contributes
// its price to candle-pane autoscale.
// ============================================================================
class BoundedLineSegment {
  constructor(price, color, lineStyle, tStart, tEnd) {
    this._price = price;
    this._color = color;
    this._style = lineStyle; // 'solid' | 'dotted' | 'dashed'
    this._tStart = tStart;
    this._tEnd = tEnd;
    this._series = null;
    this._chart = null;
    this._paneView = { renderer: () => ({ draw: (target) => this.drawLine(target) }) };
  }
  attached({ series, chart }) { this._series = series; this._chart = chart; }
  detached() { this._series = null; this._chart = null; }
  paneViews() { return [this._paneView]; }
  updateAllViews() {}
  autoscaleInfo() { return { priceRange: { minValue: this._price, maxValue: this._price } }; }

  drawLine(target) {
    if (!this._series || !this._chart) return;
    const ts = this._chart.timeScale();
    const y = this._series.priceToCoordinate(this._price);
    if (y == null) return;
    // Either bound can be a function evaluated per redraw — used to clamp the
    // right edge to "end of data" so live ticks slide the line forward.
    const tStartV = typeof this._tStart === 'function' ? this._tStart() : this._tStart;
    const tEndV   = typeof this._tEnd   === 'function' ? this._tEnd()   : this._tEnd;
    target.useBitmapCoordinateSpace(scope => {
      const ctx = scope.context;
      const xR = scope.horizontalPixelRatio, yR = scope.verticalPixelRatio;
      const width = scope.bitmapSize.width;
      const x1Raw = resolveBoundX(ts, tStartV, width, xR, 0);
      const x2Raw = resolveBoundX(ts, tEndV, width, xR, width);
      if (x1Raw == null || x2Raw == null) return;
      if (x2Raw <= 0 || x1Raw >= width) return;
      ctx.lineWidth = Math.max(1, Math.round(yR));
      ctx.strokeStyle = this._color;
      if (this._style === 'dotted') ctx.setLineDash([2 * xR, 3 * xR]);
      else if (this._style === 'dashed') ctx.setLineDash([6 * xR, 4 * xR]);
      else ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(Math.max(0, x1Raw), y * yR);
      ctx.lineTo(Math.min(width, x2Raw), y * yR);
      ctx.stroke();
      ctx.setLineDash([]);
    });
  }
}

// ============================================================================
// Series Primitive: trade chips. Entries sit in the bottom gutter, closes and
// fly completions in the top gutter carrying the same structure number, so a
// trade reads as a pair. A thin pointer runs to a dot at the exact event
// price; fly dots are click targets that toggle the profit zone and wear a
// ring while it is on. All wording lives in the card (trades.js).
// ============================================================================
class TradeMarkersPrimitive {
  constructor() {
    this._data = [];
    this._hits = [];     // chip centers (media coords) for click hit-tests
    this._dotHits = [];  // fly price-point dots
    this._pinned = null;
    this._zones = new Set();
    this._visible = true;
    this._series = null;
    this._chart = null;
    this._paneView = { renderer: () => ({ draw: (target) => this.drawPins(target) }) };
  }
  attached({ series, chart }) { this._series = series; this._chart = chart; }
  detached() { this._series = null; this._chart = null; }
  paneViews() { return [this._paneView]; }
  updateAllViews() {}
  autoscaleInfo() { return null; }

  requestRedraw() { if (this._series) this._series.applyOptions({}); }
  setData(arr) {
    this._data = (arr || []).slice().sort((a, b) => a.time - b.time || a.n - b.n);
    this._pinned = null;
    this._zones = new Set();
    this.requestRedraw();
  }
  clear() { this.setData([]); }
  setVisible(v) { this._visible = v; this.requestRedraw(); }
  setPinned(id) { this._pinned = id; this.requestRedraw(); }
  setZoneActive(id, on) { if (on) this._zones.add(id); else this._zones.delete(id); this.requestRedraw(); }
  zoneIds() { return Array.from(this._zones); }

  static side(m) { return (m.kind === 'entry' || m.kind === 'eod_fly') ? 'below' : 'above'; }
  static isFly(m) { return m.kind === 'fly' || m.kind === 'eod_fly'; }

  drawPins(target) {
    this._hits = [];
    this._dotHits = [];
    if (!this._visible || !this._series || !this._chart || !this._data.length) return;
    const series = this._series;
    const ts = this._chart.timeScale();
    target.useBitmapCoordinateSpace(scope => {
      const ctx = scope.context;
      const r = scope.horizontalPixelRatio, yr = scope.verticalPixelRatio;
      const R = 7 * r;            // chip radius
      const GUTTER = 14 * r;      // pane edge -> chip center
      const LANE = 18 * r;        // inward offset per stacked chip
      ctx.font = `700 ${Math.round(9 * r)}px -apple-system, "Segoe UI", Roboto, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      const placed = { above: [], below: [] };
      for (const m of this._data) {
        const x = ts.timeToCoordinate(m.time);
        const price = m.price != null ? m.price : m.barClose;
        if (x == null || price == null) continue;
        const yPoint = series.priceToCoordinate(price);
        if (yPoint == null) continue;
        const side = TradeMarkersPrimitive.side(m);
        const cx = x * r;
        let lane = 0;
        for (const p of placed[side]) {
          if (Math.abs(cx - p.cx) < 2 * R + 3 * r && lane <= p.lane) lane = p.lane + 1;
        }
        placed[side].push({ cx, lane });
        const cy = side === 'above'
          ? GUTTER + lane * LANE
          : scope.bitmapSize.height - GUTTER - lane * LANE;
        const py = yPoint * yr;
        const hue = tradeHue(m);
        const pinned = this._pinned === m.id;
        const zoneOn = this._zones.has(m.id);
        this._hits.push({ x: cx / r, y: cy / yr, m });
        if (TradeMarkersPrimitive.isFly(m)) this._dotHits.push({ x: cx / r, y: py / yr, m });

        // Pointer: chip edge to the event point. Long by design, so it recedes.
        ctx.strokeStyle = hue;
        ctx.globalAlpha = 0.35;
        ctx.lineWidth = Math.max(1, Math.round(r));
        ctx.beginPath();
        ctx.moveTo(cx, cy + (side === 'above' ? R : -R));
        ctx.lineTo(cx, py);
        ctx.stroke();
        ctx.globalAlpha = 1;

        // Event dot, ringed while its profit zone is shown.
        ctx.beginPath();
        ctx.arc(cx, py, 2 * r, 0, 2 * Math.PI);
        ctx.fillStyle = hue;
        ctx.fill();
        if (zoneOn) {
          ctx.beginPath();
          ctx.arc(cx, py, 5 * r, 0, 2 * Math.PI);
          ctx.lineWidth = Math.max(1, Math.round(r));
          ctx.strokeStyle = C.zoneLine;
          ctx.stroke();
        }

        // Number chip, haloed against the grid; solid while pinned.
        ctx.beginPath();
        ctx.arc(cx, cy, R + 1.5 * r, 0, 2 * Math.PI);
        ctx.fillStyle = C.bg;
        ctx.fill();
        ctx.beginPath();
        ctx.arc(cx, cy, R, 0, 2 * Math.PI);
        ctx.fillStyle = pinned ? hue : blendOverBg(hue, 0.25);
        ctx.fill();
        ctx.lineWidth = Math.max(1, Math.round(1.25 * r));
        ctx.strokeStyle = hue;
        ctx.stroke();
        ctx.fillStyle = pinned ? C.bg : hue;
        ctx.fillText(String(m.n), cx, cy + 0.5 * r);
      }
    });
  }
}

// ============================================================================
// Series Primitive: profit zones of the flies whose dot was clicked. Two thin
// amber lines at the break evens with a faint fill between, from the fly's
// bar to the right edge. Contributes its bounds to autoscale so both edges
// stay on screen.
// ============================================================================
class ProfitZonePrimitive {
  constructor() {
    this._zones = [];   // [{ id, tStart, lo, hi }]
    this._series = null;
    this._chart = null;
    this._paneView = { renderer: () => ({ draw: (target) => this.drawZones(target) }) };
  }
  attached({ series, chart }) { this._series = series; this._chart = chart; }
  detached() { this._series = null; this._chart = null; }
  paneViews() { return [this._paneView]; }
  updateAllViews() {}
  requestRedraw() { if (this._series) this._series.applyOptions({}); }
  setZones(list) { this._zones = (list || []).slice(); this.requestRedraw(); }
  clear() { this.setZones([]); }

  autoscaleInfo() {
    if (!this._zones.length) return null;
    let lo = Infinity, hi = -Infinity;
    for (const z of this._zones) { lo = Math.min(lo, z.lo); hi = Math.max(hi, z.hi); }
    return { priceRange: { minValue: lo, maxValue: hi } };
  }

  drawZones(target) {
    if (!this._series || !this._chart || !this._zones.length) return;
    const ts = this._chart.timeScale();
    target.useBitmapCoordinateSpace(scope => {
      const ctx = scope.context;
      const xR = scope.horizontalPixelRatio, yR = scope.verticalPixelRatio;
      const width = scope.bitmapSize.width;
      for (const z of this._zones) {
        const yHi = this._series.priceToCoordinate(z.hi);
        const yLo = this._series.priceToCoordinate(z.lo);
        if (yHi == null || yLo == null) continue;
        const x1 = Math.max(0, resolveBoundX(ts, z.tStart, width, xR, 0));
        if (x1 >= width) continue;
        const top = yHi * yR, bot = yLo * yR;
        ctx.fillStyle = C.zoneFill;
        ctx.fillRect(x1, top, width - x1, bot - top);
        ctx.strokeStyle = C.zoneLine;
        ctx.lineWidth = Math.max(1, Math.round(yR));
        ctx.beginPath();
        ctx.moveTo(x1, top); ctx.lineTo(width, top);
        ctx.moveTo(x1, bot); ctx.lineTo(width, bot);
        ctx.stroke();
      }
    });
  }
}
