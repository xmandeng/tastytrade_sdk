from typing import Any, List, TypedDict, Union

from typing_extensions import TypeAlias

# Basic Dash types
Component: TypeAlias = Any
DashComponent: TypeAlias = Any
Figure: TypeAlias = Any
ClientsideFunction: TypeAlias = Any


# Specific component types
class GraphConfig(TypedDict, total=False):
    displayModeBar: bool
    scrollZoom: bool
    displaylogo: bool


class CardProps(TypedDict, total=False):
    id: str
    className: str
    children: List[Any]


class InputProps(TypedDict, total=False):
    id: str
    placeholder: str
    type: str
    className: str
    value: str


class ButtonProps(TypedDict, total=False):
    id: str
    children: Union[str, List[Any]]
    className: str
    color: str
    n_clicks: int


class IntervalProps(TypedDict, total=False):
    id: str
    interval: int
    n_intervals: int
    disabled: bool


class GraphProps(TypedDict, total=False):
    id: str
    figure: Figure
    config: GraphConfig
    className: str
