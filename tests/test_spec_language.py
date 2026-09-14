"""
English that changes a design. CLAUDE.md rule 32.

The rule says English is the interface and parameters are the implementation,
and it says it outranks the briefs. That is only worth writing down if
something fails when it stops being true, so the last test in this file walks
every template in the registry and fails any choice a person has no way to ask
for. A capability nobody can reach does not exist.

The rest is the behaviour the owner asked for, in his words:

  * "make this roof a triangular roof" changes the roof of the thing in front
    of you
  * size and dimensions are the sliders' job; English is for visual change
  * "if something is changed in size and other things are not mentioned then
    the app should know to keep relative sizing between changes"
"""

from __future__ import annotations

import pytest

from whittle.build.templates.enclosure import EnclosureParams
from whittle.spec import language

#: A birdhouse as the engine actually built one - parts/birdhouse/spec.yaml.
BIRDHOUSE = dict(width_mm=120.0, depth_mm=100.0, height_mm=140.0,
                 entrance_dia_mm=32.0, roof_pitch_deg=18.0,
                 roof_style="mono", roof=True, wall_mm=3.0)


def read(sentence: str, current: dict | None = None) -> language.Reading:
    return language.read(sentence, EnclosureParams, dict(current or BIRDHOUSE))


# ---------------------------------------------------------------------------
# the sentence the owner actually typed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sentence", [
    "make this roof a triangular roof",
    "make the roof triangular",
    "give it a proper roof",
    "I want a pitched roof",
    "can you make it a peaked roof",
    "a-frame roof please",
])
def test_asking_for_a_triangular_roof_sets_the_gable(sentence):
    """
    RULE 32, first part: every capability needs an English route to it.
    `roof_style` is worth nothing if this sentence does not reach it.
    """
    assert read(sentence).as_params() == {"roof_style": "gable"}


def test_the_other_roof_shapes_are_reachable_too():
    assert read("flat roof please").as_params() == {"roof_style": "flat"}
    assert read("make it a lean-to roof", {**BIRDHOUSE, "roof_style": "gable"}
                ).as_params() == {"roof_style": "mono"}


def test_asking_for_what_it_already_is_changes_nothing():
    """
    A no-op is not an edit. Rebuilding a part to set a value to what it already
    was costs minutes and produces an identical file.
    """
    assert read("make the roof a lean-to").changes == []


def test_a_feature_can_be_taken_off_and_put_back():
    assert read("no roof").as_params() == {"roof": False}
    assert read("add a roof", {**BIRDHOUSE, "roof": False}
                ).as_params() == {"roof": True}


# ---------------------------------------------------------------------------
# "keep relative sizing between changes"
# ---------------------------------------------------------------------------


def test_naming_one_dimension_keeps_the_shape():
    """
    The owner's rule: "if something is changed in size and other things are not
    mentioned then the app should know to keep relative sizing".

    Nobody picturing a taller birdhouse pictures the same footprint with a
    stretched box on it.
    """
    changes = {c.field: c for c in read("make it 200mm tall").changes}

    assert changes["height_mm"].after == pytest.approx(200.0)
    factor = 200.0 / 140.0
    assert changes["width_mm"].after == pytest.approx(120.0 * factor, abs=0.01)
    assert changes["depth_mm"].after == pytest.approx(100.0 * factor, abs=0.01)

    # AND IT SAYS IT DID. A number that moved on its own is a surprise at the
    # printer unless it is visible.
    assert changes["height_mm"].derived is False
    assert changes["width_mm"].derived is True
    assert "proportion" in changes["width_mm"].because


def test_naming_two_dimensions_means_what_it_says():
    """
    Once a second dimension is given, the person is describing the box rather
    than scaling it, and inventing a third would override them.
    """
    changes = {c.field: c for c in read("make it 200mm tall and 150mm wide").changes}
    assert changes["height_mm"].after == pytest.approx(200.0)
    assert changes["width_mm"].after == pytest.approx(150.0)
    assert "depth_mm" not in changes


def test_what_must_never_be_scaled_with_the_body():
    """
    RULE 15 AND THE REASON THIS IS CAREFUL. A wall is a manufacturing
    constraint set by the nozzle and an entrance is 32 mm because that is the
    size of the bird. Scaling either with the body produces a part that is
    unprintable or useless while looking perfectly correct on screen.
    """
    fields = {c.field for c in read("make it 200mm tall").changes}
    assert "wall_mm" not in fields
    assert "entrance_dia_mm" not in fields
    assert "roof_thick_mm" not in fields


def test_a_shape_change_does_not_move_a_dimension():
    assert read("make the roof triangular").as_params() == {"roof_style": "gable"}


# ---------------------------------------------------------------------------
# not guessing
# ---------------------------------------------------------------------------


def test_one_number_never_lands_in_four_fields():
    """
    THE BUG THIS PINS, found the first time the parser ran on a real template.
    "Make it 15cm wide" set width_mm AND entrance_dia_mm AND drain_dia_mm AND
    mount_dia_mm, because a diameter is a width too. Three of those nobody
    asked for, none of them visible in a render, all of them wrong at the
    printer.
    """
    changes = {c.field for c in read("make it 15cm wide").changes if not c.derived}
    assert changes == {"width_mm"}


def test_degrees_never_land_in_a_length():
    changes = {c.field: c.after for c in read("pitch the roof at 30 degrees").changes}
    assert changes == {"roof_pitch_deg": 30.0}


def test_something_that_is_not_geometry_is_surfaced_in_the_persons_own_words():
    """RULE 32, third part, which does not bend."""
    reading = read("make it look fierce")
    assert reading.changes == []
    assert reading.unmapped == ["make it look fierce"]
    assert reading.options, "a sentence that did nothing should offer the real options"


def test_the_good_half_of_a_mixed_sentence_still_lands():
    reading = read("make the roof triangular and make it look fierce")
    assert reading.as_params() == {"roof_style": "gable"}
    assert reading.unmapped == ["make it look fierce"]


def test_an_empty_sentence_does_nothing_quietly():
    reading = read("   ")
    assert reading.changes == []
    assert reading.unmapped == []
    assert reading.echo() == "nothing to do"


def test_the_same_sentence_reads_the_same_way_ten_times():
    """
    Why this is a parser and not a prompt, which this repo has measured twice
    on the generate path.
    """
    seen = {read("make this roof a triangular roof").echo() for _ in range(10)}
    assert len(seen) == 1


# ---------------------------------------------------------------------------
# rule 32, enforced
# ---------------------------------------------------------------------------


def _templates():
    """Every registered template, through the registry's own public accessors."""
    from whittle.spec import registry

    return {name: registry.get(name) for name in registry.names()}


def test_every_choice_in_every_template_can_be_asked_for_in_english():
    """
    RULE 32 MADE MECHANICAL: "a parameter the spec supports but no sentence can
    reach does not exist as far as the product is concerned."

    Every Literal field on every registered template has to declare, per value,
    the words a person would use. Adding a new shape option without saying how
    somebody asks for it fails here rather than shipping as a feature only the
    schema knows about.
    """
    missing: list[str] = []

    for name, template in _templates().items():
        model = template.params_model
        for field_name, info in getattr(model, "model_fields", {}).items():
            options = language.choices_of(info)
            if not options:
                continue
            said = (getattr(info, "json_schema_extra", None) or {})
            said = said.get("says") if isinstance(said, dict) else None
            for value in options:
                words = (said or {}).get(value) if isinstance(said, dict) else None
                # The value's own name always counts - "flat" is a word people
                # use. What must not happen is a value nobody could name.
                if words or value.isalpha():
                    continue
                missing.append("%s.%s = %r" % (name, field_name, value))

    assert not missing, (
        "these choices have no English route to them, which rule 32 forbids:\n  "
        + "\n  ".join(missing)
        + "\n\nDeclare them on the field:\n"
          '    json_schema_extra={"says": {"<value>": ["what people say"]}}')


def test_the_roof_style_declares_how_people_ask_for_each_shape():
    """
    The concrete case, so the general test above cannot pass vacuously if the
    registry is ever empty.
    """
    info = EnclosureParams.model_fields["roof_style"]
    said = info.json_schema_extra["says"]

    assert set(said) == {"flat", "mono", "gable"}
    assert "triangular" in said["gable"]
    for value, words in said.items():
        assert words, "%s has no words anybody would say" % value
