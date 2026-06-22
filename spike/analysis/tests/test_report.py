import pandas as pd

from analysis.report import summarize, verdict


def test_summarize_buckets_by_horizon():
    df = pd.DataFrame(
        {
            "horizon_m": [500.0, 500.0, 2000.0],
            "abs_err_s": [10.0, 30.0, 120.0],
            "abs_err_pct": [0.05, 0.10, 0.20],
            "actual_s": [200.0, 200.0, 600.0],
        }
    )
    s = summarize(df, group="horizon_m")
    assert set(s.columns) >= {"p50_abs_err_s", "p90_abs_err_s", "p50_abs_err_pct", "n"}
    assert s.loc[500.0, "n"] == 2


def test_verdict_go_when_beats_baseline_and_threshold():
    assert verdict(model_p50_pct=0.10, baseline_p50_pct=0.20) == "GO"
    # não bate baseline por 25%
    assert verdict(model_p50_pct=0.18, baseline_p50_pct=0.20) == "NO-GO"
    # bate baseline mas erro absoluto alto demais
    assert verdict(model_p50_pct=0.22, baseline_p50_pct=0.40) == "NO-GO"
