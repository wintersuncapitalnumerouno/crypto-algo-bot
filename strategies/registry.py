# =============================================================
# strategies/registry.py — Strategy Registry
# =============================================================
#
# VERSIONING RULE:
#   Each strategy version = separate registry entry.
#   Each entry imports its own frozen params file DIRECTLY.
#
# HOW TO RUN:
#   python backtest/engine.py --strategy EMA16_V8A --tag my_tag
#   python backtest/engine.py --strategy STOCHVOL_V1 --tag my_tag
#   python backtest/engine.py --strategy STOCHVOL_V1 STOCHVOL_V3 --tag compare
#
# HOW TO ADD A NEW VERSION:
#   1. Freeze params: strategies/stochvol/params_vN.py
#   2. Import here
#   3. Add entry to REGISTRY dict below
# =============================================================

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

# ── EMA16 signal function ─────────────────────────────────────
from strategies.ema16.strategy import get_entries_exits as ema16_signals

# ── StochVol signal functions ─────────────────────────────────
try:
    from strategies.stochvol.strategy import get_entries_exits as stochvol_signals
    _has_stochvol = True
except ImportError:
    stochvol_signals = None
    _has_stochvol = False

try:
    from strategies.stochvol.strategy_v2 import get_entries_exits as stochvol_v2_signals
    _has_stochvol_v2 = True
except ImportError:
    stochvol_v2_signals = None
    _has_stochvol_v2 = False

try:
    from strategies.stochvol.strategy_v3 import get_entries_exits as stochvol_v3_signals
    _has_stochvol_v3 = True
except ImportError:
    stochvol_v3_signals = None
    _has_stochvol_v3 = False

# ── Optional strategy signal functions ───────────────────────
try:
    from strategies.momentum.strategy import get_entries_exits as momentum_signals
    _has_momentum = True
except ImportError:
    momentum_signals = None
    _has_momentum = False

try:
    from strategies.breakout.strategy import get_entries_exits as breakout_signals
    _has_breakout = True
except ImportError:
    breakout_signals = None
    _has_breakout = False

try:
    from strategies.supertrend.strategy import get_entries_exits as supertrend_signals
    _has_supertrend = True
except ImportError:
    supertrend_signals = None
    _has_supertrend = False

# ── EMA16 frozen params ───────────────────────────────────────
from strategies.ema16.params_v4  import get_default_params as _ema16_v4_params
from strategies.ema16.params_v5  import get_default_params as _ema16_v5_params
from strategies.ema16.params_v6  import get_default_params as _ema16_v6_params
from strategies.ema16.params_v7  import get_default_params as _ema16_v7_params
from strategies.ema16.params_v8a import get_default_params as _ema16_v8a_params
from strategies.ema16.params_v8b import get_default_params as _ema16_v8b_params
from strategies.ema16.params_v8c import get_default_params as _ema16_v8c_params
from strategies.ema16.params_v8d import get_default_params as _ema16_v8d_params

# ── StochVol frozen params ────────────────────────────────────
try:
    from strategies.stochvol.params_v1 import get_default_params as _stochvol_v1_params
except ImportError:
    _stochvol_v1_params = lambda: {}

try:
    from strategies.stochvol.params_v2 import get_default_params as _stochvol_v2_params
except ImportError:
    _stochvol_v2_params = lambda: {}

try:
    from strategies.stochvol.params_v3 import get_default_params as _stochvol_v3_params
except ImportError:
    _stochvol_v3_params = lambda: {}

# ── Momentum frozen params ────────────────────────────────────
try:
    from strategies.momentum.params_v1 import get_default_params as _momentum_v1_params
except ImportError:
    _momentum_v1_params = lambda: {}
    _has_momentum = False


# ── Registry ─────────────────────────────────────────────────
REGISTRY = {

    # ── EMA16 versions ────────────────────────────────────────

    "EMA16_V4": {
        "fn":          ema16_signals,
        "params":      _ema16_v4_params(),
        "params_file": "strategies/ema16/params_v4.py",
        "description": "EMA16 4h | RSI 52-65/35-48 | fixed 2% stop | scaled exits 40/30/30",
        "enabled":     True,
    },

    "EMA16_V5": {
        "fn":          ema16_signals,
        "params":      _ema16_v5_params(),
        "params_file": "strategies/ema16/params_v5.py",
        "description": "EMA16 4h | RSI 52-65/35-48 | ATR 2.5× stop | scaled exits 40/30/30",
        "enabled":     True,
    },

    "EMA16_V6": {
        "fn":          ema16_signals,
        "params":      _ema16_v6_params(),
        "params_file": "strategies/ema16/params_v6.py",
        "description": "EMA16 4h | RSI 52-65/35-48 | ATR 2.5x stop | scaled exits 1.5/2.5/4.0 restored",
        "enabled":     True,
    },

    "EMA16_V7": {
        "fn":          ema16_signals,
        "params":      _ema16_v7_params(),
        "params_file": "strategies/ema16/params_v7.py",
        "description": "EMA16 4h | RSI 52-65/35-48 | ATR 2.5x stop | dynamic trail: 0.3% normal, 0.2% above +3%",
        "enabled":     True,
    },

    "EMA16_V8A": {
        "fn":          ema16_signals,
        "params":      _ema16_v8a_params(),
        "params_file": "strategies/ema16/params_v8a.py",
        "description": "EMA16 V8A | ATR×0.7 stop placement | fixed 2% sizing | ACTIVE BASELINE",
        "enabled":     True,
    },

    "EMA16_V8B": {
        "fn":          ema16_signals,
        "params":      _ema16_v8b_params(),
        "params_file": "strategies/ema16/params_v8b.py",
        "description": "EMA16 V8B | ATR×0.7 stop + adaptive sizing",
        "enabled":     True,
    },

    "EMA16_V8C": {
        "fn":          ema16_signals,
        "params":      _ema16_v8c_params(),
        "params_file": "strategies/ema16/params_v8c.py",
        "description": "EMA16 V8C | ATR×0.5 stop + adaptive sizing",
        "enabled":     True,
    },

    "EMA16_V8D": {
        "fn":          ema16_signals,
        "params":      _ema16_v8d_params(),
        "params_file": "strategies/ema16/params_v8d.py",
        "description": "EMA16 V8D | ATR×1.0 stop + adaptive sizing",
        "enabled":     True,
    },

    # ── StochVol versions ─────────────────────────────────────

    "STOCHVOL_V1": {
        "fn":          stochvol_signals if _has_stochvol else None,
        "params":      _stochvol_v1_params(),
        "params_file": "strategies/stochvol/params_v1.py",
        "description": "Stochastic(14,3,3) cross | volume confirmation + sizing | ATR×0.7 stop | vol dry-up exit",
        "enabled":     _has_stochvol,
    },

    "STOCHVOL_V2": {
        "fn":          stochvol_v2_signals if _has_stochvol_v2 else None,
        "params":      _stochvol_v2_params(),
        "params_file": "strategies/stochvol/params_v2.py",
        "description": "StochVol V2 | adaptive ATR stop: 0.7x normal volume, 1.0x high volume entries",
        "enabled":     _has_stochvol_v2,
    },

    "STOCHVOL_V3": {
        "fn":          stochvol_v3_signals if _has_stochvol_v3 else None,
        "params":      _stochvol_v3_params(),
        "params_file": "strategies/stochvol/params_v3.py",
        "description": "StochVol V3 | Stoch(21,5,5) | entry window 3 candles | vol_min 0.5",
        "enabled":     _has_stochvol_v3,
    },

    # ── Other strategies ──────────────────────────────────────

    "Momentum": {
        "fn":          momentum_signals if _has_momentum else None,
        "params":      _momentum_v1_params(),
        "params_file": "strategies/momentum/params_v1.py",
        "description": "EMA crossover 9/21 | ATR stop | 15m",
        "enabled":     _has_momentum,
    },

    "Breakout": {
        "fn":          breakout_signals if _has_breakout else None,
        "params":      {},
        "params_file": "strategies/breakout/params_v1.py",
        "description": "Range breakout | skeleton",
        "enabled":     _has_breakout,
    },

    "SuperTrend": {
        "fn":          supertrend_signals if _has_supertrend else None,
        "params":      {},
        "params_file": "strategies/supertrend/params_v1.py",
        "description": "SuperTrend ATR | skeleton",
        "enabled":     _has_supertrend,
    },
}


# ── Helpers ───────────────────────────────────────────────────

def get_strategies(names: list = None) -> dict:
    active = {
        k: v for k, v in REGISTRY.items()
        if v.get("enabled") and v.get("fn") is not None
    }
    if names:
        unknown = [n for n in names if n not in REGISTRY]
        if unknown:
            raise ValueError(
                f"Unknown strategies: {unknown}\n"
                f"Available: {list(REGISTRY.keys())}"
            )
        active = {k: v for k, v in active.items() if k in names}
    return active


def list_strategies():
    print("\n📋 Strategy Registry:")
    print(f"  {'Name':<15} {'Enabled':<10} {'Params File':<40} {'Description'}")
    print("  " + "─" * 95)
    for name, cfg in REGISTRY.items():
        status      = "✅ ON " if cfg.get("enabled") and cfg.get("fn") else "❌ OFF"
        params_file = cfg.get("params_file", "—")
        print(f"  {name:<15} {status:<10} {params_file:<40} {cfg['description']}")
    print()


if __name__ == "__main__":
    list_strategies()
