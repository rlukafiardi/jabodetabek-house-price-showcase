import pandas as pd

from src.pipeline.weekly_report import BIAS_ALERT, ERROR_ALERT, MIN_N, alerts_for


def weekly(errors: list[float], bias: float = 0.0, n_each: int = 120) -> pd.DataFrame:
    return pd.DataFrame({"week": pd.date_range("2026-07-05", periods=len(errors), freq="7D"), "n": n_each, "median_ape": errors,
                         "cum_n": [n_each * (i + 1) for i in range(len(errors))], "cum_median_ape": errors, "cum_bias": bias})


NO_CITIES = pd.DataFrame({"n": [], "median_ape": [], "bias": []}, index=pd.Index([], name="city"))
NO_DRIFT = pd.DataFrame({"feature": ["lat"], "psi": [0.01], "ks": [0.02], "missing_ref": [0.0], "missing_now": [0.0]})


def test_quiet_when_everything_is_inside_the_limits():
    assert alerts_for(weekly([0.2, 0.2, 0.2]), NO_CITIES, NO_DRIFT, 0.95) == []


def test_error_alert_needs_two_weeks_above_the_limit():
    assert alerts_for(weekly([0.2, 0.2, ERROR_ALERT + 0.01]), NO_CITIES, NO_DRIFT, 0.95) == []
    assert len(alerts_for(weekly([0.2, ERROR_ALERT + 0.01, ERROR_ALERT + 0.02]), NO_CITIES, NO_DRIFT, 0.95)) == 1


def test_error_and_bias_are_not_judged_below_the_minimum_sample():
    small = weekly([0.4, 0.4], bias=0.2, n_each=MIN_N // 4)
    assert alerts_for(small, NO_CITIES, NO_DRIFT, 0.95) == []


def test_overall_bias_alert():
    assert any("bias" in a.lower() for a in alerts_for(weekly([0.2, 0.2, 0.2], bias=BIAS_ALERT + 0.02), NO_CITIES, NO_DRIFT, 0.95))


def test_city_bias_alert_needs_enough_listings():
    cities = pd.DataFrame({"n": [80, 10], "median_ape": [0.3, 0.3], "bias": [0.2, 0.2]}, index=["Kota A", "Kota B"])
    alerts = alerts_for(weekly([0.2, 0.2, 0.2]), cities, NO_DRIFT, 0.95)
    assert len(alerts) == 1 and "Kota A" in alerts[0]


def test_drift_missing_share_and_parse_rate_alerts():
    drift = pd.DataFrame({"feature": ["floors", "lat"], "psi": [0.63, 0.01], "ks": [0.3, 0.02], "missing_ref": [0.19, 0.0], "missing_now": [0.56, 0.0]})
    alerts = alerts_for(weekly([0.2, 0.2, 0.2]), NO_CITIES, drift, 0.5)
    assert len(alerts) == 3
