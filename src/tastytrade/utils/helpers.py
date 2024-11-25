from types import SimpleNamespace
from typing import Any


def dict_to_class(data: dict[str, Any]) -> SimpleNamespace:
    clean_data = {k.replace("-", "_"): v for k, v in data.items()}
    return SimpleNamespace(**clean_data)
