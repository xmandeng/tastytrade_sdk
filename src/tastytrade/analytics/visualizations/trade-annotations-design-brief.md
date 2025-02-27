# Trade Annotations Design Brief

## Overview
This document outlines the design approach for displaying multi-legged option trade details on financial charts within the TastyTrade SDK. The goal is to provide rich trade information without cluttering the visualization or detracting from price action analysis.

## Current Implementation
Currently, the chart supports vertical line annotations with simple text labels. While functional, this approach is limited for complex options trades that contain multiple data points and relationship information.

## Requirements
- Display entry and exit points for multi-legged option trades (credit spreads, etc.)
- Show key trade metrics (credit/debit, P/L, risk metrics)
- Provide detailed leg information when needed
- Maintain clean chart aesthetics
- Support both summary and detailed views of trades

## Design Approach
We propose a layered information architecture that progressively reveals trade details based on user interaction:

### Level 1: Minimal Annotation (Always Visible)
- Vertical line at trade time
- Compact label showing trade type and core metric (e.g., "BPS $4.20")
- Visual encoding for trade type and outcome (colors, line styles)

### Level 2: Hover Details (Interactive)
- Enhanced tooltip appearing on hover
- Shows summary metrics:
  - Trade structure (Bull Put Spread, Iron Condor, etc.)
  - Credit/debit amount
  - P/L (absolute and percentage)
  - Key strike prices
  - Expiration

### Level 3: Expanded View (On Click)
- Small collapsible panel with complete trade details:
  - All leg information
  - Entry and exit prices for each leg
  - Greeks at time of entry
  - Risk metrics (max loss, break-even points)
  - Notes field for trade rationale

## Visual Design Elements

### Vertical Lines
- **Entry Trades**: Solid lines with distinct colors based on strategy type
- **Exit Trades**: Dashed lines matching the color of corresponding entry
- **Line opacity**: Higher for more significant trades (based on size or P/L impact)

### Labels
- Concise format following convention: `[STRATEGY_CODE] [CORE_METRIC]`
- Examples: "BPS $4.20", "IC -$2.15"
- Color-coded for profit/loss status

### Tooltips
- Clean, organized layout with logical grouping
- Consistent data presentation across trade types
- Clear visual hierarchy emphasizing key metrics

### Expanded Panels
- Positioned to avoid obscuring chart data
- Dismissible via click-away or close button
- Potential for linking to trade management interface

## Implementation Considerations

### Technical Approach
1. Extend current `VerticalLine` class with trade-specific metadata
2. Implement custom tooltip handler using Plotly's hover events
3. Create expandable detail component for Level 3 information
4. Develop trade type classification system for visual encoding

### Data Structure
```python
class TradeAnnotation(VerticalLine):
    """Extension of VerticalLine with trade-specific data."""

    def __init__(
        self,
        time: datetime,
        trade_type: str,  # BPS, BCS, IC, etc.
        trade_value: float,  # Credit or debit amount
        legs: List[TradeLeg],
        is_entry: bool = True,
        linked_trade_id: Optional[str] = None,  # For connecting entry/exit
        p_l: Optional[float] = None,  # For exit trades
        notes: Optional[str] = None,
        **kwargs  # Pass through to VerticalLine
    ):
        ...
```

### Performance Considerations
- Lazy-load detailed trade information
- Optimize tooltip rendering for responsive interaction
- Consider caching trade metadata for frequently viewed charts

## UI/UX Principles

1. **Progressive Disclosure**
   - Start with minimal information
   - Reveal details through intentional user interaction
   - Maintain context when showing more information

2. **Consistency**
   - Use consistent visual language across trade types
   - Standardize terminology and layout
   - Apply familiar patterns for options traders

3. **Context Preservation**
   - Avoid obscuring critical chart areas with annotations
   - Provide spatial awareness when displaying detailed information
   - Allow quick dismissal of detailed views

4. **Visual Hierarchy**
   - Emphasize most important trade characteristics
   - De-emphasize supplementary information
   - Use size, color, and position to indicate importance

5. **Minimize Cognitive Load**
   - Group related information logically
   - Use abbreviations familiar to traders
   - Apply color consistently and meaningfully

## Next Steps

1. Create detailed mockups for each information level
2. Implement enhanced `TradeAnnotation` class extending current vertical line functionality
3. Develop trade-specific tooltip component
4. Implement expandable detail panel
5. Integrate with trade data sources
6. User testing and refinement

## Timeframe and Resources
- Design: 2 weeks
- Implementation: 3-4 weeks
- Testing and refinement: 2 weeks
- Resources required:
  - Front-end developer with Plotly/Dash experience
  - UX designer for tooltip and panel design
  - Documentation writer for user guide updates
