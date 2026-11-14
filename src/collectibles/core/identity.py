"""CS2 Item Identity and Canonical Hash Generation Engine."""

import hashlib
import json
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class StickerInfo(BaseModel):
    """Normalized sticker representation on an item."""

    model_config = ConfigDict(frozen=True)

    slot: int = Field(..., ge=0, le=4)
    name: str
    wear: Decimal | None = Field(default=None, ge=Decimal("0.0"), le=Decimal("1.0"))


class CS2ItemIdentity(BaseModel):
    """Domain model capturing full CS2 item identity parameters."""

    model_config = ConfigDict(frozen=True)

    market_hash_name: str
    paint_index: int | None = None
    paint_seed: int | None = None
    float_value: Decimal | None = Field(default=None, ge=Decimal("0.0"), le=Decimal("1.0"))
    is_stattrak: bool = False
    is_souvenir: bool = False
    phase: str | None = None
    stickers: list[StickerInfo] = Field(default_factory=list)

    def get_wear_bucket(self) -> str:
        """Classify item into wear bucket and precision tiers."""
        if self.float_value is None:
            return "unknown_wear"

        fv = self.float_value
        if fv < Decimal("0.01"):
            return "fn_triple_zero"
        if fv < Decimal("0.07"):
            return "factory_new"
        if fv < Decimal("0.15"):
            return "minimal_wear"
        if fv < Decimal("0.38"):
            return "field_tested"
        if fv < Decimal("0.45"):
            return "well_worn"
        if fv >= Decimal("0.95"):
            return "bs_high_float"
        return "battle_scarred"

    def is_commodity_grade(self) -> bool:
        """Check if item can be treated as a fungible commodity without collectors premium."""
        has_valuable_stickers = len(self.stickers) > 0
        has_rare_phase = self.phase is not None and self.phase.lower() in {
            "ruby",
            "sapphire",
            "black pearl",
            "emerald",
        }
        has_extreme_float = self.float_value is not None and (
            self.float_value < Decimal("0.01") or self.float_value >= Decimal("0.95")
        )

        return not (has_valuable_stickers or has_rare_phase or has_extreme_float)

    def compute_identity_hash(self, strict_mode: bool = False) -> str:
        """Compute deterministic SHA256 identity hash for cross-source reconciliation.

        Args:
            strict_mode: If True, incorporates exact paint_seed and float.
                         If False, matches by market_hash_name, stattrak, souvenir,
                         and wear bucket (for commodity pricing).
        """
        sorted_stickers = sorted(
            [{"slot": s.slot, "name": s.name} for s in self.stickers],
            key=lambda x: int(str(x["slot"])),
        )

        payload = {
            "market_hash_name": self.market_hash_name.strip(),
            "is_stattrak": self.is_stattrak,
            "is_souvenir": self.is_souvenir,
            "phase": self.phase.lower().strip() if self.phase else None,
            "stickers": sorted_stickers,
        }

        if strict_mode:
            payload["paint_index"] = self.paint_index
            payload["paint_seed"] = self.paint_seed
            payload["float_value"] = str(self.float_value) if self.float_value is not None else None
        else:
            payload["wear_bucket"] = self.get_wear_bucket()

        serialized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
