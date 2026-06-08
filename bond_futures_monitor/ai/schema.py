"""AI text-signal schema constants."""

EVENT_TYPES = {
    "monetary_policy",
    "fiscal_policy",
    "macro_growth",
    "inflation",
    "bond_supply",
    "funding_liquidity",
    "risk_sentiment",
    "overseas_rates",
    "other",
}

BOND_IMPACTS = {"bullish", "bearish", "neutral"}

AFFECTED_MATURITIES = {"short_end", "belly", "long_end", "full_curve", "unclear"}

CONTRACTS = {"TS", "TF", "T", "TL"}
