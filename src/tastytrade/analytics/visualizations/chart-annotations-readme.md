## Displaying Lines Without Labels

Sometimes you want to display reference lines without cluttering the chart with text labels. There are two ways to achieve this:

### 1. Using label=None

Setting `label=None` will prevent any label from being displayed:

```python
# Line with no label
HorizontalLine(
    price=prior_day.close * 1.005,  # 0.5% above prior close
    label=None,  # No label will be displayed
    color="#FFFFFF",
    line_dash="dashdot",
    opacity=0.4
)
```

### 2. Using show_label=False

Alternatively, you can set any label but disable its display:

```python
# Line with a hidden label
HorizontalLine(
    price=prior_day.close * 0.995,  # 0.5% below prior close
    label="Hidden label",  # Label exists but won't be shown
    color="#FFFFFF",
    show_label=False  # Prevents the label from being displayed
)
```

### Use Cases for Unlabeled Lines

Unlabeled lines are useful for:
- Creating minor grid lines
- Adding subtle reference points
- Showing bands or channels without cluttering the chart
- Creating background visual guides## Custom Time Ranges for Horizontal Lines

You can limit horizontal lines to specific time periods, which is useful for:
- Session-specific levels (morning, afternoon, overnight)
- Highlighting ranges where a level was respected
- Showing when a support/resistance level was broken
- Creating trading zones for specific strategies

### Basic Time Range Example

```python
from datetime import datetime
import pytz

# Create timezone-aware datetime objects
et_tz = pytz.timezone("America/New_York")
morning_start = datetime(2025, 2, 26, 9, 30, tzinfo=et_tz)
morning_end = datetime(2025, 2, 26, 11, 30, tzinfo=et_tz)

# Create a horizontal line for morning session only
morning_high = 450.25
horizontal_lines = [
    HorizontalLine(
        price=morning_high,
        label="Morning High",
        color="#4CAF50",  # Green
        extend_to_end=False,  # Use custom time range instead of full width
        start_time=morning_start,
        end_time=morning_end
    )
]
```

### Session Boundaries Example

```python
# Define trading sessions
market_open = datetime(2025, 2, 26, 9, 30, tzinfo=et_tz)
morning_end = datetime(2025, 2, 26, 11, 30, tzinfo=et_tz)
lunch_end = datetime(2025, 2, 26, 13, 30, tzinfo=et_tz)
market_close = datetime(2025, 2, 26, 16, 0, tzinfo=et_tz)

# Get session highs/lows from your data
morning_high = df.filter((pl.col("time") >= market_open) &
                          (pl.col("time") <= morning_end))["high"].max()

lunch_high = df.filter((pl.col("time") >= morning_end) &
                         (pl.col("time") <= lunch_end))["high"].max()

afternoon_high = df.filter((pl.col("time") >= lunch_end) &
                             (pl.col("time") <= market_close))["high"].max()

# Create session-specific levels
horizontal_lines = [
    # Morning session high - only visible during morning hours
    HorizontalLine(
        price=morning_high,
        label="AM High",
        color="#4CAF50",
        extend_to_end=False,
        start_time=market_open,
        end_time=morning_end
    ),

    # Lunch session high - only visible during lunch hours
    HorizontalLine(
        price=lunch_high,
        label="Lunch High",
        color="#4CAF50",
        line_dash="dash",
        extend_to_end=False,
        start_time=morning_end,
        end_time=lunch_end
    ),

    # Afternoon session high - only visible during afternoon hours
    HorizontalLine(
        price=afternoon_high,
        label="PM High",
        color="#4CAF50",
        line_dash="dashdot",
        extend_to_end=False,
        start_time=lunch_end,
        end_time=market_close
    ),
]
```# Chart Annotations Guide

This guide explains how to use horizontal price levels and vertical time lines in the TastyTrade SDK's charting system.

## Horizontal Price Levels

Horizontal lines can be used to highlight significant price levels such as:
- Previous day's high, low, or close
- Support and resistance levels
- Pivot points
- Moving averages
- VWAP (Volume Weighted Average Price)
- Entry and exit price targets

### Basic Usage

```python
from tastytrade.analytics.visualizations.plots import HorizontalLine, plot_macd_with_hull

# Create horizontal lines
horizontal_lines = [
    HorizontalLine(
        price=prior_day.close,
        label="Prior Close",
        color="#FFA500",  # Orange
        line_dash="dot",
    ),
    HorizontalLine(
        price=support_level,
        label="Support",
        color="#4CAF50",  # Green
    ),
]

# Plot with horizontal lines
plot_macd_with_hull(
    df=df_macd,
    pad_value=prior_day.close,
    horizontal_lines=horizontal_lines
)
```

### HorizontalLine Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| price | float | Required | The y-value (price) where the line will be drawn |
| label | str | None | Text label for the line. Set to None to display no label |
| color | str | "white" | Color of the line (name, hex, or rgb) |
| line_width | float | 1.0 | Width of the line in pixels |
| line_dash | str | "solid" | Line style ("solid", "dot", "dash", "longdash", "dashdot", "longdashdot") |
| opacity | float | 0.7 | Opacity of the line (0.0 to 1.0) |
| text_position | str | "left" | Position of the label ("left", "middle", "right") |
| show_label | bool | True | Whether to display the label text |
| label_font_size | int | 11 | Font size for the label |
| extend_to_end | bool | True | Whether the line should extend to the full width of the chart |
| start_time | datetime | None | Custom start time for the horizontal line |
| end_time | datetime | None | Custom end time for the horizontal line |

## Vertical Time Lines

Vertical lines can be used to mark significant times during the trading day:
- Market open and close
- Regular session hours
- Economic announcement times
- Known volatility periods (e.g., "Power Hour")
- Pre/post market transitions

### Basic Usage

```python
from tastytrade.analytics.visualizations.plots import VerticalLine, plot_macd_with_hull
import pytz

# Create vertical time lines
et_tz = pytz.timezone("America/New_York")
market_open = datetime(2025, 2, 26, 9, 30, tzinfo=et_tz)
market_close = datetime(2025, 2, 26, 16, 0, tzinfo=et_tz)

vertical_lines = [
    VerticalLine(
        time=market_open,
        label="Market Open",
        color="#FFFFFF",
        line_width=1.5,
    ),
    VerticalLine(
        time=market_close,
        label="Market Close",
        color="#FFFFFF",
        line_width=1.5,
    ),
]

# Plot with vertical time lines
plot_macd_with_hull(
    df=df_macd,
    vertical_lines=vertical_lines
)
```

### VerticalLine Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| time | datetime | Required | The x-value (datetime) where the line will be drawn |
| label | str | Time value | Text label for the line |
| color | str | "white" | Color of the line (name, hex, or rgb) |
| line_width | float | 1.0 | Width of the line in pixels |
| line_dash | str | "solid" | Line style ("solid", "dot", "dash", "longdash", "dashdot", "longdashdot") |
| opacity | float | 0.7 | Opacity of the line (0.0 to 1.0) |
| text_position | str | "top" | Position of the label ("top", "middle", "bottom") |
| show_label | bool | True | Whether to display the label text |
| label_font_size | int | 11 | Font size for the label |

## Common Use Cases

### Previous Day Levels
```python
horizontal_lines = [
    HorizontalLine(
        price=prior_day.close,
        label="PDC",
        color="#FFA500",  # Orange
    ),
    HorizontalLine(
        price=prior_day.high,
        label="PDH",
        color="#4CAF50",  # Green
    ),
    HorizontalLine(
        price=prior_day.low,
        label="PDL",
        color="#EF5350",  # Red
    ),
]
```

### Pivot Points
```python
# Calculate pivot points
pivot = (prior_day.high + prior_day.low + prior_day.close) / 3
r1 = 2 * pivot - prior_day.low
s1 = 2 * pivot - prior_day.high

horizontal_lines = [
    HorizontalLine(price=pivot, label="Pivot", color="#FFFFFF"),
    HorizontalLine(price=r1, label="R1", color="#00FFFF"),
    HorizontalLine(price=s1, label="S1", color="#FF66FE"),
]
```

### Key Market Times
```python
market_open = datetime(2025, 2, 26, 9, 30, tzinfo=et_tz)

vertical_lines = [
    VerticalLine(time=market_open, label="Market Open", color="#FFFFFF"),
    VerticalLine(time=market_open + timedelta(minutes=15), label="9:45", color="#888888"),
    VerticalLine(time=market_open + timedelta(hours=1), label="10:30", color="#888888"),
    VerticalLine(time=market_open.replace(hour=14, minute=0), label="14:00", color="#888888"),
    VerticalLine(time=market_open.replace(hour=15, minute=0), label="Power Hour", color="#FFFFFF"),
    VerticalLine(time=market_open.replace(hour=16, minute=0), label="Market Close", color="#FFFFFF"),
]
```

## Advanced Example

```python
# Calculate trading setups
vwap = calculate_vwap(df)  # Your VWAP calculation
opening_range_high = df.filter(pl.col("time") < market_open + timedelta(minutes=15))["high"].max()
opening_range_low = df.filter(pl.col("time") < market_open + timedelta(minutes=15))["low"].min()

# Create visualization elements
horizontal_lines = [
    HorizontalLine(price=vwap, label="VWAP", color="#E0E0E0", line_dash="dash"),
    HorizontalLine(price=opening_range_high, label="ORH", color="#4CAF50"),
    HorizontalLine(price=opening_range_low, label="ORL", color="#EF5350"),
]

vertical_lines = [
    VerticalLine(time=market_open, label="Open", color="#FFFFFF"),
    VerticalLine(time=market_open + timedelta(minutes=15), label="OR End", color="#FFFFFF"),
]

# Generate chart
plot_macd_with_hull(
    df=df_macd,
    pad_value=prior_day.close,
    horizontal_lines=horizontal_lines,
    vertical_lines=vertical_lines,
)
```

## Tips for Effective Charts

1. **Use a consistent color scheme** - Keep similar elements the same color (e.g., support levels in green, resistance in red)
2. **Limit the number of lines** - Too many lines can make the chart cluttered and hard to read
3. **Use different line styles** - Solid, dashed, and dotted lines help distinguish different types of levels
4. **Adjust opacity** - Less important lines can be more transparent
5. **Position labels thoughtfully** - Avoid overlapping text by using left/right positioning
6. **Use concise labels** - Short labels like "PDC" (Prior Day Close) save space

By combining horizontal price levels and vertical time lines, you can create comprehensive charts that clearly highlight important trading information.
