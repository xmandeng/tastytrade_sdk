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


def last_weekday() -> datetime:
    if datetime.now().weekday() >= 5:
        d = datetime.now() + timedelta(days=(4 - datetime.now().weekday()))
    else:
        d = datetime.now()

    return d.replace(hour=9, minute=30, second=0, microsecond=0)
