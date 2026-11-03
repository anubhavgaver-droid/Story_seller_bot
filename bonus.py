"""
Wallet top-up bonus. Example: 10% extra on top-ups of Rs 100 or more.
Configured by the admin in /setup -> Top-up Bonus. Stored in the database (settings key "bonus_config").
Applied for gateway top-ups (verify button / webhook) and for manually approved top-ups.
"""
from database.db import get_setting

DEFAULT_BONUS = {"enabled": False, "min_amount": 100, "percent": 10.0}


async def get_bonus_config() -> dict:
    raw = await get_setting("bonus_config", {}) or {}
    cfg = dict(DEFAULT_BONUS)
    cfg.update({k: v for k, v in raw.items() if v is not None})
    try:
        cfg["min_amount"] = float(cfg["min_amount"])
        cfg["percent"] = float(cfg["percent"])
    except (TypeError, ValueError):
        cfg["min_amount"], cfg["percent"] = DEFAULT_BONUS["min_amount"], DEFAULT_BONUS["percent"]
    return cfg


def bonus_for(amount: float, cfg: dict) -> float:
    """Bonus (in rupees, 2 decimals) for a top-up of `amount`. 0 when disabled or below the minimum."""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return 0.0
    if not cfg.get("enabled") or cfg.get("percent", 0) <= 0 or amount < cfg.get("min_amount", 0):
        return 0.0
    return round(amount * cfg["percent"] / 100.0, 2)


async def bonus_amount(amount: float) -> float:
    return bonus_for(amount, await get_bonus_config())


async def bonus_hint() -> str:
    """One-line promo text for the top-up screen, or an empty string when the bonus is off."""
    cfg = await get_bonus_config()
    if not cfg.get("enabled") or cfg["percent"] <= 0:
        return ""
    return f"🎁 Get <b>{cfg['percent']:g}% extra</b> on top-ups of ₹{cfg['min_amount']:g} or more!"
