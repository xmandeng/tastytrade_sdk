# TT-147: Lightweight Charts v5 Upgrade — Implementation Plan

> **Jira:** [TT-147](https://mandeng.atlassian.net/browse/TT-147)
> **Parent Story:** [TT-149](https://mandeng.atlassian.net/browse/TT-149) — Evaluate open-source charting frameworks
> **Sibling:** [TT-148](https://mandeng.atlassian.net/browse/TT-148) — KLineChart replacement evaluation
> **Branch:** `feature/TT-147-lightweight-charts-v5-upgrade`
> **Worktree:** `/tmp/worktrees/TT-147`

## Goal

Replace `src/tastytrade/charting/static/index.html` v4.2.0 implementation with a v5-native single-chart-multi-pane design. Eliminate the eight hand-rolled workarounds compensating for v4 limitations. No backend changes.

## Non-goals (v1)

- KLineChart evaluation (sibling TT-148)
- New indicators, drawing tools, or studies
- Backend changes (`server.py`, `feed.py`, `indicators.py` untouched)
- Custom Series Renderer for HMA (deferred — see "Deferred refinements" below)

## What changes

| v4 hack | v5 replacement |
|---|---|
| Two `createChart()` instances joined by manual time-scale + crosshair sync (`subscribeVisibleLogicalRangeChange` × 2 with a `syncing` flag) | One `createChart()`. MACD series go to `paneIndex: 1`. Time scale + crosshair shared natively. |
| Hand-coded resize handle (~70 LOC of CSS + JS mouse/touch drag) | `layout.panes.enableResize: true` |
| Invisible anchor series + hidden `'anchor-hidden'` price scale to extend the time axis past candle data | `timeScale().setVisibleRange()` alone (v5 honors empty regions) |
| Level lines as 2-point line series with `levelStartEpoch`/`levelEndEpoch` + manual extension on every EXT-mode tick | `candleSeries.createPriceLine({ price, color, lineStyle, title })` per level |
| `display: none` on TV branding `<a>` (CSS hack, breaks attribution compliance) | `layout.attributionLogo: false` |
| Width-padded price formatters so left-axis labels align across two charts | Single chart → single price-scale column → structurally aligned |
| `autoscaleInfoProvider: () => null` scattered across anchor/level series | `createPriceLine` lines aren't series — no opt-out needed |
| Deprecated `watermark:` option for "MACD (12,26,9)" label | Skipped in v1 (cosmetic). Follow-up: `IPanePrimitive` text watermark. |

## What stays

- All Python (`server.py`, `feed.py`, `indicators.py`) — WS payload contract unchanged
- HMA color-flip behavior, MACD 4-shade histogram colors, MKT/EXT toggle semantics
- Opening-range computation (5/15/30m), prior-day level fetch + autoscale extension
- Toolbar (symbol/interval/date dropdowns, MKT/EXT segmented control, status dot)
- Draggable legend
- `attributionLogo: false` replaces the CSS hack — TradingView attribution stays disabled (consistent with v4 behavior)

## Deferred refinements (post-v1)

- **HMA custom-series renderer** — collapse N segment-series per color run into one custom series with per-point color. v5 supports it via `ICustomSeriesPaneView`. Saves ~25 LOC and removes per-flip series allocation. Deferred because the existing segment approach works and the structural panes win is the headline.
- **MACD pane watermark** — implement via `IPanePrimitive` text watermark. Cosmetic; deferred.

## Build sequence

1. ✅ Worktree + branch created (`/tmp/worktrees/TT-147`, `feature/TT-147-lightweight-charts-v5-upgrade`)
2. ✅ Plan doc + new `index.html` in worktree
3. Push branch (triggers Jira → In Progress)
4. Smoke test: serve via existing `server.py` against InfluxDB history, verify chart renders
5. Live-tick test: 5+ min SPX 1m through Redis pub/sub
6. LOC delta + bundle size report
7. Recommendation back to parent TT-149

## Expected LOC delta

| Section | v4 LOC | v5 LOC |
|---|---|---|
| Two-chart setup + scale/crosshair sync | ~45 | 0 |
| Resize handle CSS + JS | ~70 | 0 |
| Anchor series + hidden price scale | ~25 | 0 |
| HMA segment-series management | ~40 | ~40 (kept; refactor deferred) |
| Level lines (2-pt series + tick extension) | ~35 | ~20 |
| autoscale overrides + width-padding fmt | ~15 | ~5 (just the prior-level extension) |
| Brand-link CSS hack | ~2 | 0 |
| **Net JS plumbing** | **~232** | **~65** |

Target net file size: ~700 lines (vs 989 today).

## Risks

1. **`setVisibleRange()` without anchor data** — if v5 doesn't render labels for empty regions, fallback is whitespace data points on the candle series. Test on MKT mode for instruments with sparse pre-market data.
2. **Pane resize ergonomics** — v5's built-in separator may not match the current min-height enforcement (100px candle / 60px macd). Likely fine; verify.
3. **`createPriceLine` autoscale** — `createPriceLine` lines do **not** auto-expand the price scale. Prior-day levels still need the candle-series `autoscaleInfoProvider` override to include them in y-range.
4. **Bundle size** — v5 standalone ≈190 KB vs v4 ≈165 KB (~15% over CDN). Acceptable.

## Verification evidence (for PR)

- Screenshot: two panes with shared time axis + crosshair
- Screenshot: level lines via `createPriceLine` (prior-day + opening-range)
- Tick log: 5+ minutes of live SPX 1m, no scaling glitches
- Diff: actual LOC removed/added
- Bundle size delta (curl `Content-Length` on each CDN URL)
