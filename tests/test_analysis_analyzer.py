"""Tests for the analysis itself — the arithmetic behind every sentence.

A report engine that returns *something* is worthless; the numbers have to be
right. So the fixtures here are deliberately tiny and hand-computable, and the
assertions are exact values worked out on paper, not "assert result is not
None":

* ``group_by`` sums, means, counts, medians and the TOTAL row;
* the weighted mean, where weighting by call volume is the difference between
  a true AHT and an average-of-averages;
* ``time_series`` period bucketing, period-over-period deltas and the 3-period
  moving average;
* IQR outlier detection with its exact Q1/Q3/band;
* Pearson correlation against known ±1 cases.

The other half is the promise that nothing here ever raises: one column, all
text, three rows, a filter that matches nothing — each must come back as a
valid, empty-ish result carrying a Turkish explanation in ``notes``.
"""

from __future__ import annotations

import math
from datetime import datetime

import pytest

from ai_assistant.analysis.analyzer import (
    AnalysisRequest,
    Filter,
    Measure,
    TONE_BAD,
    TONE_GOOD,
    TONE_INFO,
    TONE_WARN,
    analyze,
    apply_request_filters,
    call_center_kpis,
    correlations,
    default_agg,
    find_outliers,
    format_duration,
    format_number,
    format_value,
    group_by,
    make_finding,
    measure_for,
    pearson,
    resolve_columns,
    time_series,
)
from ai_assistant.analysis.dataset import load_csv, profile_table

FIXTURE = "tests/fixtures/cagri_merkezi.csv"


@pytest.fixture()
def call_centre():
    return load_csv(FIXTURE)


def _shifts():
    """Four rows, two shifts. Every aggregate below is checkable by hand.

    Sabah: 10 + 30 = 40 calls, SLA 80 and 60.
    Akşam: 20 + 40 = 60 calls, SLA 90 and 70.
    """
    return profile_table(
        ["Vardiya", "Çağrı Adedi", "SLA %"],
        [
            ["Sabah", "10", "%80"],
            ["Akşam", "20", "%90"],
            ["Sabah", "30", "%60"],
            ["Akşam", "40", "%70"],
        ],
    )


# --- Turkish formatting ------------------------------------------------------


@pytest.mark.parametrize(
    "value, digits, expected",
    [
        (1234.5, 1, "1.234,5"),
        (1234567.89, 2, "1.234.567,89"),
        (1234.5, 0, "1.234"),
        (-1234.5, 1, "-1.234,5"),
        (0.0, 1, "0,0"),
        (None, 1, "—"),
    ],
)
def test_format_number_is_turkish(value, digits, expected):
    assert format_number(value, digits) == expected


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (275, "4 dk 35 sn"),
        (45, "45 sn"),
        (3600, "1 sa 0 dk"),
        (4000, "1 sa 6 dk"),
        (-90, "-1 dk 30 sn"),
        (None, "—"),
    ],
)
def test_format_duration_speaks_call_centre(seconds, expected):
    assert format_duration(seconds) == expected


def test_format_value_respects_the_unit():
    assert format_value(84.2, "%") == "%84,2"
    assert format_value(275, "sn") == "4 dk 35 sn"
    assert format_value(1250.5, "₺") == "1.250,5 ₺"
    assert format_value(58, "") == "58"
    assert format_value(None, "%") == "—"
    assert format_value(float("nan"), "") == "—"


# --- picking the right aggregate --------------------------------------------


def test_default_agg_never_sums_a_rate(call_centre):
    """Summing SLA is nonsense; averaging call volume hides the volume."""
    assert default_agg(call_centre.column("SLA %")) == "mean"
    assert default_agg(call_centre.column("Doluluk %")) == "mean"
    assert default_agg(call_centre.column("AHT")) == "mean"
    assert default_agg(call_centre.column("Memnuniyet")) == "mean"
    assert default_agg(call_centre.column("Çağrı Adedi")) == "sum"
    assert default_agg(call_centre.column("Cevaplanan")) == "sum"
    assert default_agg(call_centre.column("Terk Edilen")) == "sum"


def test_measure_for_labels_itself_in_turkish(call_centre):
    measure = measure_for(call_centre.column("AHT"), weight="Çağrı Adedi")
    assert measure.agg == "mean"
    assert measure.label == "Ortalama Görüşme Süresi (AHT) (ortalama)"
    assert measure.unit == "sn"
    assert measure.weight == "Çağrı Adedi"

    volume = measure_for(call_centre.column("Çağrı Adedi"), weight="Çağrı Adedi")
    # A sum is never weighted — that would double-count.
    assert volume.agg == "sum"
    assert volume.weight == ""


# --- group_by / pivot arithmetic ---------------------------------------------


def test_group_by_sums_and_totals_exactly():
    table = group_by(_shifts(), ["Vardiya"], [Measure("Çağrı Adedi", "sum")])
    by_shift = {row["Vardiya"]: row["çağrı_adedi_sum"] for row in table.rows}
    assert by_shift == {"Sabah": 40.0, "Akşam": 60.0}
    assert table.totals["çağrı_adedi_sum"] == 100.0
    assert table.totals["Vardiya"] == "TOPLAM"
    # Sorted by the first measure, descending: Akşam (60) leads Sabah (40).
    assert [row["Vardiya"] for row in table.rows] == ["Akşam", "Sabah"]


def test_group_by_computes_mean_median_min_max_and_count():
    data = profile_table(
        ["G", "V"],
        [["A", "1"], ["A", "2"], ["A", "6"], ["B", "10"], ["B", "20"]],
    )
    table = group_by(
        data,
        ["G"],
        [
            Measure("V", "mean"),
            Measure("V", "median"),
            Measure("V", "min"),
            Measure("V", "max"),
            Measure("V", "count"),
        ],
        sort_key="v_mean",
        descending=False,
    )
    rows = {row["G"]: row for row in table.rows}
    assert rows["A"]["v_mean"] == pytest.approx(3.0)  # (1+2+6)/3
    assert rows["A"]["v_median"] == pytest.approx(2.0)
    assert rows["A"]["v_min"] == pytest.approx(1.0)
    assert rows["A"]["v_max"] == pytest.approx(6.0)
    assert rows["A"]["v_count"] == 3.0
    assert rows["B"]["v_mean"] == pytest.approx(15.0)
    assert rows["B"]["v_count"] == 2.0
    # Ascending sort on the mean: A (3) before B (15).
    assert [row["G"] for row in table.rows] == ["A", "B"]
    # The total row is the whole column, not the sum of the group means.
    assert table.totals["v_mean"] == pytest.approx(39 / 5)


def test_weighted_mean_is_not_the_average_of_averages():
    """The classic call-centre trap.

    Two agents: one handled 10 calls at 100 s, the other 90 calls at 200 s.
    The plain average is 150 s. The truth, weighted by volume, is
    (10·100 + 90·200) / 100 = 190 s. A report that says 150 is wrong.
    """
    data = profile_table(
        ["Temsilci", "Çağrı Adedi", "AHT"],
        [["Ayşe", "10", "100"], ["Mehmet", "90", "200"]],
    )
    plain = group_by(data, ["Temsilci"], [Measure("AHT", "mean")])
    assert plain.totals["aht_mean"] == pytest.approx(150.0)

    weighted = group_by(
        data, ["Temsilci"], [Measure("AHT", "mean", weight="Çağrı Adedi")]
    )
    assert weighted.totals["aht_mean"] == pytest.approx(190.0)
    # Inside a single-row group the weight cannot change anything.
    per_agent = {row["Temsilci"]: row["aht_mean"] for row in weighted.rows}
    assert per_agent == {"Ayşe": pytest.approx(100.0), "Mehmet": pytest.approx(200.0)}


def test_group_by_two_dimensions_makes_one_row_per_combination():
    data = profile_table(
        ["Vardiya", "Kuyruk", "Çağrı Adedi"],
        [
            ["Sabah", "Teknik", "10"],
            ["Sabah", "Fatura", "20"],
            ["Akşam", "Teknik", "30"],
            ["Sabah", "Teknik", "40"],
        ],
    )
    table = group_by(data, ["Vardiya", "Kuyruk"], [Measure("Çağrı Adedi", "sum")])
    cells = {
        (row["Vardiya"], row["Kuyruk"]): row["çağrı_adedi_sum"] for row in table.rows
    }
    assert cells == {
        ("Sabah", "Teknik"): 50.0,
        ("Sabah", "Fatura"): 20.0,
        ("Akşam", "Teknik"): 30.0,
    }
    assert table.totals["çağrı_adedi_sum"] == 100.0


def test_group_by_truncates_and_says_so():
    data = profile_table(["Kod", "V"], [[f"K{i:03d}", str(i)] for i in range(30)])
    table = group_by(data, ["Kod"], [Measure("V", "sum")], limit=5)
    assert len(table.rows) == 5
    assert table.truncated == 25
    assert "ilk 5" in table.note
    # The total is still computed over ALL 30 groups, not the shown 5.
    assert table.totals["v_sum"] == pytest.approx(sum(range(30)))


def test_group_by_on_the_fixture_matches_the_source_file(call_centre):
    table = group_by(call_centre, ["Kuyruk"], [Measure("Çağrı Adedi", "sum")])
    by_queue = {row["Kuyruk"]: row["çağrı_adedi_sum"] for row in table.rows}
    assert by_queue == {"Faturalama": 5356.0, "Teknik Destek": 5026.0}
    assert table.totals["çağrı_adedi_sum"] == 10382.0


def test_group_by_returns_an_empty_but_valid_table_when_it_cannot_group():
    data = profile_table(["V"], [["1"], ["2"]])
    table = group_by(data, ["YokBöyleSütun"], [Measure("V", "sum")])
    assert table.rows == []
    assert table.dimensions == []
    assert "bulunamadı" in table.note


def test_pivot_display_rows_are_formatted_in_turkish():
    table = group_by(_shifts(), ["Vardiya"], [Measure("SLA %", "mean", unit="%")])
    shown = {row["Vardiya"]: row["sla_mean"] for row in table.display_rows()}
    assert shown == {"Sabah": "%70,0", "Akşam": "%80,0"}


def test_pivot_column_specs_describe_a_sortable_table():
    table = group_by(_shifts(), ["Vardiya"], [Measure("SLA %", "mean", unit="%")])
    specs = table.column_specs()
    assert specs[0] == {"key": "Vardiya", "label": "Vardiya", "type": "text"}
    assert specs[1]["key"] == "sla_mean"
    assert specs[1]["type"] == "num"
    assert table.column_keys == ["Vardiya", "sla_mean"]


# --- time series -------------------------------------------------------------


def _six_days():
    return profile_table(
        ["Tarih", "Değer"],
        [
            [f"0{day}.01.2026", str(value)]
            for day, value in zip(range(1, 7), [10, 20, 30, 40, 50, 60])
        ],
    )


def test_time_series_deltas_and_moving_average_are_exact():
    series = time_series(_six_days(), "Tarih", "Değer", agg="sum", period="gün")
    assert [point.value for point in series.points] == [10, 20, 30, 40, 50, 60]
    assert [point.label for point in series.points][0] == "01.01.2026"
    # Period-over-period difference: the first point has no predecessor.
    assert [point.delta for point in series.points] == [None, 10, 10, 10, 10, 10]
    assert series.points[1].delta_pct == pytest.approx(100.0)  # 10 → 20
    assert series.points[5].delta_pct == pytest.approx(20.0)  # 50 → 60
    # 3-period moving average, growing into its window.
    assert [point.moving for point in series.points] == [10, 15, 20, 30, 40, 50]


def test_time_series_trend_compares_the_two_halves():
    series = time_series(_six_days(), "Tarih", "Değer", agg="sum", period="gün")
    # First half mean 20, second half mean 50 → +150%.
    assert series.trend == "up"
    assert series.change_pct == pytest.approx(150.0)


def test_time_series_buckets_rows_that_share_a_period():
    data = profile_table(
        ["Tarih", "Değer"],
        [
            ["01.01.2026", "10"],
            ["01.01.2026", "5"],
            ["02.01.2026", "20"],
            ["02.01.2026", "1"],
        ],
    )
    summed = time_series(data, "Tarih", "Değer", agg="sum", period="gün")
    assert [point.value for point in summed.points] == [15, 21]

    averaged = time_series(data, "Tarih", "Değer", agg="mean", period="gün")
    assert [point.value for point in averaged.points] == [7.5, 10.5]


def test_time_series_can_bucket_by_week_and_month():
    data = profile_table(
        ["Tarih", "Değer"],
        [
            ["05.01.2026", "1"],  # Monday
            ["07.01.2026", "2"],  # same week
            ["12.01.2026", "4"],  # next week
            ["03.02.2026", "8"],
        ],
    )
    weekly = time_series(data, "Tarih", "Değer", agg="sum", period="hafta")
    assert [point.value for point in weekly.points] == [3, 4, 8]
    assert weekly.points[0].label == "05.01.2026 haftası"

    monthly = time_series(data, "Tarih", "Değer", agg="sum", period="ay")
    assert [point.value for point in monthly.points] == [7, 8]


def test_time_series_keeps_only_the_last_periods_and_says_so():
    data = profile_table(
        ["Tarih", "Değer"],
        [[f"{day:02d}.01.2026", str(day)] for day in range(1, 21)],
    )
    series = time_series(data, "Tarih", "Değer", agg="sum", period="gün", limit=5)
    assert [point.value for point in series.points] == [16, 17, 18, 19, 20]
    assert "son 5" in series.note


def test_time_series_explains_itself_when_it_cannot_run():
    data = profile_table(["Ad", "Değer"], [["a", "1"], ["b", "2"]])
    no_date = time_series(data, "Ad", "Değer")
    assert no_date.points == []
    assert "tarih sütunu bulunamadı" in no_date.note.casefold()

    no_measure = time_series(_six_days(), "Tarih", "Tarih")
    assert no_measure.points == []
    assert "sayısal" in no_measure.note


# --- outliers ----------------------------------------------------------------


def test_iqr_outlier_band_is_computed_exactly():
    """Sorted: 10..16 then 100. Q1 = 11,75, Q3 = 15,25, IQR = 3,5.

    Band = [11,75 − 1,5·3,5 ; 15,25 + 1,5·3,5] = [6,5 ; 20,5]. Only 100 is out.
    """
    data = profile_table(
        ["Satır", "X"],
        [[f"r{i}", str(v)] for i, v in enumerate([10, 11, 12, 13, 14, 15, 16, 100])],
    )
    report = find_outliers(data, "X", context_column="Satır")
    assert report.q1 == pytest.approx(11.75)
    assert report.q3 == pytest.approx(15.25)
    assert report.iqr == pytest.approx(3.5)
    assert report.lower == pytest.approx(6.5)
    assert report.upper == pytest.approx(20.5)
    assert report.total == 8
    assert report.count == 1
    assert report.rate == pytest.approx(1 / 8)
    assert [(o.value, o.side, o.context) for o in report.examples] == [
        (100.0, "üst", "r7")
    ]
    assert "1 aykırı ölçüm" in report.interpretation


def test_outliers_finds_the_low_side_too():
    values = [100, 101, 102, 103, 104, 105, 106, 1]
    data = profile_table(["X"], [[str(v)] for v in values])
    report = find_outliers(data, "X")
    assert report.count == 1
    assert report.examples[0].side == "alt"
    assert report.examples[0].value == pytest.approx(1.0)


def test_a_balanced_column_reports_no_outliers_and_says_so():
    data = profile_table(["X"], [[str(v)] for v in [10, 11, 12, 13, 14, 15, 16, 17]])
    report = find_outliers(data, "X")
    assert report.count == 0
    assert report.examples == []
    assert "dengeli" in report.interpretation


def test_outliers_refuses_a_sample_that_is_too_small():
    data = profile_table(["X"], [[str(v)] for v in [1, 2, 3, 900]])
    report = find_outliers(data, "X")
    assert report.count == 0
    assert report.total == 4
    assert "en az 8 ölçüm" in report.interpretation


def test_outliers_refuses_a_column_that_is_not_numeric():
    data = profile_table(["Ad"], [["a"], ["b"], ["c"]])
    report = find_outliers(data, "Ad")
    assert report.count == 0
    assert "sayısal bir sütun olmadığı için" in report.interpretation


# --- correlation -------------------------------------------------------------


def test_pearson_recognises_the_textbook_cases():
    assert pearson([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) == pytest.approx(1.0)
    assert pearson([1, 2, 3, 4, 5], [10, 8, 6, 4, 2]) == pytest.approx(-1.0)
    assert pearson([1, 2, 3, 4], [1, 1, 1, 1]) is None  # no variance
    assert pearson([1, 2], [3, 4]) is None  # too few pairs


def test_pearson_matches_a_hand_computed_value():
    # x = [1,2,3,4] (mean 2,5), y = [2,4,5,4] (mean 3,75).
    #   cov   = (-1,5)(-1,75) + (-0,5)(0,25) + (0,5)(1,25) + (1,5)(0,25) = 3,5
    #   var_x = 2,25 + 0,25 + 0,25 + 2,25                                = 5
    #   var_y = 3,0625 + 0,0625 + 1,5625 + 0,0625                        = 4,75
    #   r     = 3,5 / √(5 · 4,75) = 3,5 / 4,8734 = 0,71818…
    assert pearson([1, 2, 3, 4], [2, 4, 5, 4]) == pytest.approx(
        3.5 / math.sqrt(5 * 4.75)
    )
    assert pearson([1, 2, 3, 4], [2, 4, 5, 4]) == pytest.approx(0.7182, abs=1e-4)


def test_correlations_reports_only_meaningful_pairs_with_turkish_wording():
    data = profile_table(
        ["A", "B", "C"],
        [[str(i), str(2 * i), str((i * 7919) % 11)] for i in range(1, 15)],
    )
    found = correlations(data, threshold=0.9)
    assert [(c.left, c.right) for c in found] == [("A", "B")]
    item = found[0]
    assert item.r == pytest.approx(1.0)
    assert item.strength == "çok güçlü"
    assert "birlikte artıyor" in item.interpretation
    assert item.pairs == 14


def test_correlations_on_the_fixture_find_the_real_relationships(call_centre):
    found = {(c.left, c.right): c.r for c in correlations(call_centre)}
    # Calls and answered calls move together almost perfectly.
    assert found[("Çağrı Adedi", "Cevaplanan")] > 0.95
    # Longer waits mean lower service level — a NEGATIVE relationship.
    assert found[("Bekleme Süresi (sn)", "SLA %")] < -0.9


# --- filters -----------------------------------------------------------------


@pytest.mark.parametrize(
    "op, value, kept",
    [
        ("=", "Sabah", 2),
        ("!=", "Sabah", 2),
        ("in", ["Sabah", "Akşam"], 4),
        ("contains", "şam", 2),
    ],
)
def test_filters_select_rows(op, value, kept):
    data = _shifts()
    request = AnalysisRequest(filters=[Filter("Vardiya", op, value)])
    filtered, notes = apply_request_filters(data, request)
    assert filtered.row_count == kept


def test_filters_ignore_turkish_case_on_text():
    data = _shifts()
    filtered, _ = apply_request_filters(
        data, AnalysisRequest(filters=[Filter("Vardiya", "=", "sabah")])
    )
    assert filtered.row_count == 2


def test_numeric_and_between_filters_compare_by_type():
    data = _shifts()
    above, _ = apply_request_filters(
        data, AnalysisRequest(filters=[Filter("Çağrı Adedi", ">", 25)])
    )
    assert above.row_count == 2

    band, _ = apply_request_filters(
        data, AnalysisRequest(filters=[Filter("Çağrı Adedi", "between", (15, 35))])
    )
    assert band.row_count == 2


def test_last_days_counts_back_from_the_data_not_from_today(call_centre):
    """The file ends 14.07.2026. "Last 7 days" must mean 07–14.07, not today."""
    filtered, notes = apply_request_filters(call_centre, AnalysisRequest(last_days=7))
    assert filtered.row_count == 64
    assert filtered.column("Tarih").first == datetime(2026, 7, 7)
    assert any("Süzgeç uygulandı" in note for note in notes)


def test_a_filter_that_matches_nothing_returns_the_unfiltered_data_with_a_note():
    """An empty report is worse than a mistyped shift name."""
    data = _shifts()
    filtered, notes = apply_request_filters(
        data, AnalysisRequest(filters=[Filter("Vardiya", "=", "Gece Yarısı")])
    )
    assert filtered.row_count == 4
    assert any("hiçbir satır bırakmadı" in note for note in notes)
    assert any("Gece Yarısı" in note for note in notes)


def test_an_unknown_filter_column_is_skipped_with_a_note():
    filtered, notes = apply_request_filters(
        _shifts(), AnalysisRequest(filters=[Filter("YokBöyle", "=", "x")])
    )
    assert filtered.row_count == 4
    assert any("tanınmayan sütun" in note for note in notes)


def test_resolve_columns_accepts_names_metric_keys_and_fragments(call_centre):
    found = resolve_columns(call_centre, ["SLA %", "aht", "terk", "yok böyle"])
    assert [c.name for c in found] == ["SLA %", "AHT", "Terk Edilen"]


def test_request_summary_and_window_label_are_turkish():
    request = AnalysisRequest(
        dimensions=["Vardiya"], metrics=["sla"], period="hafta", last_days=90
    )
    summary = request.summary_tr()
    assert "Göstergeler: sla" in summary
    assert "Kırılım: Vardiya" in summary
    assert "Dönem: hafta bazında" in summary
    assert request.window_label() == "Son 3 ay"
    assert AnalysisRequest(last_days=14).window_label() == "Son 2 hafta"
    assert AnalysisRequest(last_days=5).window_label() == "Son 5 gün"


# --- findings ----------------------------------------------------------------


def test_make_finding_computes_the_delta_and_picks_a_tone():
    good = make_finding("SLA", 85.0, unit="%", baseline=80.0, better="up")
    assert good.delta == pytest.approx(5.0)
    assert good.delta_pct == pytest.approx(6.25)
    assert good.direction == "up"
    assert good.tone == TONE_GOOD
    assert good.display == "%85,0"

    bad = make_finding("Terk", 8.0, unit="%", baseline=5.0, better="down")
    assert bad.direction == "up"
    assert bad.tone == TONE_WARN
    assert "istenmeyen yönde" in bad.interpretation

    neutral = make_finding("Hacim", 100.0)
    assert neutral.tone == TONE_INFO
    assert neutral.direction == "flat"


def test_call_centre_kpis_are_derived_from_the_real_columns(call_centre):
    findings = {f.key: f for f in call_center_kpis(call_centre, sla_target=80.0)}
    assert set(findings) >= {
        "calls_total",
        "sla",
        "abandon_rate",
        "aht",
        "occupancy",
        "csat",
        "asa",
    }

    assert findings["calls_total"].value == pytest.approx(10382.0)
    # Abandon rate is derived, not read: 511 / 10382 = 4,92 %.
    assert findings["abandon_rate"].value == pytest.approx(511 / 10382 * 100)
    assert findings["abandon_rate"].tone == TONE_GOOD
    assert "%5" in findings["abandon_rate"].interpretation
    # SLA is call-weighted, so it is not the plain column mean.
    assert findings["sla"].value == pytest.approx(84.36, abs=0.5)
    assert findings["sla"].tone == TONE_GOOD
    assert "hedef" in findings["sla"].interpretation.casefold()


def test_sla_below_target_is_flagged_as_a_problem():
    data = profile_table(
        ["Çağrı Adedi", "SLA %"],
        [["100", "%60"], ["100", "%62"], ["100", "%58"]],
    )
    findings = {f.key: f for f in call_center_kpis(data, sla_target=80.0)}
    sla = findings["sla"]
    assert sla.value == pytest.approx(60.0)
    assert sla.tone == TONE_BAD  # more than 5 points below target
    assert "altında" in sla.interpretation


def test_kpis_are_not_invented_when_the_columns_are_missing():
    data = profile_table(["Çağrı Adedi"], [["10"], ["20"], ["30"]])
    keys = {f.key for f in call_center_kpis(data)}
    assert keys == {"calls_total"}


# --- analyze() end to end ----------------------------------------------------


def test_analyze_picks_sensible_defaults_for_call_centre_data(call_centre):
    result = analyze(call_centre, now=datetime(2026, 8, 1, 9, 0))
    assert result.is_call_center is True
    assert result.generated_at == "2026-08-01T09:00:00"
    assert result.title.endswith("Veri Analizi")
    assert result.headline

    # The three natural axes, plus one cross-tab.
    titles = [p.title for p in result.pivots]
    assert "Temsilci kırılımı" in titles
    assert "Kuyruk kırılımı" in titles
    assert "Vardiya kırılımı" in titles

    assert result.series, "a dated call-centre file must produce a trend"
    assert all(len(s.values) >= 2 for s in result.series)
    assert result.findings
    assert result.correlations

    payload = result.as_dict()
    assert payload["profile"]["row_count"] == 112
    assert payload["is_call_center"] is True


def test_analyze_honours_an_explicit_request(call_centre):
    request = AnalysisRequest(
        dimensions=["Vardiya"],
        metrics=["sla", "abandon"],
        period="hafta",
        last_days=7,
        include=["pivot", "kpi"],
        title="Haftalık SLA",
    )
    result = analyze(call_centre, request)
    assert result.title == "Haftalık SLA"
    assert [p.title for p in result.pivots] == ["Vardiya kırılımı"]
    assert [m.column for m in result.pivots[0].measures] == ["SLA %", "Terk Edilen"]
    # include= excluded them.
    assert result.series == []
    assert result.outliers == []
    assert result.correlations == []
    assert result.dataset.row_count == 64


def test_analyze_notes_what_it_could_not_find(call_centre):
    result = analyze(
        call_centre,
        AnalysisRequest(dimensions=["Şube"], metrics=["nps"]),
    )
    assert any("bulunamayan gösterge" in note for note in result.notes)
    assert any("bulunamayan kırılım" in note for note in result.notes)
    # …and it still produced a report from the columns that DO exist.
    assert result.pivots


def test_key_findings_put_the_problems_first():
    data = profile_table(
        ["Çağrı Adedi", "SLA %", "Terk Edilen"],
        [["100", "%50", "30"], ["100", "%52", "28"], ["100", "%48", "31"]],
    )
    result = analyze(data)
    top = result.key_findings(2)
    assert top[0].tone in (TONE_BAD, TONE_WARN)
    assert result.headline == top[0].interpretation


# --- graceful degradation ----------------------------------------------------


def test_a_single_numeric_column_still_yields_a_valid_result():
    data = profile_table(["Tek"], [[str(i)] for i in range(1, 11)])
    result = analyze(data)
    assert result.pivots == []
    assert result.series == []
    assert result.findings, "even one column deserves a headline figure"
    assert result.findings[0].value == pytest.approx(55.0)
    assert any("zaman serisi üretilemedi" in note for note in result.notes)
    assert result.headline


def test_all_text_data_degrades_to_a_distribution_note():
    data = profile_table(
        ["Şehir", "Not"],
        [["İstanbul", "iyi"], ["Ankara", "kötü"], ["İstanbul", "iyi"]],
    )
    result = analyze(data)
    assert result.is_call_center is False
    assert any("sayısal sütun yok" in note for note in result.notes)
    assert result.findings
    assert "en sık görülen değer" in result.findings[0].interpretation
    assert result.headline


def test_three_rows_do_not_break_anything():
    data = profile_table(
        ["Tarih", "V"], [["01.01.2026", "1"], ["02.01.2026", "2"], ["03.01.2026", "3"]]
    )
    result = analyze(data)
    assert result.outliers == []  # too few measurements for IQR
    assert result.headline


def test_a_dimension_only_table_produces_a_result_without_raising():
    data = profile_table(["Vardiya"], [["Sabah"], ["Akşam"], ["Sabah"]])
    result = analyze(data)
    assert result.headline
    assert result.as_dict()["profile"]["column_count"] == 1


def test_analyze_never_divides_by_zero_on_constant_data():
    data = profile_table(["Tarih", "V"], [[f"0{d}.01.2026", "0"] for d in range(1, 8)])
    result = analyze(data)
    for series in result.series:
        assert series.change_pct is None or math.isfinite(series.change_pct)
    assert result.headline
