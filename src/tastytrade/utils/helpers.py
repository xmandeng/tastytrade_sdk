from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any


def dict_to_class(data: dict[str, Any]) -> SimpleNamespace:
    clean_data = {k.replace("-", "_"): v for k, v in data.items()}
    return SimpleNamespace(**clean_data)


def dash_to_underscore(value: str) -> str:
    return value.replace("-", "_")


def get_trade_day() -> str:
    trade_day = datetime.now()
    while trade_day.weekday() >= 5:
        trade_day += timedelta(days=1)

    return trade_day.strftime("%y%m%d")
