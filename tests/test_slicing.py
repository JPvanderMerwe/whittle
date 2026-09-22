"""
Time and filament, from a slicer, or not at all.

THE WHOLE POINT OF THESE TESTS is that the absent case is as correct as the
present one. No slicer is installed on the machine this was written on, and
the honest behaviour with none - everything else about the print still
reported, this part saying plainly what it needs - has to be as well
defined as the behaviour with one.
"""

from __future__ import annotations

from whittle import slicing

# A PRUSASLICER G-CODE HEADER, as the slicer writes it. Kept as a fixture
# rather than generated: the format is the contract between whittle and a
# program it does not control, and a fixture is the only way to test a
# parser against a shape without owning the thing that produces it.
#
# CONFIRM THIS AGAINST A REAL RUN when a slicer is installed. It is written
# from PrusaSlicer's documented comment format; if a build writes something
# different, `read_estimates` returns nothing rather than a wrong number,
# which is the failure mode this was designed for.
PRUSA_TAIL = """
G1 X10 Y10 E1.0
; filament used [mm] = 1626.28
; filament used [cm3] = 3.91
; filament used [g] = 4.97
; total filament used [g] = 4.97
; total filament used for wipe tower [g] = 0.00
; filament cost = 0.07
; estimated printing time (normal mode) = 32m 52s
; prusaslicer_config = begin
"""

#: The same slice with no density in the filament profile, which is the
#: STOCK CONFIGURATION - `filament_density = 0`. Kept because it is the
#: default state of a fresh install and the one that produced a zero.
PRUSA_TAIL_NO_DENSITY = """
; filament used [mm] = 1626.28
; filament used [cm3] = 3.91
; total filament used [g] = 0.00
; total filament used for wipe tower [g] = 0.00
; estimated printing time (normal mode) = 32m 52s
"""


def test_it_reads_what_the_slicer_said():
    """
    THE FIXTURE IS A REAL SLICE. PrusaSlicer 2.7.2 over parts/a_hinge:
    1626.28 mm, 3.91 cm3, 4.97 g at 1.27 g/cm3, 32m 52s. Written from the
    file rather than from memory of the format - the first version of this
    test guessed a "total layer count" line that PrusaSlicer does not write,
    and a grams figure it only writes when a density is configured.
    """
    read = slicing.read_estimates(PRUSA_TAIL)
    assert read.ok
    assert read.seconds == 32 * 60 + 52
    assert read.grams == 4.97
    assert read.filament_mm == 1626.28
    assert read.filament_cm3 == 3.91
    # EVERY FIGURE CITES THE LINE IT CAME FROM, so a number on a screen can
    # be chased back into the file the slicer wrote.
    assert len(read.evidence) >= 4


def test_a_zero_weight_is_a_missing_profile_and_not_a_measurement():
    """
    THIS ONE WAS FOUND BY RUNNING IT.

    PrusaSlicer's stock filament profile carries `filament_density = 0`, so
    a real slice of a real hinge reported "total filament used [g] = 0.00".
    The parser accepted it, and the answer was a part weighing nothing -
    a figure somebody would load a spool against.

    No print uses no filament and no print takes no time, so a zero here
    means "not known". The time and the volume are still reported, because
    the slicer does know those.
    """
    read = slicing.read_estimates(PRUSA_TAIL_NO_DENSITY)
    assert read.ok, "a slice with no density still knows its time and volume"
    assert read.grams is None, "0.00 g was reported as the weight of a part"
    assert read.filament_cm3 == 3.91
    assert read.seconds == 32 * 60 + 52


def test_it_derives_nothing():
    """
    THE RULE THAT MATTERS HERE.

    Grams must not be computed from millimetres and a density, and time must
    not be computed from length and a speed. Both look like the slicer's
    figures and are this program's, and somebody loading a spool is acting
    on them.
    """
    only_length = "; filament used [mm] = 1234.56\n"
    read = slicing.read_estimates(only_length)
    assert read.filament_mm == 1234.56
    assert read.grams is None, "grams were invented from a length"
    assert read.seconds is None, "a time was invented from a length"


def test_gcode_with_no_estimates_says_so_rather_than_reporting_zero():
    """
    A print reported as taking no time and no filament is a figure somebody
    might believe. An absent one is a question they will ask.
    """
    read = slicing.read_estimates("G1 X0 Y0\nG1 X10 Y10\n")
    assert not read.ok
    assert read.seconds is None and read.grams is None
    assert "no estimates" in read.why


def test_durations_in_every_shape_the_slicer_writes():
    assert slicing.as_seconds("45s") == 45
    assert slicing.as_seconds("23m 45s") == 23 * 60 + 45
    assert slicing.as_seconds("1h 23m 45s") == 3600 + 23 * 60 + 45
    assert slicing.as_seconds("2d 1h") == 2 * 86400 + 3600
    # AND NOTHING AT ALL for something that is not a duration - never zero.
    assert slicing.as_seconds("who knows") is None
    assert slicing.as_seconds("") is None


def test_with_no_slicer_it_says_which_one_to_install(monkeypatch, tmp_path):
    """
    A missing feature that says only "not available" is a dead end. Naming
    the package turns it into a decision somebody can make.
    """
    monkeypatch.setattr(slicing, "which_slicer", lambda: None)
    model = tmp_path / "part.stl"
    model.write_bytes(b"solid x\nendsolid x\n")

    out = slicing.slice_part(model)
    assert not out.ok
    assert out.seconds is None and out.grams is None
    assert "apt install prusa-slicer" in out.why


def test_a_slicer_that_refuses_hands_back_its_own_complaint(monkeypatch, tmp_path):
    """
    "Object too large for the bed" is the answer. Rewording it here would
    lose the one sentence worth reading.
    """
    import subprocess

    model = tmp_path / "part.stl"
    model.write_bytes(b"solid x\nendsolid x\n")

    monkeypatch.setattr(slicing, "which_slicer", lambda: "/usr/bin/pretend")

    def refuse(command, **kw):
        return subprocess.CompletedProcess(
            command, 1, stdout="", stderr="Object too large for the bed\n")

    monkeypatch.setattr(subprocess, "run", refuse)
    out = slicing.slice_part(model)
    assert not out.ok
    assert out.why == "Object too large for the bed"


def test_the_real_machine_reports_honestly_either_way():
    """
    Whatever is installed here, the answer is well formed: figures with a
    slicer named, or no figures and a reason. There is no third state.
    """
    out = slicing.Sliced(why=slicing.how_to_install()) \
        if slicing.which_slicer() is None else None
    if out is None:
        import pytest

        pytest.skip("a slicer is installed - covered by the fixture tests")
    assert not out.ok
    assert out.why
