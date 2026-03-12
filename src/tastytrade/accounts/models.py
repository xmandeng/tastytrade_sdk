import json
import logging
from datetime import date, datetime
from enum import Enum
from types import SimpleNamespace
from typing import Any, ClassVar, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tastytrade.messaging.models.events import FloatFieldMixin

# Model config for order models: extra="allow" to preserve all fields
# the brokerage sends, even ones we haven't explicitly modeled yet.
ORDER_MODEL_CONFIG = ConfigDict(
    frozen=True,
    validate_assignment=True,
    extra="allow",
    str_strip_whitespace=True,
    populate_by_name=True,
)

logger = logging.getLogger(__name__)


class InstrumentType(str, Enum):
    EQUITY = "Equity"
    EQUITY_OPTION = "Equity Option"
    FUTURE = "Future"
    FUTURE_OPTION = "Future Option"
    CRYPTOCURRENCY = "Cryptocurrency"
    BOND = "Bond"
    CURRENCY_PAIR = "Currency Pair"
    EQUITY_OFFERING = "Equity Offering"
    FIXED_INCOME_SECURITY = "Fixed Income Security"
    INDEX = "Index"
    LIQUIDITY_POOL = "Liquidity Pool"
    UNKNOWN = "Unknown"
    WARRANT = "Warrant"


class QuantityDirection(str, Enum):
    LONG = "Long"
    SHORT = "Short"
    ZERO = "Zero"


class TastyTradeApiModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        validate_assignment=True,
        extra="allow",
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class InfluxMixin:
    """Makes account models compatible with TelegrafHTTPEventProcessor."""

    INFLUX_JSON_FIELDS: ClassVar[set[str]] = set()
    INFLUX_EXCLUDE: ClassVar[set[str]] = set()

    def for_influx(self) -> SimpleNamespace:
        """Return a flat representation for InfluxDB.

        Declared JSON fields and any unexpected non-scalar fields
        (from extra='allow') are serialized to JSON strings.
        Returns a SimpleNamespace that process_event() can iterate
        via __dict__ with no surprises.
        """
        fields: dict[str, Any] = {}
        # Include declared fields from __dict__ and extra fields from model_extra
        all_fields = dict(self.__dict__)
        extra = getattr(self, "model_extra", None)
        if extra:
            all_fields.update(extra)

        for attr, value in all_fields.items():
            if attr in self.INFLUX_EXCLUDE:
                continue
            if attr in self.INFLUX_JSON_FIELDS or not isinstance(
                value, (str, int, float, bool, type(None))
            ):
                if isinstance(value, (datetime, date)):
                    fields[attr] = value.isoformat()
                elif isinstance(value, BaseModel):
                    fields[attr] = value.model_dump_json(by_alias=True)
                elif isinstance(value, Enum):
                    fields[attr] = value.value
                elif isinstance(value, list):
                    items = [
                        item.model_dump(by_alias=True)
                        if isinstance(item, BaseModel)
                        else item
                        for item in value
                    ]
                    fields[attr] = json.dumps(items, default=str)
                elif isinstance(value, dict):
                    fields[attr] = json.dumps(value, default=str)
                else:
                    fields[attr] = value
            else:
                fields[attr] = value

        cls = type(self.__class__.__name__, (SimpleNamespace,), {})
        return cls(**fields, eventSymbol=self.eventSymbol)  # type: ignore[attr-defined, return-value]


class Position(TastyTradeApiModel, FloatFieldMixin, InfluxMixin):
    INFLUX_JSON_FIELDS: ClassVar[set[str]] = set()
    INFLUX_EXCLUDE: ClassVar[set[str]] = set()

    # Identity
    account_number: str = Field(alias="account-number", description="Account number")
    symbol: str = Field(alias="symbol", description="Position symbol")
    instrument_type: InstrumentType = Field(
        alias="instrument-type", description="Type of instrument"
    )
    underlying_symbol: Optional[str] = Field(
        default=None, alias="underlying-symbol", description="Underlying symbol"
    )

    # Quantity
    quantity: float = Field(alias="quantity", description="Position quantity")
    quantity_direction: QuantityDirection = Field(
        alias="quantity-direction", description="Long, Short, or Zero"
    )
    multiplier: Optional[float] = Field(
        default=None, alias="multiplier", description="Contract multiplier"
    )

    # Pricing
    close_price: Optional[float] = Field(
        default=None, alias="close-price", description="Last close price"
    )
    average_open_price: Optional[float] = Field(
        default=None, alias="average-open-price", description="Average open price"
    )
    mark: Optional[float] = Field(
        default=None, alias="mark", description="Current mark price"
    )
    mark_price: Optional[float] = Field(
        default=None, alias="mark-price", description="Mark price"
    )
    average_daily_market_close_price: Optional[float] = Field(
        default=None,
        alias="average-daily-market-close-price",
        description="Average daily market close price",
    )
    average_yearly_market_close_price: Optional[float] = Field(
        default=None,
        alias="average-yearly-market-close-price",
        description="Average yearly market close price",
    )

    # Status
    is_frozen: Optional[bool] = Field(
        default=None, alias="is-frozen", description="Whether position is frozen"
    )
    is_suppressed: Optional[bool] = Field(
        default=None,
        alias="is-suppressed",
        description="Whether position is suppressed",
    )
    restricted_quantity: Optional[float] = Field(
        default=None, alias="restricted-quantity", description="Restricted quantity"
    )
    cost_effect: Optional[str] = Field(
        default=None, alias="cost-effect", description="Cost effect (Debit/Credit)"
    )

    # Streamer (AC7)
    streamer_symbol: Optional[str] = Field(
        default=None,
        alias="streamer-symbol",
        description="DXLink streamer symbol for subscription mapping",
    )

    # P&L
    realized_day_gain: Optional[float] = Field(
        default=None, alias="realized-day-gain", description="Realized day gain"
    )
    realized_day_gain_effect: Optional[str] = Field(
        default=None,
        alias="realized-day-gain-effect",
        description="Realized day gain effect",
    )
    realized_day_gain_date: Optional[date] = Field(
        default=None,
        alias="realized-day-gain-date",
        description="Realized day gain date",
    )
    realized_today: Optional[float] = Field(
        default=None, alias="realized-today", description="Realized today"
    )
    realized_today_effect: Optional[str] = Field(
        default=None,
        alias="realized-today-effect",
        description="Realized today effect",
    )
    realized_today_date: Optional[date] = Field(
        default=None, alias="realized-today-date", description="Realized today date"
    )

    # Dates
    expires_at: Optional[datetime] = Field(
        default=None, alias="expires-at", description="Expiration date"
    )
    created_at: Optional[datetime] = Field(
        default=None, alias="created-at", description="Creation timestamp"
    )
    updated_at: Optional[datetime] = Field(
        default=None, alias="updated-at", description="Last update timestamp"
    )

    # Delivery
    deliverable_type: Optional[str] = Field(
        default=None, alias="deliverable-type", description="Deliverable type"
    )
    fixing_price: Optional[float] = Field(
        default=None, alias="fixing-price", description="Fixing price"
    )

    convert_float = FloatFieldMixin.validate_float_fields(
        "quantity",
        "multiplier",
        "close_price",
        "average_open_price",
        "mark",
        "mark_price",
        "average_daily_market_close_price",
        "average_yearly_market_close_price",
        "restricted_quantity",
        "realized_day_gain",
        "realized_today",
        "fixing_price",
    )

    @field_validator("instrument_type", mode="before")
    @classmethod
    def coerce_unknown_instrument_type(cls, value: Any) -> str:
        try:
            InstrumentType(value)
        except ValueError:
            logger.warning("Unknown instrument type '%s', mapping to UNKNOWN", value)
            return InstrumentType.UNKNOWN.value
        return value

    @property
    def eventSymbol(self) -> str:
        return self.streamer_symbol or self.symbol


class Account(TastyTradeApiModel):
    account_number: str = Field(alias="account-number", description="Account number")
    account_type_name: Optional[str] = Field(
        default=None, alias="account-type-name", description="Account type name"
    )
    nickname: Optional[str] = Field(
        default=None, alias="nickname", description="Account nickname"
    )
    is_closed: Optional[bool] = Field(
        default=None, alias="is-closed", description="Whether account is closed"
    )
    day_trader_status: Optional[bool] = Field(
        default=None,
        alias="day-trader-status",
        description="Day trader status",
    )
    is_firm_error: Optional[bool] = Field(
        default=None, alias="is-firm-error", description="Whether firm error"
    )
    is_firm_proprietary: Optional[bool] = Field(
        default=None,
        alias="is-firm-proprietary",
        description="Whether firm proprietary",
    )
    is_foreign: Optional[bool] = Field(
        default=None, alias="is-foreign", description="Whether foreign account"
    )
    is_futures_approved: Optional[bool] = Field(
        default=None,
        alias="is-futures-approved",
        description="Whether futures approved",
    )
    is_test_drive: Optional[bool] = Field(
        default=None, alias="is-test-drive", description="Whether test drive account"
    )
    investment_objective: Optional[str] = Field(
        default=None,
        alias="investment-objective",
        description="Investment objective",
    )
    suitable_options_level: Optional[str] = Field(
        default=None,
        alias="suitable-options-level",
        description="Suitable options level",
    )
    margin_or_cash: Optional[str] = Field(
        default=None, alias="margin-or-cash", description="Margin or Cash"
    )
    ext_crm_id: Optional[str] = Field(
        default=None, alias="ext-crm-id", description="External CRM identifier"
    )
    external_id: Optional[str] = Field(
        default=None, alias="external-id", description="External identifier"
    )
    funding_date: Optional[date] = Field(
        default=None, alias="funding-date", description="Account funding date"
    )
    futures_account_purpose: Optional[str] = Field(
        default=None,
        alias="futures-account-purpose",
        description="Futures account purpose",
    )
    regulatory_domain: Optional[str] = Field(
        default=None, alias="regulatory-domain", description="Regulatory domain"
    )
    opened_at: Optional[datetime] = Field(
        default=None, alias="opened-at", description="Account open date"
    )
    created_at: Optional[datetime] = Field(
        default=None, alias="created-at", description="Account creation timestamp"
    )


class AccountBalance(TastyTradeApiModel, FloatFieldMixin):
    # Core
    account_number: str = Field(alias="account-number", description="Account number")
    cash_balance: Optional[float] = Field(
        default=None, alias="cash-balance", description="Cash balance"
    )
    net_liquidating_value: Optional[float] = Field(
        default=None,
        alias="net-liquidating-value",
        description="Net liquidating value",
    )

    # Buying power
    equity_buying_power: Optional[float] = Field(
        default=None,
        alias="equity-buying-power",
        description="Equity buying power",
    )
    derivative_buying_power: Optional[float] = Field(
        default=None,
        alias="derivative-buying-power",
        description="Derivative buying power",
    )
    day_trading_buying_power: Optional[float] = Field(
        default=None,
        alias="day-trading-buying-power",
        description="Day trading buying power",
    )
    effective_cryptocurrency_buying_power: Optional[float] = Field(
        default=None,
        alias="effective-cryptocurrency-buying-power",
        description="Effective cryptocurrency buying power",
    )

    # Position values
    long_equity_value: Optional[float] = Field(
        default=None, alias="long-equity-value", description="Long equity value"
    )
    short_equity_value: Optional[float] = Field(
        default=None, alias="short-equity-value", description="Short equity value"
    )
    long_derivative_value: Optional[float] = Field(
        default=None,
        alias="long-derivative-value",
        description="Long derivative value",
    )
    short_derivative_value: Optional[float] = Field(
        default=None,
        alias="short-derivative-value",
        description="Short derivative value",
    )
    long_futures_value: Optional[float] = Field(
        default=None, alias="long-futures-value", description="Long futures value"
    )
    short_futures_value: Optional[float] = Field(
        default=None, alias="short-futures-value", description="Short futures value"
    )
    long_futures_derivative_value: Optional[float] = Field(
        default=None,
        alias="long-futures-derivative-value",
        description="Long futures derivative value",
    )
    short_futures_derivative_value: Optional[float] = Field(
        default=None,
        alias="short-futures-derivative-value",
        description="Short futures derivative value",
    )
    long_margineable_value: Optional[float] = Field(
        default=None,
        alias="long-margineable-value",
        description="Long margineable value",
    )
    short_margineable_value: Optional[float] = Field(
        default=None,
        alias="short-margineable-value",
        description="Short margineable value",
    )
    long_bond_value: Optional[float] = Field(
        default=None, alias="long-bond-value", description="Long bond value"
    )
    long_cryptocurrency_value: Optional[float] = Field(
        default=None,
        alias="long-cryptocurrency-value",
        description="Long cryptocurrency value",
    )
    short_cryptocurrency_value: Optional[float] = Field(
        default=None,
        alias="short-cryptocurrency-value",
        description="Short cryptocurrency value",
    )
    long_fixed_income_security_value: Optional[float] = Field(
        default=None,
        alias="long-fixed-income-security-value",
        description="Long fixed income security value",
    )
    long_index_derivative_value: Optional[float] = Field(
        default=None,
        alias="long-index-derivative-value",
        description="Long index derivative value",
    )
    short_index_derivative_value: Optional[float] = Field(
        default=None,
        alias="short-index-derivative-value",
        description="Short index derivative value",
    )

    # Margin
    margin_equity: Optional[float] = Field(
        default=None, alias="margin-equity", description="Margin equity"
    )
    maintenance_requirement: Optional[float] = Field(
        default=None,
        alias="maintenance-requirement",
        description="Maintenance requirement",
    )
    maintenance_call_value: Optional[float] = Field(
        default=None,
        alias="maintenance-call-value",
        description="Maintenance call value",
    )
    maintenance_excess: Optional[float] = Field(
        default=None, alias="maintenance-excess", description="Maintenance excess"
    )
    margin_settle_balance: Optional[float] = Field(
        default=None,
        alias="margin-settle-balance",
        description="Margin settle balance",
    )
    futures_margin_requirement: Optional[float] = Field(
        default=None,
        alias="futures-margin-requirement",
        description="Futures margin requirement",
    )
    cryptocurrency_margin_requirement: Optional[float] = Field(
        default=None,
        alias="cryptocurrency-margin-requirement",
        description="Cryptocurrency margin requirement",
    )
    bond_margin_requirement: Optional[float] = Field(
        default=None,
        alias="bond-margin-requirement",
        description="Bond margin requirement",
    )
    equity_offering_margin_requirement: Optional[float] = Field(
        default=None,
        alias="equity-offering-margin-requirement",
        description="Equity offering margin requirement",
    )
    fixed_income_security_margin_requirement: Optional[float] = Field(
        default=None,
        alias="fixed-income-security-margin-requirement",
        description="Fixed income security margin requirement",
    )
    futures_overnight_margin_requirement: Optional[float] = Field(
        default=None,
        alias="futures-overnight-margin-requirement",
        description="Futures overnight margin requirement",
    )
    futures_intraday_margin_requirement: Optional[float] = Field(
        default=None,
        alias="futures-intraday-margin-requirement",
        description="Futures intraday margin requirement",
    )

    # Cash management
    pending_cash: Optional[float] = Field(
        default=None, alias="pending-cash", description="Pending cash"
    )
    pending_cash_effect: Optional[str] = Field(
        default=None, alias="pending-cash-effect", description="Pending cash effect"
    )
    cash_available_to_withdraw: Optional[float] = Field(
        default=None,
        alias="cash-available-to-withdraw",
        description="Cash available to withdraw",
    )
    cash_settle_balance: Optional[float] = Field(
        default=None,
        alias="cash-settle-balance",
        description="Cash settle balance",
    )
    closed_loop_available_balance: Optional[float] = Field(
        default=None,
        alias="closed-loop-available-balance",
        description="Closed loop available balance",
    )
    available_trading_funds: Optional[float] = Field(
        default=None,
        alias="available-trading-funds",
        description="Available trading funds",
    )
    total_settle_balance: Optional[float] = Field(
        default=None,
        alias="total-settle-balance",
        description="Total settle balance",
    )

    # Day trading
    day_trade_excess: Optional[float] = Field(
        default=None, alias="day-trade-excess", description="Day trade excess"
    )
    day_trading_call_value: Optional[float] = Field(
        default=None,
        alias="day-trading-call-value",
        description="Day trading call value",
    )
    day_equity_call_value: Optional[float] = Field(
        default=None,
        alias="day-equity-call-value",
        description="Day equity call value",
    )

    # Reg-T
    reg_t_call_value: Optional[float] = Field(
        default=None, alias="reg-t-call-value", description="Reg-T call value"
    )
    reg_t_margin_requirement: Optional[float] = Field(
        default=None,
        alias="reg-t-margin-requirement",
        description="Reg-T margin requirement",
    )

    # SMA
    sma_equity_option_buying_power: Optional[float] = Field(
        default=None,
        alias="sma-equity-option-buying-power",
        description="SMA equity option buying power",
    )
    special_memorandum_account_value: Optional[float] = Field(
        default=None,
        alias="special-memorandum-account-value",
        description="Special memorandum account value",
    )
    special_memorandum_account_apex_adjustment: Optional[float] = Field(
        default=None,
        alias="special-memorandum-account-apex-adjustment",
        description="Special memorandum account apex adjustment",
    )

    # Intraday
    intraday_equities_cash_amount: Optional[float] = Field(
        default=None,
        alias="intraday-equities-cash-amount",
        description="Intraday equities cash amount",
    )
    intraday_equities_cash_effect: Optional[str] = Field(
        default=None,
        alias="intraday-equities-cash-effect",
        description="Intraday equities cash effect",
    )
    intraday_equities_cash_effective_date: Optional[date] = Field(
        default=None,
        alias="intraday-equities-cash-effective-date",
        description="Intraday equities cash effective date",
    )
    intraday_futures_cash_amount: Optional[float] = Field(
        default=None,
        alias="intraday-futures-cash-amount",
        description="Intraday futures cash amount",
    )
    intraday_futures_cash_effect: Optional[str] = Field(
        default=None,
        alias="intraday-futures-cash-effect",
        description="Intraday futures cash effect",
    )
    intraday_futures_cash_effective_date: Optional[date] = Field(
        default=None,
        alias="intraday-futures-cash-effective-date",
        description="Intraday futures cash effective date",
    )

    # Crypto/settlement
    unsettled_cryptocurrency_fiat_amount: Optional[float] = Field(
        default=None,
        alias="unsettled-cryptocurrency-fiat-amount",
        description="Unsettled cryptocurrency fiat amount",
    )
    unsettled_cryptocurrency_fiat_effect: Optional[str] = Field(
        default=None,
        alias="unsettled-cryptocurrency-fiat-effect",
        description="Unsettled cryptocurrency fiat effect",
    )
    previous_day_cryptocurrency_fiat_amount: Optional[float] = Field(
        default=None,
        alias="previous-day-cryptocurrency-fiat-amount",
        description="Previous day cryptocurrency fiat amount",
    )
    previous_day_cryptocurrency_fiat_effect: Optional[str] = Field(
        default=None,
        alias="previous-day-cryptocurrency-fiat-effect",
        description="Previous day cryptocurrency fiat effect",
    )
    previous_date_cryptocurrency_fiat_effective_date: Optional[date] = Field(
        default=None,
        alias="previous-date-cryptocurrency-fiat-effective-date",
        description="Previous date cryptocurrency fiat effective date",
    )

    # Other
    pending_margin_interest: Optional[float] = Field(
        default=None,
        alias="pending-margin-interest",
        description="Pending margin interest",
    )
    apex_starting_day_margin_equity: Optional[float] = Field(
        default=None,
        alias="apex-starting-day-margin-equity",
        description="Apex starting day margin equity",
    )
    buying_power_adjustment: Optional[float] = Field(
        default=None,
        alias="buying-power-adjustment",
        description="Buying power adjustment",
    )
    buying_power_adjustment_effect: Optional[str] = Field(
        default=None,
        alias="buying-power-adjustment-effect",
        description="Buying power adjustment effect",
    )
    total_pending_liquidity_pool_rebate: Optional[float] = Field(
        default=None,
        alias="total-pending-liquidity-pool-rebate",
        description="Total pending liquidity pool rebate",
    )
    used_derivative_buying_power: Optional[float] = Field(
        default=None,
        alias="used-derivative-buying-power",
        description="Used derivative buying power",
    )
    snapshot_date: Optional[date] = Field(
        default=None, alias="snapshot-date", description="Snapshot date"
    )
    time_of_day: Optional[str] = Field(
        default=None, alias="time-of-day", description="Time of day"
    )
    currency: Optional[str] = Field(
        default=None, alias="currency", description="Currency"
    )
    updated_at: Optional[datetime] = Field(
        default=None, alias="updated-at", description="Last update timestamp"
    )

    convert_float = FloatFieldMixin.validate_float_fields(
        "cash_balance",
        "net_liquidating_value",
        "equity_buying_power",
        "derivative_buying_power",
        "day_trading_buying_power",
        "effective_cryptocurrency_buying_power",
        "long_equity_value",
        "short_equity_value",
        "long_derivative_value",
        "short_derivative_value",
        "long_futures_value",
        "short_futures_value",
        "long_futures_derivative_value",
        "short_futures_derivative_value",
        "long_margineable_value",
        "short_margineable_value",
        "long_bond_value",
        "long_cryptocurrency_value",
        "short_cryptocurrency_value",
        "long_fixed_income_security_value",
        "long_index_derivative_value",
        "short_index_derivative_value",
        "margin_equity",
        "maintenance_requirement",
        "maintenance_call_value",
        "maintenance_excess",
        "margin_settle_balance",
        "futures_margin_requirement",
        "cryptocurrency_margin_requirement",
        "bond_margin_requirement",
        "equity_offering_margin_requirement",
        "fixed_income_security_margin_requirement",
        "futures_overnight_margin_requirement",
        "futures_intraday_margin_requirement",
        "pending_cash",
        "cash_available_to_withdraw",
        "cash_settle_balance",
        "closed_loop_available_balance",
        "available_trading_funds",
        "total_settle_balance",
        "day_trade_excess",
        "day_trading_call_value",
        "day_equity_call_value",
        "reg_t_call_value",
        "reg_t_margin_requirement",
        "sma_equity_option_buying_power",
        "special_memorandum_account_value",
        "special_memorandum_account_apex_adjustment",
        "intraday_equities_cash_amount",
        "intraday_futures_cash_amount",
        "unsettled_cryptocurrency_fiat_amount",
        "previous_day_cryptocurrency_fiat_amount",
        "pending_margin_interest",
        "apex_starting_day_margin_equity",
        "buying_power_adjustment",
        "total_pending_liquidity_pool_rebate",
        "used_derivative_buying_power",
    )


# ---------------------------------------------------------------------------
# TT-60: Order & ComplexOrder models
# ---------------------------------------------------------------------------


class OrderStatus(str, Enum):
    RECEIVED = "Received"
    ROUTED = "Routed"
    IN_FLIGHT = "In Flight"
    LIVE = "Live"
    FILLED = "Filled"
    CANCELLED = "Cancelled"
    EXPIRED = "Expired"
    REJECTED = "Rejected"
    CANCEL_REQUESTED = "Cancel Requested"
    REPLACE_REQUESTED = "Replace Requested"
    REMOVED = "Removed"
    PARTIALLY_REMOVED = "Partially Removed"
    CONTINGENT = "Contingent"
    UNKNOWN = "Unknown"


class OrderAction(str, Enum):
    BUY_TO_OPEN = "Buy to Open"
    BUY_TO_CLOSE = "Buy to Close"
    SELL_TO_OPEN = "Sell to Open"
    SELL_TO_CLOSE = "Sell to Close"
    UNKNOWN = "Unknown"


class ComplexOrderType(str, Enum):
    OCO = "OCO"
    OTOCO = "OTOCO"
    UNKNOWN = "Unknown"


class PriceEffect(str, Enum):
    CREDIT = "Credit"
    DEBIT = "Debit"
    NONE = "None"
    UNKNOWN = "Unknown"


class TimeInForce(str, Enum):
    DAY = "Day"
    GTC = "GTC"
    GTD = "GTD"
    IOC = "IOC"
    UNKNOWN = "Unknown"


class OrderType(str, Enum):
    LIMIT = "Limit"
    MARKET = "Market"
    STOP = "Stop"
    STOP_LIMIT = "Stop Limit"
    UNKNOWN = "Unknown"


class OrderFill(BaseModel, FloatFieldMixin):
    """A single fill execution within an order leg."""

    model_config = ORDER_MODEL_CONFIG

    fill_id: str = Field(alias="fill-id")
    quantity: float = Field(alias="quantity")
    fill_price: float = Field(alias="fill-price")
    filled_at: datetime = Field(alias="filled-at")
    destination_venue: Optional[str] = Field(default=None, alias="destination-venue")
    ext_exec_id: Optional[str] = Field(default=None, alias="ext-exec-id")
    ext_group_fill_id: Optional[str] = Field(default=None, alias="ext-group-fill-id")

    convert_float = FloatFieldMixin.validate_float_fields("quantity", "fill_price")


class OrderLeg(BaseModel, FloatFieldMixin):
    """A single leg within an order."""

    model_config = ORDER_MODEL_CONFIG

    instrument_type: InstrumentType = Field(alias="instrument-type")
    symbol: str = Field(alias="symbol")
    action: OrderAction = Field(alias="action")
    quantity: float = Field(alias="quantity")
    remaining_quantity: Optional[float] = Field(
        default=None, alias="remaining-quantity"
    )
    fills: list[OrderFill] = Field(default_factory=list, alias="fills")

    convert_float = FloatFieldMixin.validate_float_fields(
        "quantity", "remaining_quantity"
    )

    @field_validator("instrument_type", mode="before")
    @classmethod
    def coerce_unknown_instrument_type(cls, value: Any) -> str:
        try:
            InstrumentType(value)
        except ValueError:
            logger.warning("Unknown instrument type '%s', mapping to UNKNOWN", value)
            return InstrumentType.UNKNOWN.value
        return value

    @field_validator("action", mode="before")
    @classmethod
    def coerce_unknown_action(cls, value: Any) -> str:
        try:
            OrderAction(value)
        except ValueError:
            logger.warning("Unknown order action '%s', mapping to UNKNOWN", value)
            return OrderAction.UNKNOWN.value
        return value


class PlacedOrder(BaseModel, FloatFieldMixin, InfluxMixin):
    """A single order from the Account Streamer."""

    model_config = ORDER_MODEL_CONFIG
    INFLUX_JSON_FIELDS: ClassVar[set[str]] = {"legs"}
    INFLUX_EXCLUDE: ClassVar[set[str]] = set()

    # Identity
    id: int = Field(alias="id")
    account_number: str = Field(alias="account-number")

    # Order parameters
    order_type: OrderType = Field(alias="order-type")
    time_in_force: TimeInForce = Field(alias="time-in-force")
    price: Optional[float] = Field(default=None, alias="price")
    price_effect: Optional[PriceEffect] = Field(default=None, alias="price-effect")
    size: Optional[int] = Field(default=None, alias="size")

    # Status
    status: OrderStatus = Field(alias="status")
    cancellable: bool = Field(default=False, alias="cancellable")
    editable: bool = Field(default=False, alias="editable")

    # Underlying
    underlying_symbol: Optional[str] = Field(default=None, alias="underlying-symbol")
    underlying_instrument_type: Optional[InstrumentType] = Field(
        default=None, alias="underlying-instrument-type"
    )

    # Legs
    legs: list[OrderLeg] = Field(default_factory=list, alias="legs")

    # Timestamps
    received_at: Optional[datetime] = Field(default=None, alias="received-at")
    updated_at: Optional[datetime] = Field(default=None, alias="updated-at")
    in_flight_at: Optional[datetime] = Field(default=None, alias="in-flight-at")
    live_at: Optional[datetime] = Field(default=None, alias="live-at")
    terminal_at: Optional[datetime] = Field(default=None, alias="terminal-at")

    # Exchange routing
    destination_venue: Optional[str] = Field(default=None, alias="destination-venue")

    convert_float = FloatFieldMixin.validate_float_fields("price")

    @field_validator("status", mode="before")
    @classmethod
    def coerce_unknown_status(cls, value: Any) -> str:
        try:
            OrderStatus(value)
        except ValueError:
            logger.warning("Unknown order status '%s', mapping to UNKNOWN", value)
            return OrderStatus.UNKNOWN.value
        return value

    @field_validator("order_type", mode="before")
    @classmethod
    def coerce_unknown_order_type(cls, value: Any) -> str:
        try:
            OrderType(value)
        except ValueError:
            logger.warning("Unknown order type '%s', mapping to UNKNOWN", value)
            return OrderType.UNKNOWN.value
        return value

    @field_validator("time_in_force", mode="before")
    @classmethod
    def coerce_unknown_tif(cls, value: Any) -> str:
        try:
            TimeInForce(value)
        except ValueError:
            logger.warning("Unknown time-in-force '%s', mapping to UNKNOWN", value)
            return TimeInForce.UNKNOWN.value
        return value

    @property
    def eventSymbol(self) -> str:
        return self.underlying_symbol or ""


class PlacedComplexOrder(BaseModel, InfluxMixin):
    """A complex (multi-leg) order from the Account Streamer."""

    model_config = ORDER_MODEL_CONFIG
    INFLUX_JSON_FIELDS: ClassVar[set[str]] = {"orders", "trigger_order"}
    INFLUX_EXCLUDE: ClassVar[set[str]] = set()

    # Identity
    id: int = Field(alias="id")
    account_number: str = Field(alias="account-number")

    # Type
    type: ComplexOrderType = Field(alias="type")

    # Sub-orders
    orders: list[PlacedOrder] = Field(default_factory=list, alias="orders")
    trigger_order: Optional[PlacedOrder] = Field(default=None, alias="trigger-order")

    # Status
    terminal_at: Optional[datetime] = Field(default=None, alias="terminal-at")

    @field_validator("type", mode="before")
    @classmethod
    def coerce_unknown_type(cls, value: Any) -> str:
        try:
            ComplexOrderType(value)
        except ValueError:
            logger.warning("Unknown complex order type '%s', mapping to UNKNOWN", value)
            return ComplexOrderType.UNKNOWN.value
        return value

    @property
    def eventSymbol(self) -> str:
        if self.orders:
            return self.orders[0].underlying_symbol or ""
        return ""


# ---------------------------------------------------------------------------
# TradeChain — models the OrderChain event from the account streamer.
# Captures the full trade lifecycle: opens, closes, rolls, and realized P&L.
# Uses extra="allow" throughout — the brokerage schema may evolve and we
# must not reject unknown fields.
# ---------------------------------------------------------------------------


class TradeChainEntry(TastyTradeApiModel):
    """A position entry within a trade chain (open-entries or node entries)."""

    symbol: str = Field(description="Position symbol")
    instrument_type: str = Field(alias="instrument-type")
    quantity: str = Field(description="Quantity as string")
    quantity_type: str = Field(alias="quantity-type", description="Long or Short")
    quantity_numeric: str = Field(
        alias="quantity-numeric", description="Signed quantity"
    )


class TradeChainLeg(TastyTradeApiModel):
    """A single leg within an order node of a trade chain."""

    symbol: str = Field(description="Option/future symbol")
    instrument_type: str = Field(alias="instrument-type")
    action: str = Field(description="e.g. Buy to Open, Sell to Close")
    fill_quantity: str = Field(alias="fill-quantity")
    order_quantity: str = Field(alias="order-quantity")


class TradeChainMarketData(TastyTradeApiModel):
    """Market snapshot for a single symbol at time of order execution."""

    symbol: str
    instrument_type: str = Field(alias="instrument-type")
    bid: Optional[str] = None
    ask: Optional[str] = None
    last: Optional[str] = None
    delta: Optional[str] = None
    gamma: Optional[str] = None
    theta: Optional[str] = None
    rho: Optional[str] = None
    vega: Optional[str] = None


class TradeChainMarketSnapshot(TastyTradeApiModel):
    """Market state at time of order execution."""

    market_datas: list[TradeChainMarketData] = Field(
        alias="market-datas", default_factory=list
    )
    total_delta: Optional[str] = Field(default=None, alias="total-delta")
    total_theta: Optional[str] = Field(default=None, alias="total-theta")


class TradeChainNode(TastyTradeApiModel):
    """A node in the trade chain — either open-positions or an order."""

    node_type: str = Field(alias="node-type", description="'open-positions' or 'order'")
    id: str = Field(description="Node ID")
    description: str = Field(description="e.g. 'Iron Condor', 'Closing', 'Open Pos'")
    occurred_at: Optional[str] = Field(default=None, alias="occurred-at")
    total_fees: Optional[str] = Field(default=None, alias="total-fees")
    total_fees_effect: Optional[str] = Field(default=None, alias="total-fees-effect")
    total_fill_cost: Optional[str] = Field(default=None, alias="total-fill-cost")
    total_fill_cost_effect: Optional[str] = Field(
        default=None, alias="total-fill-cost-effect"
    )
    gcd_quantity: Optional[str] = Field(default=None, alias="gcd-quantity")
    fill_cost_per_quantity: Optional[str] = Field(
        default=None, alias="fill-cost-per-quantity"
    )
    fill_cost_per_quantity_effect: Optional[str] = Field(
        default=None, alias="fill-cost-per-quantity-effect"
    )
    order_fill_count: Optional[int] = Field(default=None, alias="order-fill-count")
    roll: Optional[bool] = None
    legs: list[TradeChainLeg] = Field(default_factory=list)
    entries: list[TradeChainEntry] = Field(default_factory=list)
    market_state_snapshot: Optional[TradeChainMarketSnapshot] = Field(
        default=None, alias="market-state-snapshot"
    )


class TradeChainComputedData(TastyTradeApiModel):
    """Pre-computed trade P&L and lifecycle data from TastyTrade."""

    open: bool = Field(description="True if the chain still has open legs")
    total_fees: Optional[str] = Field(default=None, alias="total-fees")
    total_fees_effect: Optional[str] = Field(default=None, alias="total-fees-effect")
    total_commissions: Optional[str] = Field(default=None, alias="total-commissions")
    total_commissions_effect: Optional[str] = Field(
        default=None, alias="total-commissions-effect"
    )
    realized_gain: Optional[str] = Field(default=None, alias="realized-gain")
    realized_gain_effect: Optional[str] = Field(
        default=None, alias="realized-gain-effect"
    )
    realized_gain_with_fees: Optional[str] = Field(
        default=None, alias="realized-gain-with-fees"
    )
    realized_gain_with_fees_effect: Optional[str] = Field(
        default=None, alias="realized-gain-with-fees-effect"
    )
    winner_realized_and_closed: Optional[bool] = Field(
        default=None, alias="winner-realized-and-closed"
    )
    winner_realized: Optional[bool] = Field(default=None, alias="winner-realized")
    winner_realized_with_fees: Optional[bool] = Field(
        default=None, alias="winner-realized-with-fees"
    )
    roll_count: int = Field(default=0, alias="roll-count")
    opened_at: Optional[str] = Field(default=None, alias="opened-at")
    last_occurred_at: Optional[str] = Field(default=None, alias="last-occurred-at")
    total_opening_cost: Optional[str] = Field(default=None, alias="total-opening-cost")
    total_opening_cost_effect: Optional[str] = Field(
        default=None, alias="total-opening-cost-effect"
    )
    total_closing_cost: Optional[str] = Field(default=None, alias="total-closing-cost")
    total_closing_cost_effect: Optional[str] = Field(
        default=None, alias="total-closing-cost-effect"
    )
    total_cost: Optional[str] = Field(default=None, alias="total-cost")
    total_cost_effect: Optional[str] = Field(default=None, alias="total-cost-effect")
    open_entries: list[TradeChainEntry] = Field(
        default_factory=list, alias="open-entries"
    )


class TradeChain(TastyTradeApiModel, InfluxMixin):
    """Full trade lifecycle from the TastyTrade OrderChain event.

    Captures the complete history of a trade including opens, closes, rolls,
    realized P&L, fees, and market snapshots at time of execution.
    """

    INFLUX_JSON_FIELDS: ClassVar[set[str]] = {"computed_data", "lite_nodes"}
    INFLUX_EXCLUDE: ClassVar[set[str]] = set()

    id: str = Field(description="Chain ID from TastyTrade")
    description: str = Field(description="Strategy name, e.g. 'Iron Condor'")
    underlying_symbol: str = Field(alias="underlying-symbol")
    computed_data: TradeChainComputedData = Field(alias="computed-data")
    lite_nodes_sizes: Optional[int] = Field(default=None, alias="lite-nodes-sizes")
    lite_nodes: list[TradeChainNode] = Field(default_factory=list, alias="lite-nodes")

    @property
    def eventSymbol(self) -> str:
        return self.underlying_symbol
