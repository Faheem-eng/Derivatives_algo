import os
from dataclasses import dataclass

MODE = os.getenv("MODE", "shadow")   # shadow | testnet | live
BASES = {"shadow": "https://fapi.binance.com",
         "live": "https://fapi.binance.com",
         "testnet": "https://testnet.binancefuture.com"}
BASE_URL = BASES[MODE]
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# Endpoint versions badalte rehte hain; changelog se verify karo
ACCOUNT_PATH = "/fapi/v2/account"
POSRISK_PATH = "/fapi/v2/positionRisk"

@dataclass
class P:
    universe_n: int = 20
    min_listing_days: int = 90
    max_spread_pct: float = 0.05
    adx4h_min: float = 22
    adx1h_min: float = 20
    donchian: int = 20
    chase_atr: float = 1.5
    vol_mult: float = 1.5
    soft_min: int = 6
    stop_atr: float = 2.5
    trail_atr: float = 3.0
    time_stop_bars: int = 24
    time_stop_r: float = 0.5
    gap_atr_max: float = 0.5
    risk_pct: float = 0.005
    leverage: int = 2
    max_positions: int = 5
    max_open_risk_pct: float = 0.03
    max_notional_x: float = 1.5
    daily_loss_pct: float = 0.02
    weekly_loss_pct: float = 0.05
    dd_pause_pct: float = 0.10
    dd_kill_pct: float = 0.20
    cooldown_bars: int = 6
    max_funding: float = 0.0005
    fee_rate: float = 0.0005
    slip_rate: float = 0.0005
    start_equity: float = 1000.0     # sirf shadow mode