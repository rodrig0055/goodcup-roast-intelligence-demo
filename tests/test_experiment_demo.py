import pytest

from goodcup.dashboard.experiment_demo import DEFAULT_CUP_SCORES, evaluate_blind_results


def test_blind_result_ranking_and_cautious_decision():
    result = evaluate_blind_results(DEFAULT_CUP_SCORES)
    assert result["winner"]["blind_code"] == "728"
    assert result["winner"]["n"] == 3
    assert result["margin"] == pytest.approx(0.75)
    assert "confirmation roast" in result["decision"]


def test_close_result_is_inconclusive():
    result = evaluate_blind_results({
        "314": [84.0, 84.1], "728": [84.2, 84.1], "561": [84.0, 84.2]
    })
    assert "No clear leader" in result["decision"]


def test_invalid_score_is_rejected():
    with pytest.raises(ValueError):
        evaluate_blind_results({
            "314": [84.0, 101.0], "728": [84.0, 84.0], "561": [84.0, 84.0]
        })
