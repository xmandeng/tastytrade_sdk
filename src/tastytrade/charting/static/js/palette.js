// Chart palette (mirrors plots.py) and shared formatting helpers. Loaded
// first; every later module reads these globals. Classic scripts share one
// global scope, so no bundler or module loader is needed.
const C = {
  bg:'#131313', grid:'rgba(255,255,255,0.03)', text:'#787b86', border:'#2a2a2a',
  accent:'#58a6ff',
  candleUpBorder:'#4CAF50', candleUpBody:'rgba(19,19,19,0.1)',
  candleDownBorder:'#EF5350', candleDownBody:'#EF5350',
  hmaUp:'#01FFFF', hmaDown:'#FF66FE',
  kalVelUp:'#2196F3', kalVelDown:'#FF9800',
  macdValue:'#01FFFF', macdSignal:'#F8E9A6', macdZero:'rgba(255,255,255,0.12)',
  // Prior-day reference levels — amber/green/red, slightly transparent so they
  // recede behind candles. Amber for Prior Close matches the conventional
  // "reference price" hue used by most charting platforms.
  priorClose:'rgba(255, 183, 77, 0.65)',
  priorHigh: 'rgba(76, 175, 80, 0.60)',
  priorLow:  'rgba(244, 67, 54, 0.60)',
  // Axis-badge fills — lightweight-charts renders price-axis label backgrounds
  // as opaque (alpha in rgba gets stripped). To get a quiet, tinted badge we
  // pre-blend the level color against the chart bg (#131313) at ~22% alpha
  // and pass the result as a solid rgb. Bakes the math but lands the visual.
  priorCloseBadge: 'rgb(71, 55, 32)',
  priorHighBadge:  'rgb(32, 53, 32)',
  priorLowBadge:   'rgb(69, 30, 27)',
  badgeText:       '#a0a4ad',
  orLevel:   'rgba(76, 175, 80, 0.60)',
  // Profit zone of a pinned fly: amber like the fly chips, faint fill.
  zoneLine: 'rgba(255, 183, 77, 0.75)',
  zoneFill: 'rgba(255, 183, 77, 0.07)',
  pos:'#3fb950', neg:'#ef5350',
};

// Trade chip hues derive from the chart palette: candle green/red for
// entry direction, grey for closes, amber for fly structures.
const TRADE_STYLE = {
  entry_bull: { hue: C.candleUpBorder },
  entry_bear: { hue: C.candleDownBody },
  close:      { hue: '#9AA0A6' },
  fly:        { hue: '#FFB74D' },
  eod_fly:    { hue: '#FFB74D' },
};

function tradeHue(m) {
  const key = m.kind === 'entry' ? `entry_${m.dir}` : m.kind;
  return (TRADE_STYLE[key] || TRADE_STYLE.close).hue;
}

// Opaque badge fill: hue pre-blended over the chart bg (#131313) at the given
// alpha — quiet ground, full contrast for text.
function blendOverBg(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  const mix = (c, b) => Math.round(c * alpha + b * (1 - alpha));
  const r = mix((n >> 16) & 255, 19), g = mix((n >> 8) & 255, 19), b = mix(n & 255, 19);
  return `rgb(${r},${g},${b})`;
}

const MARKET_OPEN_H = 9, MARKET_OPEN_M = 30;

// Chart times are ET epochs shifted so UTC getters read as ET.
function fmtTime(epochSec) {
  const d = new Date(epochSec * 1000);
  const h = d.getUTCHours(), m = d.getUTCMinutes();
  const hh = h > 12 ? h - 12 : (h === 0 ? 12 : h);
  const mm = m < 10 ? '0' + m : '' + m;
  return `${hh}:${mm} ${h >= 12 ? 'PM' : 'AM'}`;
}

// Short clock for pane strips and trade cards: "10:50".
function fmtClock(epochSec) {
  const d = new Date(epochSec * 1000);
  let h = d.getUTCHours(); const m = d.getUTCMinutes();
  if (h > 12) h -= 12; if (h === 0) h = 12;
  return `${h}:${m < 10 ? '0' + m : m}`;
}

function fmtPx(v, digits = 2) {
  return v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(digits);
}

// Study axes: up to two decimals with trailing zeros trimmed (12, 0.5, -0.25).
function fmtTrim(v) {
  if (v == null || Number.isNaN(Number(v))) return '';
  return String(Number(Number(v).toFixed(2)));
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;' }[c]));
}
