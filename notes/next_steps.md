# Next Steps for TastyTrade Live Charts

## Feature Enhancements

### Time Range Controls
- Add start and end time controls
  - Start time: Allow user to specify historical start point
  - End time: Default to "Live" for real-time updates
  - Consider adding preset ranges (1D, 5D, 1M, etc.)

### UI Improvements
- Remove "Price" from candlestick legend as it's redundant
- Add a "Delete All Charts" button for better UX
  - Position in top right corner
  - Add confirmation dialog to prevent accidental clicks

### Chart Behavior
- Fix zoom persistence issue
  - Currently charts reset zoom level on updates
  - Need to maintain zoom and pan position during data updates
  - Consider using Plotly's `uirevision` property more effectively

## Implementation Notes
- Time range implementation should consider:
  - Timezone handling (ensure consistent EDT/EST display)
  - Date picker component selection
  - Proper DXLink historical data fetching
- Chart deletion should properly clean up:
  - DXLink subscriptions
  - Interval callbacks
  - DOM elements
