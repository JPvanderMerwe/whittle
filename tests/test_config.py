"""
Config loads, validates, and refuses to hand back a number it does not have.
"""

from pathlib import Path

import pytest

from whittle.config import (
    Config,
    ConfigError,
    UnsetConfigError,
    format_config,
    load_config,
)

CONFIG = Path(__file__).resolve().parent.parent / "config" / "default.toml"


@pytest.fixture
def cfg() -> Config:
    return load_config(CONFIG)


def test_config_loads(cfg):
    assert cfg.path == CONFIG


def test_print_settings_present(cfg):
    assert cfg.print_settings["nozzle_mm"] == 0.40
    assert cfg.print_settings["layer_mm"] == 0.20


def test_limits_present(cfg):
    limits = cfg.limits
    assert limits["min_feature_multiple"] == 1.0
    assert limits["min_engrave_stroke_mm"] == 0.45
    assert limits["min_pin_mm"] == 2.40
    assert limits["max_overhang_deg"] == 45.0
    assert limits["max_bridge_gap_mm"] == 0.50


def test_export_tolerances_are_the_ones_that_stay_watertight(cfg):
    assert cfg.export["stl_tolerance"] == 0.005
    assert cfg.export["stl_angular_tolerance"] == 0.05


def test_the_stocked_materials_are_configured(cfg):
    """
    The list is the shop's stock, so it GROWS - and this used to pin it.

    It read `== ["petg", "pla", "tpu"]`, which is a snapshot rather than a rule.
    The day the rest of the shop's catalogue went into the config the test
    failed while nothing was wrong: an exact list against something people add
    to is a test that reports restocking as a regression.

    What is actually load-bearing is that the three whittle has always built
    with are still there. Anything else is inventory.
    """
    for name in ("petg", "pla", "tpu"):
        assert name in cfg.material_names, "%s is no longer configured" % name
    assert cfg.material_names == sorted(cfg.material_names), (
        "material_names is documented as sorted, and clients rely on it"
    )


def test_no_material_is_half_measured(cfg):
    """
    A material has BOTH of its numbers or NEITHER. Rule 29, applied to the
    thing rule 29 is about.

    The two are measured together - print a test fit, measure the gap that
    turns freely, measure what the part came out at - so a material with a
    clearance and an UNSET shrink is not a partially-filled row, it is a number
    somebody guessed and a number they did not. That is the exact shape of
    mistake this catches, and it is invisible in the file: both lines look
    equally deliberate.
    """
    unset = set(cfg.unset_fields())
    for name in cfg.material_names:
        missing = {
            field for field in ("clearance_mm", "shrink_pct")
            if "materials.%s.%s" % (name, field) in unset
        }
        assert missing in (set(), {"clearance_mm", "shrink_pct"}), (
            "%s has %s measured and %s UNSET. Measure both or neither - a "
            "clearance without the shrink it was measured at is a fit that "
            "works on one printer."
            % (name, sorted({"clearance_mm", "shrink_pct"} - missing), sorted(missing))
        )


def test_harvested_material_numbers_are_readable(cfg):
    """
    PLA and PETG carry clearances harvested from reference parts that printed
    and worked, so reading them succeeds.
    """
    assert cfg.material("petg")["clearance_mm"] == 0.30    # PIVOT_CLEAR / PIN_CLEAR
    assert cfg.material("pla")["clearance_mm"] == 0.20     # REGISTER_CLEAR
    for name in ("pla", "petg"):
        assert cfg.material(name)["shrink_pct"] == 0.0


def test_unset_material_raises_and_names_the_field(cfg):
    """
    whittle must never substitute a plausible-looking tolerance. TPU is flexible,
    no reference part uses it, and a clearance guessed for a flexible material
    is worse than none.
    """
    with pytest.raises(UnsetConfigError) as exc:
        cfg.material("tpu")
    message = str(exc.value)
    assert "clearance_mm" in message
    assert "shrink_pct" in message
    assert str(CONFIG) in message


def test_unknown_material_raises(cfg):
    with pytest.raises(ConfigError):
        cfg.material("nylon")


def test_both_machine_profiles_are_configured(cfg):
    assert cfg.machine_names == ["desktop", "laptop"]


def test_machine_hosts_are_loopback(cfg):
    from whittle.models.base import assert_local_endpoint

    for name in cfg.machine_names:
        assert_local_endpoint(
            cfg.machine(name)["host"], allowed_hosts=cfg.allowed_model_hosts
        )


def test_no_tailscale_host_is_whitelisted(cfg):
    assert cfg.allowed_model_hosts == []


def test_machine_profile_shapes(cfg):
    desktop = cfg.machine("desktop")
    laptop = cfg.machine("laptop")
    assert desktop["backend"] == laptop["backend"] == "ollama"
    # The laptop is slower, so it gets longer to answer and fewer attempts.
    assert laptop["timeout_s"] > desktop["timeout_s"]
    assert laptop["max_attempts_per_level"] < desktop["max_attempts_per_level"]
    assert laptop["num_ctx"] < desktop["num_ctx"]


def test_no_model_tag_is_pinned_before_it_is_benchmarked(cfg):
    """
    A tag may be set ONLY on a machine whose measurements are recorded in the
    config beside it. The laptop was benchmarked on 2026-08-27 (100% CPU, three
    models timed) so it is pinned; the desktop has not been touched yet, so it
    must still be UNSET.
    """
    text = CONFIG.read_text()
    for name in cfg.machine_names:
        table = cfg.machine(name)
        pinned = table["model_primary"] != "UNSET"
        section = text.split("[machines.%s]" % name, 1)[1].split("[machines.", 1)[0]
        has_measurements = "MEASURED" in section
        assert pinned == has_measurements, (
            "machine %r: model_primary is %s but the config %s measurements "
            "beside it. Benchmark it with `whittle models bench` and record the "
            "numbers, or set it back to UNSET."
            % (name, "pinned" if pinned else "UNSET",
               "has" if has_measurements else "has no")
        )


def test_the_desktop_is_still_unbenchmarked(cfg):
    """8 GB VRAM, and nothing has been run on it. Nothing may be pinned."""
    assert cfg.machine("desktop")["model_primary"] == "UNSET"


def test_unset_fields_are_listed(cfg):
    """
    Everything with no measured source behind it, named.

    THE COUNT IS DERIVED, NOT WRITTEN DOWN. This asserted `len(unset) == 4`
    with "# TPU x 2, desktop x 2" beside it, and the arithmetic was correct on
    the day it was written - which is the problem. Stocking four more materials
    nobody has run a fit test in is not a regression, it is the honest state of
    a shelf, and the test called it one.

    So the expected number is worked out from the same rule the comment
    described: two fields per unmeasured material, plus the two on an
    unbenchmarked machine. A material that is HALF unset breaks
    test_no_material_is_half_measured rather than quietly changing this total.
    """
    unset = cfg.unset_fields()

    # The ones that are measured stay out of the list, and the ones that are
    # not stay in it. These four are the named cases the rest is derived from.
    assert "materials.tpu.clearance_mm" in unset
    assert "materials.pla.clearance_mm" not in unset
    assert "machines.desktop.model_primary" in unset
    assert "machines.laptop.model_primary" not in unset   # benchmarked and pinned

    materials = sum(
        1 for name in cfg.material_names
        if "materials.%s.clearance_mm" % name in unset
    )
    machines = sum(
        1 for name in cfg.machine_names
        if "machines.%s.model_primary" % name in unset
    )
    assert len(unset) == 2 * materials + 2 * machines, (
        "unset_fields() lists %d entries; %d unmeasured materials and %d "
        "unbenchmarked machines account for %d. Something is unset that this "
        "rule does not describe - look at it rather than at the number."
        % (len(unset), materials, machines, 2 * materials + 2 * machines)
    )


def test_format_config_flags_every_unset_value(cfg):
    text = format_config(cfg)
    assert "UNSET" in text
    assert "supply before use" in text
    for field in cfg.unset_fields():
        assert field in text


def test_missing_config_file_raises_with_the_path(tmp_path):
    missing = tmp_path / "nope.toml"
    with pytest.raises(ConfigError) as exc:
        load_config(missing)
    assert str(missing) in str(exc.value)
