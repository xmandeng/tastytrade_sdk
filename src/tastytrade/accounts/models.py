import logging
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tastytrade.messaging.models.events import FloatFieldMixin

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
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class Position(TastyTradeApiModel, FloatFieldMixin):
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
