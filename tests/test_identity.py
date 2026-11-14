"""Unit tests for CS2 item identity and hashing engine."""

from decimal import Decimal

from collectibles.core.identity import CS2ItemIdentity, StickerInfo


def test_wear_bucket_classification() -> None:
    # Factory New (<0.07)
    item_fn = CS2ItemIdentity(market_hash_name="AK-47 | Redline", float_value=Decimal("0.05"))
    assert item_fn.get_wear_bucket() == "factory_new"

    # Minimal Wear (0.07 - 0.15)
    item_mw = CS2ItemIdentity(market_hash_name="AK-47 | Redline", float_value=Decimal("0.12"))
    assert item_mw.get_wear_bucket() == "minimal_wear"

    # Field-Tested standard (0.22 - 0.38)
    item_ft = CS2ItemIdentity(market_hash_name="AK-47 | Redline", float_value=Decimal("0.25"))
    assert item_ft.get_wear_bucket() == "field_tested"

    # Field-Tested low float (<0.22)
    item_ft_low = CS2ItemIdentity(market_hash_name="AK-47 | Redline", float_value=Decimal("0.20"))
    assert item_ft_low.get_wear_bucket() == "ft_low_float"

    # Minimal Wear low float (<0.09)
    item_mw_low = CS2ItemIdentity(market_hash_name="AK-47 | Redline", float_value=Decimal("0.08"))
    assert item_mw_low.get_wear_bucket() == "mw_low_float"

    # Triple zero extreme float (<0.01)
    item_extreme = CS2ItemIdentity(market_hash_name="AK-47 | Redline", float_value=Decimal("0.005"))
    assert item_extreme.get_wear_bucket() == "fn_triple_zero"
    assert not item_extreme.is_commodity_grade()


def test_identity_hash_reconciliation() -> None:
    # Two identical Field-Tested skins with slightly different floats should match in commodity mode
    skin_a = CS2ItemIdentity(
        market_hash_name="M4A4 | Asiimov (Field-Tested)",
        float_value=Decimal("0.25"),
        is_stattrak=False,
    )
    skin_b = CS2ItemIdentity(
        market_hash_name="M4A4 | Asiimov (Field-Tested)",
        float_value=Decimal("0.28"),
        is_stattrak=False,
    )

    hash_a = skin_a.compute_identity_hash(strict_mode=False)
    hash_b = skin_b.compute_identity_hash(strict_mode=False)
    assert hash_a == hash_b

    # But with strict mode, different floats produce distinct hashes
    hash_strict_a = skin_a.compute_identity_hash(strict_mode=True)
    hash_strict_b = skin_b.compute_identity_hash(strict_mode=True)
    assert hash_strict_a != hash_strict_b


def test_stickers_prevent_commodity_matching() -> None:
    skin_clean = CS2ItemIdentity(
        market_hash_name="AK-47 | Vulcan (Field-Tested)",
        float_value=Decimal("0.20"),
    )
    skin_stickered = CS2ItemIdentity(
        market_hash_name="AK-47 | Vulcan (Field-Tested)",
        float_value=Decimal("0.20"),
        stickers=[StickerInfo(slot=0, name="Titan | Katowice 2014")],
    )

    assert skin_clean.is_commodity_grade() is True
    assert skin_stickered.is_commodity_grade() is False
    assert skin_clean.compute_identity_hash() != skin_stickered.compute_identity_hash()
