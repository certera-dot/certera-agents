"""
Tests del RiskManager — correr antes de cualquier deploy
"""
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.risk_manager import RiskManager, RiskViolation

@pytest.fixture
def rm():
    os.environ.update({"RISK_PER_TRADE_PCT":"1.0","STOP_LOSS_MAX_PCT":"2.0",
                        "DRAWDOWN_MAX_PCT":"15.0","DAILY_LOSS_LIMIT_PCT":"5.0"})
    return RiskManager()

VALID = {"asset":"BTCUSDT","signal_type":"LONG","entry":65000,
         "stop_loss":63700,"take_profit":[67600],"min_rr":2.0}

def test_valid_signal_approved(rm):
    assert rm.validate(VALID).approved

def test_stop_too_wide_rejected(rm):
    s = {**VALID,"stop_loss":63000}   # ~3% stop
    r = rm.validate(s)
    assert not r.approved
    assert r.reason == RiskViolation.STOP_TOO_WIDE

def test_bad_rr_rejected(rm):
    s = {**VALID,"take_profit":[65600],"min_rr":2.0}  # ~0.46 R:R
    r = rm.validate(s)
    assert not r.approved
    assert r.reason == RiskViolation.BAD_RR

def test_incomplete_signal_rejected(rm):
    r = rm.validate({"asset":"BTC"})
    assert not r.approved
    assert r.reason == RiskViolation.NO_SIGNAL

def test_daily_loss_limit_triggers_pause(rm):
    rm.daily_pnl_pct = -5.1
    r = rm.validate(VALID)
    assert not r.approved
    assert rm.is_paused

def test_drawdown_triggers_pause(rm):
    rm.current_drawdown_pct = 15.1
    r = rm.validate(VALID)
    assert not r.approved
    assert rm.is_paused

def test_consecutive_stops_pause(rm):
    rm.consecutive_stops = 3
    r = rm.validate(VALID)
    assert not r.approved
    assert r.reason == RiskViolation.CONSECUTIVE_STOPS

def test_kill_switch_blocks_all(rm):
    rm.kill_switch()
    assert not rm.validate(VALID).approved

def test_resume_after_pause(rm):
    rm.kill_switch()
    rm.resume()
    assert rm.validate(VALID).approved

def test_position_size_calc(rm):
    ps = rm.calc_position_size(10000, 65000, 63700)
    assert ps["risk_usd"] == 100.0
    assert ps["units"] > 0

def test_register_win_resets_consecutive(rm):
    rm.consecutive_stops = 2
    rm.register_result("WIN", 1.5)
    assert rm.consecutive_stops == 0

def test_register_loss_increments_consecutive(rm):
    rm.register_result("LOSS", -1.0)
    assert rm.consecutive_stops == 1
