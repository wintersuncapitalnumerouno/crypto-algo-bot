"""
test_basket_optimizer.py — Validate basket_optimizer.py

Run from project root:
    python live/test_basket_optimizer.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from live.basket_optimizer import (
    build_entry_basket, log_basket,
    MAX_BASKET_RISK_PCT, MAX_COIN_RISK_PCT, MAX_POSITIONS, MIN_NOTIONAL, RISK_PER_TRADE
)

MOCK_SIGNALS = [
    {
        "coin": "ETH", "action": "long",
        "price": 2050.0, "stop_loss": 2009.0,   # 2.00% stop
        "vol_ratio": 1.52, "stoch_k": 82.0, "stoch_d": 74.0,
    },
    {
        "coin": "SOL", "action": "long",
        "price": 80.0, "stop_loss": 78.4,        # 2.00% stop
        "vol_ratio": 0.51, "stoch_k": 28.0, "stoch_d": 22.0,
    },
    {
        "coin": "DOGE", "action": "long",
        "price": 0.091, "stop_loss": 0.0892,     # ~1.98% stop
        "vol_ratio": 0.55, "stoch_k": 32.0, "stoch_d": 26.0,
    },
    {
        "coin": "XRP", "action": "long",
        "price": 1.32, "stop_loss": 1.294,       # ~1.97% stop
        "vol_ratio": 0.50, "stoch_k": 42.0, "stoch_d": 31.0,
    },
    {
        "coin": "LINK", "action": "long",
        "price": 8.70, "stop_loss": 8.52,        # ~2.07% stop
        "vol_ratio": 0.50, "stoch_k": 34.0, "stoch_d": 28.0,
    },
]

EQUITY = 51.30
OPEN_POSITIONS = {"DOGE": object(), "XRP": object()}


def run_test():
    print("=" * 60)
    print("  Basket Optimizer — V1 Test")
    print("=" * 60)
    print(f"\n  Equity:               ${EQUITY}")
    print(f"  Max basket risk:      ${EQUITY * MAX_BASKET_RISK_PCT:.4f} ({MAX_BASKET_RISK_PCT*100:.1f}%)")
    print(f"  Max coin risk:        ${EQUITY * MAX_COIN_RISK_PCT:.4f} ({MAX_COIN_RISK_PCT*100:.1f}%)")
    print(f"  Base risk per trade:  ${EQUITY * RISK_PER_TRADE:.4f} ({RISK_PER_TRADE*100:.2f}%)")
    print(f"  Open positions:       {list(OPEN_POSITIONS.keys())}")
    print(f"  Slots available:      {MAX_POSITIONS - len(OPEN_POSITIONS)}")
    print(f"  Candidates:           {[s['coin'] for s in MOCK_SIGNALS]}")
    print()

    allocations = build_entry_basket(MOCK_SIGNALS, EQUITY, OPEN_POSITIONS)
    log_basket(allocations, log_fn=lambda x: print(x))

    print()
    print(f"  {'Coin':<6} {'Score':>6} {'Size $':>8} {'Risk $':>8} {'Stop%':>6} {'Action'}")
    print("  " + "-" * 52)
    for a in allocations:
        print(
            f"  {a['coin']:<6} {a['score']:>6.3f} "
            f"{a['size_usd']:>8.2f} "
            f"{a['risk_usd']:>8.4f} "
            f"{a['stop_pct']*100:>5.2f}% "
            f"{a['signal'].get('action')}"
        )

    errors = []
    coins = [a["coin"] for a in allocations]

    # Already-open coins must not appear
    for coin in list(OPEN_POSITIONS.keys()):
        if coin in coins:
            errors.append(f"FAIL: {coin} selected but already open")

    # Slot cap
    max_new = MAX_POSITIONS - len(OPEN_POSITIONS)
    if len(allocations) > max_new:
        errors.append(f"FAIL: {len(allocations)} allocations > {max_new} slots")

    # All required fields present and stop_pct positive
    for a in allocations:
        for field in ("coin", "signal", "score", "size_usd", "risk_usd", "stop_pct"):
            if field not in a:
                errors.append(f"FAIL: {a.get('coin','?')} missing field '{field}'")
        if a.get("stop_pct", 0) <= 0:
            errors.append(f"FAIL: {a['coin']} has non-positive stop_pct")

    # All notionals >= MIN_NOTIONAL
    for a in allocations:
        if a["size_usd"] < MIN_NOTIONAL:
            errors.append(f"FAIL: {a['coin']} size ${a['size_usd']} < MIN_NOTIONAL ${MIN_NOTIONAL}")

    # risk_usd == size_usd * stop_pct (accounting integrity)
    for a in allocations:
        expected = a["size_usd"] * a["stop_pct"]
        if abs(expected - a["risk_usd"]) > 1e-4:
            errors.append(
                f"FAIL: {a['coin']} risk_usd={a['risk_usd']:.6f} != "
                f"size*stop={expected:.6f}"
            )

    # Total basket risk <= budget
    total_risk = sum(a["risk_usd"] for a in allocations)
    basket_budget = EQUITY * MAX_BASKET_RISK_PCT
    if total_risk > basket_budget + 1e-6:
        errors.append(
            f"FAIL: total risk ${total_risk:.6f} exceeds basket budget ${basket_budget:.6f}"
        )

    # Per-coin risk <= MAX_COIN_RISK_PCT * equity
    max_coin_risk = EQUITY * MAX_COIN_RISK_PCT
    for a in allocations:
        if a["risk_usd"] > max_coin_risk + 1e-6:
            errors.append(
                f"FAIL: {a['coin']} risk ${a['risk_usd']:.6f} > max ${max_coin_risk:.6f}"
            )

    # Per-coin size not above what the risk cap should produce
    for a in allocations:
        max_size_from_risk_cap = max_coin_risk / a["stop_pct"]
        if a["size_usd"] > max_size_from_risk_cap + 0.01:
            errors.append(
                f"FAIL: {a['coin']} size ${a['size_usd']:.2f} exceeds "
                f"risk-cap-implied max ${max_size_from_risk_cap:.2f}"
            )

    # ETH should be selected (highest vol_ratio in this mock set)
    if "ETH" not in coins and len(allocations) > 0:
        errors.append("FAIL: ETH not selected despite highest vol_ratio")

    print()
    if errors:
        print("  ❌ FAILED:")
        for e in errors:
            print(f"    {e}")
    else:
        print("  ✅ All assertions passed")
        print(f"     Total risk: ${total_risk:.4f} / ${basket_budget:.4f} budget "
              f"({total_risk/basket_budget*100:.1f}% used)")

    # ── Edge cases ────────────────────────────────────────────────────────────
    print()
    print("  Edge cases:")

    full = {c: object() for c in ["ETH", "SOL", "DOGE", "XRP", "LINK", "AAVE"]}
    assert build_entry_basket(MOCK_SIGNALS, EQUITY, full) == [], "No slots → non-empty"
    print("  ✅ No slots → empty list")

    assert build_entry_basket([], EQUITY, {}) == [], "No candidates → non-empty"
    print("  ✅ No candidates → empty list")

    assert build_entry_basket(MOCK_SIGNALS, 0, {}) == [], "Zero equity → non-empty"
    print("  ✅ Zero equity → empty list")

    # Signals missing 'coin' key — should be skipped gracefully
    bad_signals = [{"action": "long", "price": 100.0, "stop_loss": 98.0, "vol_ratio": 1.0}]
    result = build_entry_basket(bad_signals, EQUITY, {})
    assert result == [], f"Missing coin key → should skip, got {result}"
    print("  ✅ Missing coin field → skipped gracefully")

    # Tiny equity — all positions below MIN_NOTIONAL should be rejected
    result = build_entry_basket(MOCK_SIGNALS, 1.0, {})
    for a in result:
        assert a["size_usd"] >= MIN_NOTIONAL, f"{a['coin']} below min at tiny equity"
    print("  ✅ Tiny equity → no sub-minimum positions")

    print()
    print("=" * 60)
    print("  Test complete")
    print("=" * 60)


if __name__ == "__main__":
    run_test()
