"""Vulture whitelist — false positives that are used dynamically.

Each entry tells vulture the symbol is intentionally present.
Add a comment explaining WHY it's a false positive.
"""

# --- Pydantic model_config class variables (used by Pydantic framework) ---
from tastytrade.accounts.messages import *  # noqa: F403 — model_config
from tastytrade.accounts.models import *  # noqa: F403 — model_config, field validators
from tastytrade.messaging.models.events import *  # noqa: F403 — model_config
from tastytrade.messaging.models.messages import *  # noqa: F403 — model_config, validators
from tastytrade.market.models import *  # noqa: F403 — model_config, Pydantic fields
from tastytrade.analytics.visualizations.models import *  # noqa: F403 — model_config, validators

# --- Pydantic @field_validator / @model_validator methods ---
# These are called by Pydantic's metaclass machinery, not directly.
# vulture sees them as unused because there's no explicit call site.
# Pattern: @field_validator("field_name") / @model_validator(mode="before")

# --- Click CLI command functions ---
# Decorated with @cli.command() — Click registers them via the decorator.
# vulture can't see the decorator-based registration.

# --- __aexit__ protocol parameters (exc_type, exc, tb) ---
# Required by the async context manager protocol even if unused.
# These appear in connections/sockets.py and accounts/streamer.py.

# --- Enum members used via deserialization ---
# Pydantic coerces strings to enum values at runtime.
from tastytrade.config.enumerations import *  # noqa: F403 — enum members
