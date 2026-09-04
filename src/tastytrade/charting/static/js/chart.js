// The chart instance, the candle series and the primitives that live on it,
// plus the session-bound view helpers. Later modules hang off these globals.
const chartEl = document.getElementById('chart');

const chart = LightweightCharts.createChart(chartEl, {
  layout: {
    background: { type: 'solid', color: C.bg },
    textColor: C.text,
    fontFamily: 'monospace',
    panes: { separatorColor: C.border, separatorHoverColor: C.accent, enableResize: true },
    attributionLogo: false,
  },
  grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
  crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  // One axis column on the left for price and every study, as the original
  // chart had it; the right edge stays clear.
  leftPriceScale: { visible: true, borderColor: C.border, scaleMargins: { top: 0.05, bottom: 0.05 } },
  rightPriceScale: { visible: false },
  localization: { timeFormatter: (t) => fmtTime(t) },
  timeScale: {
    borderColor: C.border, timeVisible: true, secondsVisible: false,
    tickMarkFormatter: (time, tickMarkType) => {
      if (tickMarkType <= 2) {
        const d = new Date(time * 1000);
        const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        return `${months[d.getUTCMonth()]} ${d.getUTCDate()}`;
      }
      return fmtClock(time);
    },
  },
  handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true },
  handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true },
});

// --- Pane 0: candles + the overlay primitives ---
const candleSeries = chart.addSeries(LightweightCharts.CandlestickSeries, {
  upColor: C.candleUpBody, downColor: C.candleDownBody,
  borderUpColor: C.candleUpBorder, borderDownColor: C.candleDownBorder,
  wickUpColor: C.candleUpBorder, wickDownColor: C.candleDownBorder,
  lastValueVisible: false, priceLineVisible: false,
  priceScaleId: 'left',
}, 0);

// Last-price badge on the axis, coloured by the last bar's direction. The
// candlestick series' own badge inherits the hollow up-body colour, so a
// price line carries it instead (label only, no line).
let lastPriceLine = null;
function updateLastPriceBadge(bar) {
  if (lastPriceLine) { try { candleSeries.removePriceLine(lastPriceLine); } catch (e) {} lastPriceLine = null; }
  if (!bar) return;
  const up = bar.close >= bar.open;
  lastPriceLine = candleSeries.createPriceLine({
    price: bar.close, lineVisible: false, axisLabelVisible: true, title: '',
    axisLabelColor: up ? C.candleUpBorder : C.candleDownBorder, axisLabelTextColor: C.bg,
  });
}

const hmaPrimitive = new HmaPrimitive();
candleSeries.attachPrimitive(hmaPrimitive);
const tradeMarkers = new TradeMarkersPrimitive();
candleSeries.attachPrimitive(tradeMarkers);
const profitZones = new ProfitZonePrimitive();
candleSeries.attachPrimitive(profitZones);

// Horizontal offset of the pane area inside #chart (the left axis width).
function axisLeftWidth() {
  try { return chart.priceScale('left').width(); } catch (e) { return 0; }
}

// ============================================================================
// Session state and bounds
// ============================================================================
let lastCandles = [];
// True iff the chart date == today in ET (the only case where the prior-day
// OHLC line may extend past 4:00 PM, to follow live afterhours ticks).
let chartIsLiveToday = false;
let hasMarketHours = true;

// Time bounds for level drawing, set by computeBounds() from the chart date.
//   levelTimeStart/End — 9:30 AM – 4:00 PM ET, for intraday-locked levels.
//   priorTimeStart/End — midnight to midnight of the chart date.
let levelTimeStart = 0, levelTimeEnd = 0;
let priorTimeStart = 0, priorTimeEnd = 0;
let viewStartEpoch = 0, levelStartEpoch = 0, marketCloseEpoch = 0;

function computeBounds(candles) {
  viewStartEpoch = 0; levelStartEpoch = 0; marketCloseEpoch = 0;
  levelTimeStart = 0; levelTimeEnd = 0;
  priorTimeStart = 0; priorTimeEnd = 0;
  if (candles.length) {
    const d = new Date(candles[0].time * 1000);
    const y = d.getUTCFullYear(), mo = d.getUTCMonth(), day = d.getUTCDate();
    viewStartEpoch   = Date.UTC(y, mo, day, 9, 30) / 1000;
    levelStartEpoch  = Date.UTC(y, mo, day, 9, 30) / 1000;
    marketCloseEpoch = Date.UTC(y, mo, day, 16, 30) / 1000;
    levelTimeStart   = Date.UTC(y, mo, day, 9, 30) / 1000;
    levelTimeEnd     = Date.UTC(y, mo, day, 16, 0) / 1000;
    priorTimeStart   = Date.UTC(y, mo, day, 0, 0) / 1000;
    priorTimeEnd     = Date.UTC(y, mo, day + 1, 0, 0) / 1000;
  }
  if (candles.length && hasMarketHours) {
    const anyInMarket = candles.some(c => c.time >= viewStartEpoch && c.time <= marketCloseEpoch);
    if (!anyInMarket) hasMarketHours = false;
  }
  if (!hasMarketHours) {
    viewStartEpoch = candles.length ? candles[0].time : 0;
    levelStartEpoch = viewStartEpoch;
    marketCloseEpoch = candles.length ? candles[candles.length - 1].time : 0;
  }
}

function floorHour(e) { return e - (e % 3600); }
function ceilHour(e)  { return e % 3600 === 0 ? e : floorHour(e) + 3600; }

function setTradingHoursView() {
  if (!hasMarketHours) {
    if (!lastCandles.length) return;
    const from = floorHour(lastCandles[0].time - 1800);
    const to = ceilHour(lastCandles[lastCandles.length - 1].time + 1800);
    chart.timeScale().setVisibleRange({ from, to });
    return;
  }
  if (viewStartEpoch === 0 || marketCloseEpoch === 0) return;
  // The session fills the pane: the open to five past the close (or just
  // past the latest bar while the day is still running). Starting exactly at
  // 9:30 keeps flat pre-market bars out of the autoscale.
  const from = viewStartEpoch;
  const lastCandle = lastCandles.length ? lastCandles[lastCandles.length - 1].time : levelStartEpoch;
  const to = Math.min(levelTimeEnd + 300, Math.max(lastCandle + 600, levelStartEpoch + 3600));
  chart.timeScale().setVisibleRange({ from, to });
}

function toggleMarketHours() {
  hasMarketHours = !hasMarketHours;
  computeBounds(lastCandles);
  setTradingHoursView();
  renderControls();
}

function candleAt(time) {
  for (let i = lastCandles.length - 1; i >= 0; i--) if (lastCandles[i].time === time) return lastCandles[i];
  return null;
}

function resizeChart() {
  if (chartEl.clientWidth && chartEl.clientHeight) chart.resize(chartEl.clientWidth, chartEl.clientHeight);
  // The observer fires on observe(), before panes.js has loaded.
  if (typeof sizePanes === 'function') { sizePanes(); layoutStrips(); }
}
window.addEventListener('resize', resizeChart);
new ResizeObserver(resizeChart).observe(chartEl);
