// Level lines on the candle pane: prior-day OHLC and the opening range.
// Each level is TWO objects — a price line on levelAxisSeries for the badge
// on the right axis (line suppressed) and a BoundedLineSegment on the candle
// series for the clipped line itself. Visibility is owned by
// studyState; entries stay registered and applyLevelVisibility reconciles.
const levels = {};  // id -> { entries, axisLabel, lines }

function lwcStyle(s) {
  if (s === 'dot' || s === 'dotted') return LightweightCharts.LineStyle.Dotted;
  if (s === 'dash' || s === 'dashed') return LightweightCharts.LineStyle.Dashed;
  return LightweightCharts.LineStyle.Solid;
}

// Map level id -> {group, child} so visibility resolves through studyState.
const LEVEL_STUDY_MAP = {
  priorClose: { group: 'priorOHLC',    child: 'priorClose' },
  priorHigh:  { group: 'priorOHLC',    child: 'priorHigh'  },
  priorLow:   { group: 'priorOHLC',    child: 'priorLow'   },
  or5:        { group: 'openingRange', child: 'or5'        },
  or15:       { group: 'openingRange', child: 'or15'       },
  or30:       { group: 'openingRange', child: 'or30'       },
};

function isLevelVisible(id) {
  const m = LEVEL_STUDY_MAP[id];
  if (!m) return true;  // unmanaged (live levels from Redis)
  return studyState[m.group] && studyState[m.child];
}

function createLevelLine(entry, axisLabel) {
  const priceLineOpts = {
    price: entry.price, color: entry.color, lineWidth: 1,
    lineStyle: lwcStyle(entry.lineStyle),
    // Badge shows the price only; the strip carries the level names.
    axisLabelVisible: !!axisLabel, title: '',
    lineVisible: false,
  };
  if (entry.badgeColor)     priceLineOpts.axisLabelColor     = entry.badgeColor;
  if (entry.badgeTextColor) priceLineOpts.axisLabelTextColor = entry.badgeTextColor;
  const priceLine = levelAxisSeries.createPriceLine(priceLineOpts);
  const hasBounds = entry.tStart !== undefined || entry.tEnd !== undefined;
  let primitive = null;
  if (hasBounds) {
    primitive = new BoundedLineSegment(entry.price, entry.color, entry.lineStyle,
      entry.tStart ?? null, entry.tEnd ?? null, entry.autoscale !== false);
    candleSeries.attachPrimitive(primitive);
  } else {
    priceLine.applyOptions({ lineVisible: true });
  }
  return { priceLine, primitive };
}

function removeLevelLine(obj) {
  if (!obj) return;
  if (obj.priceLine) { try { levelAxisSeries.removePriceLine(obj.priceLine); } catch (e) {} }
  if (obj.primitive) { try { candleSeries.detachPrimitive(obj.primitive); } catch (e) {} }
}

function registerLevel(id, entries, axisLabel) {
  if (levels[id]) return;
  levels[id] = { entries, axisLabel: !!axisLabel, lines: [] };
  applyLevelVisibility(id);
}

function applyLevelVisibility(id) {
  const lv = levels[id];
  if (!lv) return;
  lv.lines.forEach(removeLevelLine);
  lv.lines = [];
  if (isLevelVisible(id)) lv.lines = lv.entries.map(e => createLevelLine(e, lv.axisLabel));
  dedupeBadges();
}

// Levels that coincide (the 5m and 15m opening-range lows on a quiet open)
// would stack identical badges; keep the first badge per price.
function dedupeBadges() {
  const seen = new Set();
  for (const id of Object.keys(levels)) {
    const lv = levels[id];
    if (!lv.axisLabel) continue;
    lv.lines.forEach((line, i) => {
      if (!line.priceLine) return;
      const key = Math.round(lv.entries[i].price * 100);
      const dup = seen.has(key);
      seen.add(key);
      line.priceLine.applyOptions({ axisLabelVisible: !dup });
    });
  }
}

function clearAllLevels() {
  Object.keys(levels).forEach(id => {
    levels[id].lines.forEach(removeLevelLine);
    delete levels[id];
  });
}

// Prior-day OHLC bounds: left is midnight of the chart date; right is the
// next midnight for a historical date, or follows the latest live tick
// (capped at 4 PM during RTH) when the chart shows today.
function registerPriorDay(dc) {
  const tStart = priorTimeStart;
  const tEnd = () => {
    if (!chartIsLiveToday) return priorTimeEnd;
    const lastT = lastCandles.length ? lastCandles[lastCandles.length - 1].time : levelTimeEnd;
    if (lastT > levelTimeEnd) return Math.min(priorTimeEnd, lastT);
    return levelTimeEnd;
  };
  const spec = [
    ['priorClose', dc.close, 'Prior Close', C.priorClose, C.priorCloseBadge],
    ['priorHigh',  dc.high,  'Prior Hi',    C.priorHigh,  C.priorHighBadge],
    ['priorLow',   dc.low,   'Prior Lo',    C.priorLow,   C.priorLowBadge],
  ];
  for (const [id, price, label, color, badge] of spec) {
    if (price == null) continue;
    registerLevel(id, [{ price, label, color, lineStyle: 'dotted',
      badgeColor: badge, badgeTextColor: C.badgeText, tStart, tEnd }], true);
  }
}

// ============================================================================
// Opening range: locks the high/low of the first N minutes after the open.
// ============================================================================
const OR_WINDOWS = [
  { min:5,  id:'or5',  label:'5m',  style:'solid',  opacity:0.6 },
  { min:15, id:'or15', label:'15m', style:'dashed', opacity:0.4 },
  { min:30, id:'or30', label:'30m', style:'dotted', opacity:0.3 },
];
const orState = {};

function initOR() {
  OR_WINDOWS.forEach(w => { orState[w.min] = { high: null, low: null, locked: false }; });
}

function processCandleOR(candle) {
  const d = new Date(candle.time * 1000);
  const minSinceOpen = (d.getUTCHours() - MARKET_OPEN_H) * 60 + (d.getUTCMinutes() - MARKET_OPEN_M);
  if (minSinceOpen < 0) return;
  OR_WINDOWS.forEach(w => {
    const st = orState[w.min];
    if (!st || st.locked) return;
    if (minSinceOpen >= w.min) {
      st.locked = true;
      if (st.high !== null) {
        registerLevel(w.id, [
          { price: st.high, label: `${w.label} Hi`, color: C.orLevel, lineStyle: w.style, tStart: levelTimeStart, tEnd: levelTimeEnd,
            badgeColor: C.priorHighBadge, badgeTextColor: C.badgeText },
          { price: st.low,  label: `${w.label} Lo`, color: C.orLevel, lineStyle: w.style, tStart: levelTimeStart, tEnd: levelTimeEnd,
            badgeColor: C.priorHighBadge, badgeTextColor: C.badgeText },
        ], true);
        renderStrips();
      }
      return;
    }
    if (st.high === null || candle.high > st.high) st.high = candle.high;
    if (st.low === null || candle.low < st.low) st.low = candle.low;
  });
}

// Values for the candle pane's label strip.
function levelSummary() {
  const price = id => (levels[id] && levels[id].entries[0]) ? levels[id].entries[0].price : null;
  return {
    priorClose: price('priorClose'), priorHigh: price('priorHigh'), priorLow: price('priorLow'),
    orLocked: OR_WINDOWS.filter(w => orState[w.min] && orState[w.min].locked).map(w => w.label),
  };
}
