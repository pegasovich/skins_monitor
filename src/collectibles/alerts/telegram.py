"""Production Telegram Bot alert dispatcher with inline buttons and markdown formatting."""

import re
from typing import Any
from urllib.parse import quote

import httpx
import structlog
from pydantic import SecretStr

from collectibles.alerts.engine import AlertChannel
from collectibles.core.models import AnomalySignal

logger = structlog.get_logger(__name__)


def _slugify(name: str) -> str:
    """Convert Steam market hash name to Skinport URL slug.

    E.g. 'AK-47 | Redline (Field-Tested)' → 'ak-47-redline-field-tested'
    """
    # Lowercase
    slug = name.lower()
    # Remove special chars except hyphens, letters, digits, spaces
    slug = re.sub(r"[|()★™]", " ", slug)
    # Collapse whitespace → hyphens
    slug = re.sub(r"[\s]+", "-", slug.strip())
    # Remove any chars that aren't alphanumeric or hyphen
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    # Collapse multiple hyphens
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug


class TelegramAlertChannel(AlertChannel):
    """Sends enriched notifications with action buttons via Telegram Bot API."""

    def __init__(
        self,
        bot_token: SecretStr | None,
        chat_id: str | None,
        dry_run: bool = True,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.dry_run = dry_run
        self.timeout = timeout_seconds

    def _build_marketplace_url(self, platform_id: str, market_hash_name: str) -> str:
        """Construct direct listing/search URL for platform."""
        safe_name = quote(market_hash_name)
        if platform_id.lower() == "csfloat":
            # CSFloat search by name — shows all buy-now listings sorted by price
            return f"https://csfloat.com/search?market_hash_name={safe_name}&sort_by=price&type=buy_now"
        if platform_id.lower() == "skinport":
            # Skinport item page: /item/csgo/<slug>
            slug = _slugify(market_hash_name)
            return f"https://skinport.com/item/csgo/{slug}"
        if platform_id.lower() == "steam":
            # Steam Community Market listing page
            return f"https://steamcommunity.com/market/listings/730/{safe_name}"
        return f"https://google.com/search?q=CS2+{safe_name}"

    def format_signal_html(self, signal: AnomalySignal) -> str:
        """Render readable HTML message for Telegram."""
        mode_tag = (
            "🧪 <b>[DRY_RUN SIMULATION]</b>\n"
            if self.dry_run
            else "🚨 <b>[LIVE ARBITRAGE SIGNAL]</b>\n"
        )
        trade_lock = (
            "⏳ <i>7-Day Trade Lock Required</i>"
            if signal.trade_lock_risk
            else "⚡ <i>Instant Delivery</i>"
        )

        sell_str = f"{signal.source_sell.upper()} (Net: ${signal.sell_price_net})"
        return (
            f"{mode_tag}"
            f"<b>Item:</b> <code>{signal.market_hash_name}</code>\n\n"
            f"🟢 <b>Buy:</b> {signal.source_buy.upper()} @ <b>${signal.buy_price_net}</b>\n"
            f"🔴 <b>Sell:</b> <b>{sell_str}</b>\n\n"
            f"📈 <b>Net Spread:</b> <code>+{signal.net_spread_percent}%</code>\n"
            f"💰 <b>Estimated Net Profit:</b> <b>+${signal.net_profit_nominal}</b>\n"
            f"📊 <b>Liquidity:</b> {signal.liquidity_tier.value.upper()}\n"
            f"🛡 <b>Confidence:</b> {int(signal.confidence_score * 100)}%\n"
            f"📦 <b>Status:</b> {trade_lock}\n"
            f"🆔 <code>{signal.signal_id}</code>"
        )

    def _build_inline_keyboard(self, signal: AnomalySignal) -> dict[str, Any]:
        """Create action buttons linking directly to markets."""
        buy_url = self._build_marketplace_url(signal.source_buy, signal.market_hash_name)
        sell_url = self._build_marketplace_url(signal.source_sell, signal.market_hash_name)

        return {
            "inline_keyboard": [
                [
                    {"text": f"🛒 Buy on {signal.source_buy.upper()}", "url": buy_url},
                    {"text": f"🏷 Sell on {signal.source_sell.upper()}", "url": sell_url},
                ]
            ]
        }

    async def send(self, message: str) -> bool:
        """Send plain text message to configured Telegram chat."""
        if not self.bot_token or not self.chat_id:
            logger.debug("telegram.skipped_no_credentials")
            return False

        if self.dry_run:
            logger.info("telegram.dry_run_dispatch", chat_id=self.chat_id, preview=message[:80])
            return True

        url = f"https://api.telegram.org/bot{self.bot_token.get_secret_value()}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error("telegram.send_failed", error=str(e), chat_id=self.chat_id)
            return False

    async def send_signal(self, signal: AnomalySignal) -> bool:
        """Send rich HTML message with action buttons."""
        if not self.bot_token or not self.chat_id:
            logger.debug("telegram.skipped_no_credentials")
            return False

        html_text = self.format_signal_html(signal)

        if self.dry_run:
            logger.info(
                "telegram.dry_run_signal_dispatched",
                signal_id=signal.signal_id,
                item=signal.market_hash_name,
            )
            return True

        url = f"https://api.telegram.org/bot{self.bot_token.get_secret_value()}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": html_text,
            "parse_mode": "HTML",
            "reply_markup": self._build_inline_keyboard(signal),
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                logger.info("telegram.signal_delivered", signal_id=signal.signal_id)
                return True
        except Exception as e:
            logger.error(
                "telegram.signal_delivery_failed",
                signal_id=signal.signal_id,
                error=str(e),
            )
            return False
