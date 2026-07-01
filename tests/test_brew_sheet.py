"""Tests for the brew-sheet generator: measured data vs. templated recipe."""

from __future__ import annotations

import pytest

from goodcup.analysis import descriptors as D
from goodcup.knowledge import brew_sheet as B

from conftest import make_cupping, make_green, make_roast


def test_infer_roast_level_is_honest_about_basis():
    label, basis = B.infer_roast_level(203.0)
    assert label == "Light"
    assert "203" in basis
    assert B.infer_roast_level(None) == ("Unspecified", "no drop temperature recorded")


def test_brew_sheet_uses_measured_flavor_notes_and_sensory(conn):
    g = make_green(conn, lot_name="Yirgacheffe Test", process="washed")
    for i in range(3):
        r = make_roast(conn, g, drop_temp=206.0)
        make_cupping(conn, r, session_id=f"S{i}", total_score=85.0, acidity=7.0, body=6.5,
                     sweetness=7.2, descriptors_raw="jasmine, lemon, honey")
    D.rebuild_descriptors(conn)

    sheet = B.build_brew_sheet(conn, g, method="Hario V60-02")
    assert sheet["lot_name"] == "Yirgacheffe Test"
    assert sheet["n_cuppings"] == 3
    assert sheet["sensory"]["acidity"] == 7.0
    assert sheet["sensory"]["n"] == 3
    # flavour notes are drawn from the mapped descriptors, not invented
    assert any(note in {"jasmine", "lemon", "honey"} for note in sheet["flavor_notes"])
    # recipe is the template starting point, clearly separate from measured data
    assert sheet["recipe"]["dose_g"] == 12
    assert sheet["recipe"]["water_g"] == 192


def test_brew_sheet_without_cuppings_does_not_invent_notes(conn):
    g = make_green(conn, lot_name="Unscored Lot")
    make_roast(conn, g, drop_temp=208.0)
    sheet = B.build_brew_sheet(conn, g)
    assert sheet["n_cuppings"] == 0
    assert sheet["sensory"] is None
    assert sheet["flavor_notes"] == []
    # renderer says so rather than fabricating
    html = B.render_brew_sheet_html(sheet)
    assert "No cuppings recorded" in html


def test_render_marks_recipe_as_a_starting_point(conn):
    g = make_green(conn, lot_name="L")
    make_roast(conn, g, drop_temp=206.0)
    html = B.render_brew_sheet_html(B.build_brew_sheet(conn, g))
    assert "starting point" in html.lower()
    assert "not a measured value" in html.lower()


def test_unknown_method_is_rejected(conn):
    g = make_green(conn)
    make_roast(conn, g)
    with pytest.raises(ValueError):
        B.build_brew_sheet(conn, g, method="French Press XL")
