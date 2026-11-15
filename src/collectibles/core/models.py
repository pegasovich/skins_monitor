"""Core domain entities and data models."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DataStatus(StrEnum):
    """Quality status of a price ingestion data point."""

    FRESH = "Fresh"
    STALE = "Stale"
    DEGRADED = "Degraded"
    QUARANTINED = "Quarantined"


class AnomalyType(StrEnum):
    """Categorization of detected pricing anomalies."""

    NET_SPREAD_ARBITRAGE = "net_spread_arbitrage"
    FLASH_CRASH = "flash_crash"
    SPIKE_DEVIATION = "spike_deviation"
    VOLUME_OUTLIER = "volume_outlier"


class LiquidityTier(StrEnum):
    """Liquidity category based on sales frequency and active volume."""

    ULTRA_HIGH = "ultra_high"  # multiple sales per hour
    HIGH = "high"  # 10+ sales per day
    MEDIUM = "medium"  # 1-5 sales per day
    LOW = "low"  # less than 1 sale per day (illiquid/high risk)
    ILLIQUID = "illiquid"  # zero or negligible recent sales


class PricePoint(BaseModel):
    """Canonical, normalized price observation for a specific collectible item."""

    model_config = ConfigDict(frozen=True)

    source_id: str = Field(
        ..., description="Unique platform identifier (e.g., 'csfloat', 'skinport')"
    )
    external_item_id: str = Field(..., description="Original platform listing/asset ID")
    item_identity_hash: str = Field(..., description="Canonical SHA256 identity hash of the item")
    market_hash_name: str | None = Field(default=None, description="Original item market name")
    float_value: Decimal | None = Field(default=None, description="Exact float value if available")

    raw_price: Decimal = Field(..., description="Original price on provider before conversion")
    raw_currency: str = Field(..., description="Currency symbol/code from the provider")
    normalized_price: Decimal = Field(..., description="Standardized price in base currency (USD)")
    reference_price: Decimal | None = Field(
        default=None,
        description="Predicted/reference market value in USD (e.g. CSFloat predicted_price)",
    )
    base_currency: str = Field(default="USD", description="Target base currency")

    fx_rate: Decimal = Field(
        default=Decimal("1.0"), description="Exchange rate applied to raw_price"
    )
    fx_source: str = Field(default="direct", description="Origin of FX quote")

    event_time: datetime = Field(..., description="Timestamp of trade/listing on the source (UTC)")
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when our adapter received the data (UTC)",
    )

    status: DataStatus = Field(default=DataStatus.FRESH, description="Data quality classification")
    confidence: Decimal = Field(
        default=Decimal("1.0"),
        ge=Decimal("0.0"),
        le=Decimal("1.0"),
        description="Reliability confidence score",
    )

    contract_version: str = Field(default="1.0.0", description="Schema specification version")
    correlation_id: str = Field(..., description="Trace correlation identifier")
    trace_id: str | None = Field(default=None, description="OpenTelemetry trace id if active")
    raw_payload: dict[str, Any] = Field(
        default_factory=dict, description="Raw unparsed payload for audit"
    )


class PlatformFeeConfig(BaseModel):
    """Platform transaction fees for net spread calculations."""

    model_config = ConfigDict(frozen=True)

    platform_id: str
    seller_fee_percent: Decimal = Field(
        ..., description="Percentage deducted from seller, e.g. 0.025 for 2.5%"
    )
    buyer_fee_percent: Decimal = Field(
        default=Decimal("0.0"), description="Percentage added to buyer"
    )
    flat_fee: Decimal = Field(
        default=Decimal("0.0"), description="Flat transaction fee in base currency"
    )
    has_trade_lock: bool = Field(
        default=True, description="Whether items on this platform undergo 7-day hold"
    )


class AnomalySignal(BaseModel):
    """Actionable alert generated when profitable spread or pricing discrepancy is confirmed."""

    model_config = ConfigDict(frozen=True)

    signal_id: str
    anomaly_type: AnomalyType
    item_identity_hash: str
    market_hash_name: str
    float_value: Decimal | None = Field(default=None, description="Item float value if known")

    source_buy: str
    buy_price_net: Decimal
    buy_raw_price: Decimal | None = Field(default=None, description="Original un-normalized price")
    buy_raw_currency: str | None = Field(default=None, description="Original currency symbol")
    buy_external_id: str | None = Field(
        default=None, description="Platform listing ID for buy side"
    )
    source_sell: str
    sell_price_net: Decimal
    sell_raw_price: Decimal | None = Field(default=None, description="Original un-normalized price")
    sell_raw_currency: str | None = Field(default=None, description="Original currency symbol")
    sell_external_id: str | None = Field(
        default=None, description="Platform listing ID for sell side"
    )

    gross_spread_percent: Decimal
    net_spread_percent: Decimal
    net_profit_nominal: Decimal

    liquidity_tier: LiquidityTier
    confidence_score: Decimal
    trade_lock_risk: bool

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    fingerprint: str = Field(..., description="De-duplication hash")
