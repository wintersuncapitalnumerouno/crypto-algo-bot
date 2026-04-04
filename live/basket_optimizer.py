"""
live/basket_optimizer.py — Stage 2 Entry Basket Optimizer
==========================================================

Scores simultaneous entry candidates and allocates position sizes
based on signal quality rather than first-come-first-served.

USAGE
-----
    from live.basket_optimizer import build_entry_basket, log_basket

    allocations = build_entry_basket(candidates, equity, open_positions)

    for alloc in allocations:
        _enter_trade(alloc["coin"], alloc["signal"], equity, size_usd=alloc["size_usd"])

DESIGN PRINCIPLES
-----------------
- Pure function: no side effects, no state, no I/O
- Risk accounting in risk-USD throughout (not notional-USD)
- Returns stop_pct and risk_usd in each allocation for debugging

SCORING FACTORS (V1)
--------------------
1. vol_ratio    — higher volume = stronger conviction
2. stoch_spread — |K - D| at cross = momentum quality
3. stop_distance — tighter stop improves capital efficiency for fixed risk budget

CONSTRAINTS
-----------
- MAX_POSITIONS       : max simultaneous open positions (existing + new)
- MAX_BASKET_RISK_PCT : max total portfolio risk across all new entries (3%)
- MAX_COIN_RISK_PCT   : max portfolio risk for any single new coin (1%)
- MIN_NOTIONAL        : minimum position notional in USD
- RISK_PER_TRADE      : base risk per trade as fraction of equity
- VOL_SIZE_MIN/MAX    : vol scaling multiplier bounds
"""

from __future__ import annotations
from typing import Any

# ── Hard constraints ──────────────────────────────────────────────────────────

MAX_POSITIONS       = 6      # max total open positions (existing + new)
MAX_BASKET_RISK_PCT = 0.03   # max total portfolio risk across all new entries (3%)
MAX_COIN_RISK_PCT   = 0.01   # max portfolio risk for any single new coin (1%)
MIN_NOTIONAL        = 10.0   # minimum position notional in USD
RISK_PER_TRADE      = 0.005  # base risk per trade as fraction of equity (0.5%)
VOL_SIZE_MIN        = 1.0    # minimum vol scaling multiplier
VOL_SIZE_MAX        = 2.0    # maximum vol scaling multiplier


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score_candidate(signal: dict[str, Any]) -> float:
    """
    Score a single entry candidate. Higher = more preferred.
    Returns a float in roughly [0, 3]. Used for ranking only.
    """
    score = 0.0

    # 1. Volume ratio — proxy for conviction (cap contribution at 2x)
    vol_ratio = float(signal.get("vol_ratio", 1.0) or 1.0)
    score += min(vol_ratio, 2.0)

    # 2. Stoch spread — |K - D|: larger = fresher cross
    k = float(signal.get("stoch_k", 50) or 50)
    d = float(signal.get("stoch_d", 50) or 50)
    spread = abs(k - d)
    score += min(spread / 30.0, 1.0)   # spread of 30 = full point

    # 3. Stop distance — tighter stop improves capital efficiency
    #    for a fixed risk budget (smaller stop → larger position for same risk)
    entry_price = float(signal.get("price", 0) or 0)
    stop_loss   = float(signal.get("stop_loss", 0) or 0)
    if entry_price > 0 and stop_loss > 0:
        stop_pct = abs(entry_price - stop_loss) / entry_price
        if stop_pct > 0:
            score += max(0.0, 1.0 - (stop_pct / 0.03))

    return round(score, 4)


# ── Sizing ────────────────────────────────────────────────────────────────────

def _calc_size(
    signal:             dict[str, Any],
    equity:             float,
    remaining_risk_usd: float,
) -> tuple[float, float, float]:
    """
    Calculate position notional and actual risk for a single candidate.

    Returns (size_usd, risk_used_usd, stop_pct).
    Returns (0, 0, 0) if position cannot meet minimum notional.

    Caps applied in order:
      1. Per-coin risk cap  (MAX_COIN_RISK_PCT * equity)
      2. Remaining basket risk budget
      3. Minimum notional floor
    """
    entry_price = float(signal.get("price", 0) or 0)
    stop_loss   = float(signal.get("stop_loss", 0) or 0)
    vol_ratio   = float(signal.get("vol_ratio", 1.0) or 1.0)

    if entry_price <= 0 or stop_loss <= 0:
        return 0.0, 0.0, 0.0

    stop_pct = abs(entry_price - stop_loss) / entry_price
    if stop_pct <= 0:
        return 0.0, 0.0, 0.0

    # Volume scaling
    vol_mult = min(max(vol_ratio, VOL_SIZE_MIN), VOL_SIZE_MAX)

    # Risk-based sizing: size = (equity * risk_pct * vol_mult) / stop_pct
    size_usd = (equity * RISK_PER_TRADE * vol_mult) / stop_pct

    # Cap by per-coin risk limit (in risk-USD)
    max_coin_risk_usd = equity * MAX_COIN_RISK_PCT
    if size_usd * stop_pct > max_coin_risk_usd:
        size_usd = max_coin_risk_usd / stop_pct

    # Recompute risk at current size, then cap by remaining basket budget
    risk_used = size_usd * stop_pct
    if risk_used > remaining_risk_usd:
        risk_used = remaining_risk_usd
        size_usd  = risk_used / stop_pct

    # Reject if below minimum notional — no early-break heuristic needed
    if size_usd < MIN_NOTIONAL:
        return 0.0, 0.0, stop_pct

    return size_usd, risk_used, stop_pct


# ── Main entry point ──────────────────────────────────────────────────────────

def build_entry_basket(
    candidates:     list[dict[str, Any]],
    equity:         float,
    open_positions: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Score and allocate a basket of simultaneous entry candidates.

    Parameters
    ----------
    candidates      : signal dicts with action in ("long", "short").
                      Each must contain: coin, action, price, stop_loss,
                      vol_ratio, stoch_k, stoch_d.
    equity          : current portfolio equity in USD.
    open_positions  : currently open positions {coin: Position}.

    Returns
    -------
    List of allocation dicts sorted best-first:
        [{
            "coin":     str,
            "signal":   dict,
            "score":    float,
            "size_usd": float,   # notional to place
            "risk_usd": float,   # USD at risk (size_usd * stop_pct)
            "stop_pct": float,   # stop distance as fraction of entry
        }, ...]
    """
    if not candidates or equity <= 0:
        return []

    slots_available = MAX_POSITIONS - len(open_positions)
    if slots_available <= 0:
        return []

    # Risk budget tracked in risk-USD throughout — never mixed with notional
    remaining_risk_usd = equity * MAX_BASKET_RISK_PCT

    # Score candidates, skip already-open coins
    scored = []
    for sig in candidates:
        coin = sig.get("coin", "")
        if not coin or coin in open_positions:
            continue
        scored.append({"coin": coin, "signal": sig, "score": _score_candidate(sig)})

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Allocate top-down; _calc_size() handles all rejection logic
    allocations = []
    for item in scored:
        if len(allocations) >= slots_available:
            break

        size_usd, risk_used, stop_pct = _calc_size(
            item["signal"], equity, remaining_risk_usd
        )
        if size_usd <= 0:
            continue

        allocations.append({
            "coin":     item["coin"],
            "signal":   item["signal"],
            "score":    item["score"],
            "size_usd": size_usd,
            "risk_usd": risk_used,
            "stop_pct": stop_pct,
        })
        remaining_risk_usd -= risk_used   # deduct actual risk, not notional

    return allocations


# ── Diagnostics ───────────────────────────────────────────────────────────────

def log_basket(allocations: list[dict[str, Any]], log_fn=print) -> None:
    """Log basket allocations in a readable format."""
    if not allocations:
        log_fn("  📦 Basket: no candidates selected")
        return

    total_risk     = sum(a["risk_usd"] for a in allocations)
    total_notional = sum(a["size_usd"] for a in allocations)
    log_fn(
        f"  📦 Basket: {len(allocations)} selected | "
        f"notional=${total_notional:.2f} | risk=${total_risk:.4f}"
    )
    for a in allocations:
        log_fn(
            f"    {a['coin']:<6} score={a['score']:.3f} "
            f"size=${a['size_usd']:.2f} "
            f"risk=${a['risk_usd']:.4f} "
            f"stop={a['stop_pct']*100:.2f}% "
            f"action={a['signal'].get('action')} "
            f"vol={a['signal'].get('vol_ratio', 0):.2f}"
        )
