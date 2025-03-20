from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TradeAction(str, Enum):
    EXECUTE = "execute"
    DO_NOT_TRADE = "do_not_trade"
    HOLD = "hold"


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    VOLATILE = "volatile"


class TradeDecision(BaseModel):
    action: TradeAction = Field(..., description="Decision for trade execution")
    direction: Direction = Field(..., description="Direction of the trade")
    reason: str = Field(..., description="Brief explanation for the trade decision")
    hold_above: Optional[float] = Field(
        None,
        description="If action is 'hold', the price level above which execution may be reconsidered",
    )
    hold_below: Optional[float] = Field(
        None,
        description="If action is 'hold', the price level below which execution may be reconsidered",
    )
    confidence: float = Field(
        ..., ge=0, le=1, description="Confidence level of the decision (0 to 1)"
    )


# Example Usage
trade_decision = TradeDecision(
    action=TradeAction.HOLD,
    reason="Price needs to confirm support above 5610 before entering",
    hold_above=5610,
    hold_below=5605,
    confidence=0.75,
)
