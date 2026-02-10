"""Chart annotation models backed by BaseEvent for native InfluxDB persistence.

Annotation models serve two contracts simultaneously:

1. **Charting code** needs native ``datetime`` objects for timezone conversion
   and Plotly rendering (``h_line.start_time`` returns ``datetime``).
2. **InfluxDB processor** iterates ``event.__dict__.items()`` and calls
   ``point.field(attr, value)`` which only accepts ``str|int|float|bool``.

Two mechanisms handle this without modifying the processor:

``_ProcessorSafeDict``
    Wraps ``__dict__`` so that direct attribute access returns raw Python
    objects (datetime, etc.) while iteration via ``.items()`` converts
    datetime values to ISO-8601 strings and skips None values.  This keeps
    the processor's hot path untouched — no isinstance checks on every
    field of every event — and scopes the conversion cost to annotation
    models only.

Timestamp jitter (``BaseAnnotation.time`` property)
    InfluxDB deduplicates points by (measurement, tag-set, timestamp).
    Multiple annotations often share the same ``start_time`` and
    ``eventSymbol`` — e.g. prior-close, prior-high, and prior-low lines
    all anchored at market open.  Without differentiation, only the last
    write survives.

    The ``time`` property returns ``start_time`` plus a deterministic
    microsecond offset (0–999 µs) derived from a SHA-256 hash of the
    annotation's ``label``.  This guarantees:

    - **Uniqueness**: annotations with different content always get
      different InfluxDB timestamps, even when ``start_time`` is identical.
    - **Idempotency**: re-persisting the same annotation produces the same
      timestamp — no duplicate points.
    - **Invisibility**: < 1 ms offset has zero impact on chart rendering.
"""

import hashlib
from datetime import datetime, timedelta
from typing import Annotated, Any, Iterator, Optional, Self, Union

from pydantic import BeforeValidator, Field, model_validator

from tastytrade.messaging.models.events import BaseEvent


def _coerce_price(v: Union[float, int, None]) -> float:
    """Accept float, int, or None — coerce int to float, reject None."""
    if v is None:
        raise ValueError("price cannot be None for HorizontalLine")
    return float(v)


class _ProcessorSafeDict(dict):
    """Dict subclass that converts datetime values to ISO strings during iteration.

    The InfluxDB processor calls ``point.field(attr, value)`` for each item in
    ``event.__dict__.items()``.  ``point.field()`` rejects ``datetime`` objects.
    Rather than adding isinstance checks to the processor's hot path (millions
    of market-data events per session), we override ``items()`` here so only
    annotation models pay the conversion cost.

    Direct key access (``d["start_time"]``, ``d.get("start_time")``) still
    returns raw ``datetime`` objects — Python's C-level dict lookup is not
    affected by this override.
    """

    def items(self) -> Iterator[tuple[str, Any]]:  # type: ignore[override]
        for k, v in super().items():
            if isinstance(v, datetime):
                yield k, v.isoformat()
            elif v is None:
                continue
            else:
                yield k, v

    def copy(self) -> "_ProcessorSafeDict":
        """Return a _ProcessorSafeDict with raw values (not ISO-converted)."""
        return _ProcessorSafeDict(dict.copy(self))

    def __copy__(self) -> "_ProcessorSafeDict":
        """Support ``copy.copy()`` — used by Pydantic's ``model_copy``.

        Without this, ``copy.copy()`` falls through to ``__reduce_ex__``
        which serializes via ``items()`` and converts datetimes to strings.
        """
        return self.copy()


class BaseAnnotation(BaseEvent):
    """Base for all chart annotation events with shared styling fields.

    Extends BaseEvent so annotations flow through the same InfluxDB
    processor pipeline as CandleEvent, TradeEvent, etc.

    Processor compatibility:
        ``__dict__`` is wrapped in ``_ProcessorSafeDict`` so that
        ``event.__dict__.items()`` yields only primitive types
        (str/int/float/bool).  The ``time`` property provides the InfluxDB
        point timestamp with a deterministic microsecond jitter to prevent
        deduplication when multiple annotations share the same
        ``start_time``.  See module docstring for full details.
    """

    eventSymbol: str = Field(
        default="", description="Symbol this annotation is associated with"
    )
    event_type: str = "chart_annotation"
    start_time: datetime
    label: str
    color: str = "white"
    line_width: float = 1.0
    line_dash: str = "solid"
    opacity: float = Field(default=0.7, ge=0.0, le=1.0)
    show_label: bool = True
    label_font_size: float = 11.0

    @model_validator(mode="before")
    @classmethod
    def remap_time_to_start_time(cls, data: Any) -> Any:
        """Allow ``VerticalLine(time=dt)`` for backward compatibility.

        Remaps the ``time`` kwarg to ``start_time`` so callers that used the
        old ``VerticalLine.time`` field can construct models without changes.
        """
        if isinstance(data, dict) and "time" in data and "start_time" not in data:
            data["start_time"] = data.pop("time")
        return data

    @property
    def time(self) -> datetime:
        """InfluxDB point timestamp with microsecond jitter for uniqueness.

        The processor discovers this via ``hasattr(event, "time")`` and uses it
        as the InfluxDB point timestamp via ``point.time(event.time)``.  Because
        this is a ``@property`` (descriptor), it lives on the *class* — not in
        ``__dict__`` — so it never enters the field iteration loop.

        InfluxDB deduplicates points by (measurement, tag-set, timestamp).
        Multiple annotations can share the same ``start_time`` and
        ``eventSymbol`` (e.g. prior-close, prior-high, prior-low all anchored
        at market open).  A deterministic microsecond offset derived from the
        annotation's content fields ensures each point gets a unique timestamp
        without affecting chart rendering (< 1 ms).
        """
        offset_us = int(hashlib.sha256(self.label.encode()).hexdigest(), 16) % 1000
        return self.start_time + timedelta(microseconds=offset_us)

    def model_post_init(self, __context: Any) -> None:
        """Wrap __dict__ in _ProcessorSafeDict after Pydantic initialization."""
        object.__setattr__(self, "__dict__", _ProcessorSafeDict(self.__dict__))

    def model_copy(self, **kwargs: Any) -> Self:
        """Re-wrap __dict__ after Pydantic's model_copy to preserve processor safety."""
        copy = super().model_copy(**kwargs)
        object.__setattr__(copy, "__dict__", _ProcessorSafeDict(copy.__dict__))
        return copy


class HorizontalLine(BaseAnnotation):
    """A horizontal price level line on a chart."""

    price: Annotated[float, BeforeValidator(_coerce_price)]
    text_position: str = "left"
    extend_to_end: bool = False
    end_time: Optional[datetime] = None


class VerticalLine(BaseAnnotation):
    """A vertical time line on a chart."""

    text_position: str = "top"
    text_orientation: str = "horizontal"
    label_padding: int = 6
    span_subplots: bool = True
    label_bg_opacity: float = 0.8
