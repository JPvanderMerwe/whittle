"""
The language layer. Build plan v8 section 12.

M3's acceptance: "\"hollow it to 2mm and cut it to fit my bed\" produces the
right two operations, ten times out of ten." The ten-times test is at the
bottom and it is not a formality - it is the reason this is a parser rather
than a prompt. A 7B model on a CPU does not do anything ten times out of ten,
which this repo has measured twice on the generate path.
"""

from __future__ import annotations

import pytest
import trimesh

from whittle.edit import EditStack, apply_to, diff, read, resolve
from whittle.ingest.gate import check

BED = (220.0, 220.0, 250.0)


def _kinds(reading) -> list[str]:
    return [p.operation for p in reading.proposals]


# ---------------------------------------------------------------------------
# reading a sentence
# ---------------------------------------------------------------------------


def test_two_instructions_in_one_sentence_become_two_operations():
    reading = read("hollow it to 2mm and cut it to fit my bed")
    assert _kinds(reading) == ["hollow", "cut_plane"]
    assert reading.proposals[0].parameters["wall_mm"] == pytest.approx(2.0)


@pytest.mark.parametrize("phrase,expected", [
    ("hollow it to 2mm", 2.0),
    ("hollow it to 2 mm", 2.0),
    ("hollow to 0.25 inches", 6.35),
    ("hollow it to 1.5cm", 15.0),
])
def test_the_units_people_type_are_read(phrase, expected):
    reading = read(phrase)
    assert reading.proposals[0].parameters["wall_mm"] == pytest.approx(expected)


def test_a_missing_number_is_not_invented():
    """
    whittle/agent/command.py's rule, followed here: a command that silently
    invents a dimension is worse than one that fails. The operation is still
    right - they did ask to hollow it - so it goes on with its own default,
    named as derived and with the confidence dropped so the UI shows it.
    """
    reading = read("hollow it")
    proposal = reading.proposals[0]

    assert proposal.operation == "hollow"
    assert "wall_mm" not in proposal.parameters
    assert "wall_mm" in proposal.derived
    assert proposal.confidence < 1.0


def test_something_that_is_not_geometry_is_surfaced_every_time():
    """
    Section 12: "make it look fierce" is not a geometric operation and
    "pretending otherwise is how trust dies".
    """
    reading = read("make it look fierce")
    assert reading.proposals == []
    assert reading.unmapped == ["make it look fierce"]
    assert "nothing geometric" in reading.echo()


def test_a_vague_ask_gets_the_real_options_rather_than_a_guess():
    """
    Section 12: "If they say 'make it stronger', respond with the real
    options: thicken walls, reduce hollow, add fillets, reorient."
    """
    reading = read("make it stronger")
    assert reading.proposals == []
    assert len(reading.questions) == 1

    question = reading.questions[0]
    assert len(question.options) >= 2
    assert any("thicken" in option for option in question.options)


def test_ambiguity_asks_once():
    """Section 12: "Ambiguity asks once"."""
    reading = read("make it stronger and stronger")
    assert len(reading.questions) == 1


def test_the_good_part_of_a_mixed_sentence_still_lands():
    """
    A sentence with one real instruction and one piece of poetry should do the
    instruction and say what it ignored, not refuse the lot.
    """
    reading = read("hollow it to 2mm and make it look fierce")
    assert _kinds(reading) == ["hollow"]
    assert reading.unmapped == ["make it look fierce"]


def test_an_empty_sentence_does_nothing_quietly():
    reading = read("   ")
    assert reading.proposals == []
    assert reading.unmapped == []
    assert reading.echo() == "nothing to do"


# ---------------------------------------------------------------------------
# resolving goals against the machine
# ---------------------------------------------------------------------------


def test_fit_my_bed_is_resolved_from_the_bed_and_the_model():
    """
    "To fit my bed" names an operation and a GOAL. The height to cut at is
    arithmetic on the model and the machine, and it is reported as derived so
    a number never appears without a reason attached.
    """
    tall = trimesh.creation.box((90, 60, 300))
    reading = resolve(read("cut it to fit my bed"),
                      bounds_mm=tall.bounds, bed_mm=BED)
    proposal = reading.proposals[0]

    assert proposal.operation == "cut_plane"
    assert proposal.parameters["at_mm"] == pytest.approx(0.0, abs=0.01)
    assert "250 mm bed" in proposal.derived["at_mm"]
    assert "2 pieces" in proposal.derived["at_mm"]


def test_the_cut_is_in_the_models_own_coordinates():
    """
    THE BUG THIS PINS. A cut plane is a position, and a model centred on the
    origin runs -150 to +150 rather than 0 to 300. Working from the extents
    alone put the plane exactly on the top face, where it cut nothing: "the
    cut at z 150.00 mm is outside the model, which runs -150.00 to 150.00".
    """
    lifted = trimesh.creation.box((90, 60, 300))
    lifted.apply_translation((0, 0, 400))       # nowhere near the origin

    reading = resolve(read("cut it to fit my bed"),
                      bounds_mm=lifted.bounds, bed_mm=BED)
    at = reading.proposals[0].parameters["at_mm"]

    assert float(lifted.bounds[0][2]) < at < float(lifted.bounds[1][2]), (
        "the cut at %.1f is outside the model, which runs %.1f to %.1f"
        % (at, lifted.bounds[0][2], lifted.bounds[1][2]))


def test_a_model_that_already_fits_is_told_so():
    """
    Cutting it anyway because the sentence said "cut" would be obeying the
    words over the intent: they asked for it to fit the bed, and it does.
    """
    small = trimesh.creation.box((40, 40, 40))
    reading = resolve(read("cut it to fit my bed"),
                      bounds_mm=small.bounds, bed_mm=BED)
    proposal = reading.proposals[0]

    assert "already fits" in proposal.derived["at_mm"]
    assert proposal.confidence < 0.8


def test_no_bed_configured_says_so_rather_than_guessing_one():
    tall = trimesh.creation.box((90, 60, 300))
    reading = resolve(read("cut it to fit my bed"),
                      bounds_mm=tall.bounds, bed_mm=None)
    proposal = reading.proposals[0]

    assert "at_mm" not in proposal.parameters
    assert "no bed is configured" in proposal.derived["at_mm"]


# ---------------------------------------------------------------------------
# applying, and the diff
# ---------------------------------------------------------------------------


def test_reading_and_applying_are_separate_steps():
    """
    Section 12: "Show the selection before applying it." A caller has to be
    able to read a sentence, show what it understood, and apply only when the
    user agrees - which is impossible if parsing and applying are one call.
    """
    box = trimesh.creation.box((40, 40, 40))
    stack = EditStack(box)
    reading = read("hollow it to 2mm")

    assert stack.ops == [], "reading a sentence must not change the stack"

    apply_to(reading, stack)
    assert [op.kind for op in stack.ops] == ["hollow"]


def test_a_parameter_diff_reads_the_way_the_plan_asks():
    """Section 13.3: "Every language edit shows a parameter diff: wall_mm 1.2 -> 2.0"."""
    lines = diff({"wall_mm": 1.2}, {"wall_mm": 2.0})
    assert lines == ["wall_mm 1.2 -> 2.0"]

    assert diff({}, {"wall_mm": 2.0}) == ["wall_mm 2"]
    assert diff({"wall_mm": 2.0}, {"wall_mm": 2.0}) == []


# ---------------------------------------------------------------------------
# M3's acceptance, as the plan words it
# ---------------------------------------------------------------------------


def test_the_acceptance_sentence_ten_times_out_of_ten():
    """
    M3 IS DONE WHEN: "hollow it to 2mm and cut it to fit my bed" produces the
    right two operations, ten times out of ten.

    Ten identical readings, asserted identical. That is trivially true of a
    parser and is exactly the point: it is why this is a parser.
    """
    tall = trimesh.creation.box((90, 60, 300))
    sentence = "hollow it to 2mm and cut it to fit my bed"

    seen = set()
    for _ in range(10):
        reading = resolve(read(sentence), bounds_mm=tall.bounds, bed_mm=BED)
        assert _kinds(reading) == ["hollow", "cut_plane"]
        assert reading.proposals[0].parameters["wall_mm"] == pytest.approx(2.0)
        assert reading.unmapped == []
        seen.add(reading.echo())

    assert len(seen) == 1, "ten readings gave %d different answers" % len(seen)


def test_the_acceptance_sentence_actually_makes_the_model_printable():
    """
    The operations being right is half of it. Running them has to turn a model
    the gate rejects into one it accepts - which is the whole product in one
    sentence.
    """
    tall = trimesh.creation.box((90, 60, 300))

    before = check(tall, nozzle_mm=0.4, bed_mm=BED)
    assert not before.printable
    assert any(f.rule == "bed size" for f in before.failures)

    stack = EditStack(tall, nozzle_mm=0.4)
    reading = resolve(read("hollow it to 2mm and cut it to fit my bed"),
                      bounds_mm=tall.bounds, bed_mm=BED)
    apply_to(reading, stack)
    out = stack.evaluate()

    after = check(out, nozzle_mm=0.4, bed_mm=BED)
    assert after.printable, after.as_text()

    # Each piece fits, which is what "print it in two goes" means.
    pieces = out.split(only_watertight=False)
    assert len(pieces) >= 2
    for piece in pieces:
        assert float(piece.extents[2]) <= BED[2] + 0.01

    # And every step is still a slider afterwards.
    for op in stack.ops:
        assert op.parameters
