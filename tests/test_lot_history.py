import pandas as pd
import pytest

from goodcup.analysis.lot_history import repeatability_summary, require_single_temperature_unit


def test_repeatability_summary_reports_spread_and_curve_coverage():
    roasts = pd.DataFrame({
        "mean_total_score": [84.0, 84.5, 85.0],
        "dtr_pct": [18.0, 19.0, 20.0],
        "drop_temp": [208.0, 209.0, 210.0],
        "total_time_s": [580.0, 590.0, 600.0],
        "curve_available": [1, 1, 0],
    })
    result = repeatability_summary(roasts)
    assert result["n_roasts"] == 3
    assert result["score_sd"] == pytest.approx(0.5)
    assert result["curve_coverage"] == pytest.approx(2 / 3)
    assert result["status"] == "Tight score repeatability"


def test_unit_check_accepts_one_unit_and_rejects_mixed_units():
    assert require_single_temperature_unit(pd.DataFrame({"temp_unit": ["C", "C"]})) == "C"
    with pytest.raises(ValueError, match="mixed"):
        require_single_temperature_unit(pd.DataFrame({"temp_unit": ["C", "F"]}))
