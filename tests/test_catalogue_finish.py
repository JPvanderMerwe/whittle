"""
The surface finish across the catalogue, not one template at a time.

WHY THIS FILE IS SEPARATE FROM test_surface_finish.py
------------------------------------------------------
That file proves the MODULE works. This one proves the CATALOGUE uses it, and
uses it the same way everywhere - which is the thing that actually decays.
The finish began as four fields inside `enclosure`; the next template that
wanted one copied them. Copies drift, and the day one template gains a family
the others do not, "put a honeycomb on it" works on a box and does nothing on
a tray. The person typing it has no way to tell which.

So the rules asserted here are about sameness:

  * every template that declares a finish takes it from surface.Finished, so
    there is one list of families and one list of words
  * asking for a finish actually removes material - a pattern that was
    accepted, reported and did nothing is the worst outcome of the three
  * a finish never makes the part bigger, on any template
  * a template that has NO outer wall to decorate says so here by name, so
    "why can I not put ribs on a hook" has an answer written down
"""

from __future__ import annotations

import pytest

from whittle.build import surface
from whittle.build.helpers import BuildLog
from whittle.spec import language, registry

#: The templates with a wall that runs a band around a body.
FINISHED = ("container", "tray", "cable_box", "gridfinity", "vessel",
            "enclosure")

#: The templates with no such wall, and why. A plate, an arm or a blade has an
#: outside, but it has no BAND - there is nowhere for a pattern to run round.
#: Written down so the absence is a decision on the record rather than an
#: oversight somebody has to rediscover.
NOT_FINISHED = {
    "bracket": "a plate and a gusset, no body to run a band around",
    "hook": "a backplate and an arm",
    "clip": "a C-section a few millimetres wide",
    "stand": "a leaning wedge, no vertical wall",
    "keyring_device": "a flat tag",
    "louvre_vent": "a frame full of blades",
}


def _model(name: str):
    return registry.get(name).params_model


def test_the_catalogue_is_split_into_finished_and_not_on_purpose():
    """Every template is on exactly one of the two lists, and the lists are real."""
    assert set(FINISHED) | set(NOT_FINISHED) == set(registry.names())
    assert not set(FINISHED) & set(NOT_FINISHED)
    for name, why in NOT_FINISHED.items():
        assert why and "finish" not in _model(name).model_fields, name


@pytest.mark.parametrize("name", FINISHED)
def test_every_finished_template_offers_the_same_families(name):
    """
    One list of families, so a person learns the words once.

    `enclosure` is allowed MORE than the shared set - `board` and `slat` are
    its own, they mean weatherboard and slatted panel on a birdhouse and
    nothing on a tray - but it may not offer FEWER.
    """
    options = set(language.choices_of(_model(name).model_fields["finish"]))
    assert set(surface.FINISHES) <= options, (
        "%s is missing %s" % (name, sorted(set(surface.FINISHES) - options)))


@pytest.mark.parametrize("name", FINISHED)
def test_every_finished_template_declares_the_same_words(name):
    """
    RULE 32 across the catalogue. "Honeycomb" reaching `hex` on a container
    and nothing on a tray is a capability that exists on one object and not
    the next, which is indistinguishable from a bug to the person using it.
    """
    said = _model(name).model_fields["finish"].json_schema_extra["says"]
    for value, words in surface.FINISH_SAYS.items():
        assert set(words) <= set(said.get(value, [])), "%s.%s" % (name, value)


@pytest.mark.parametrize("name", FINISHED)
def test_every_finished_template_carries_the_three_numbers(name):
    for field in ("finish_pitch_mm", "finish_groove_mm", "finish_depth_mm"):
        assert field in _model(name).model_fields, "%s.%s" % (name, field)


#: One buildable set of parameters per template, and a family that template
#: can actually take. Vessel is flared by default, so it gets a family that
#: follows a curve; the rest are straight-walled.
CASES = [
    ("container", {}, "ribs"),
    ("tray", {}, "ribs"),
    ("cable_box", {}, "ribs"),
    ("gridfinity", {"units_z": 6}, "ribs"),
    ("vessel", {"outer_dia_mm": 90.0, "height_mm": 110.0}, "hex"),
    ("enclosure", {}, "hex"),
]


def _built(name: str, params: dict):
    template = registry.get(name)
    model = template.params_model(**params)

    class _Spec:
        material = "pla"

    return template.builder(model, _Spec())


@pytest.mark.parametrize("name,params,kind", CASES)
def test_asking_for_a_finish_actually_removes_material(name, params, kind):
    """
    THE QUIET FAILURE. A finish that is accepted, reported in the log and
    never cut leaves a part that looks finished and is not what was asked
    for - and nothing downstream notices, because the part is valid.
    """
    plain = _built(name, dict(params, finish="plain")).solid.val().Volume()
    finished = _built(name, dict(params, finish=kind)).solid.val().Volume()
    assert finished < plain - 10.0, (
        "%s accepted finish=%s and cut nothing" % (name, kind))


@pytest.mark.parametrize("name,params,kind", CASES)
def test_a_finish_never_makes_the_part_bigger(name, params, kind):
    """
    Every family is cut, never added, on every template - so nominal_mm stays
    true and a part that fitted still fits. On gridfinity this is not a
    nicety: a bin that grew by half a millimetre does not go in the baseplate.
    """
    plain = _built(name, dict(params, finish="plain")).solid.val().BoundingBox()
    got = _built(name, dict(params, finish=kind)).solid.val().BoundingBox()
    assert got.xlen <= plain.xlen + 1e-6
    assert got.ylen <= plain.ylen + 1e-6
    assert got.zlen <= plain.zlen + 1e-6


@pytest.mark.parametrize("name,params,kind", CASES)
def test_the_finish_is_named_in_english_on_every_template(name, params, kind):
    """The words reach the parameter, read through the parser that has to do it."""
    model = registry.get(name).params_model
    reading = language.read("put a honeycomb on the outside", model,
                            dict(params, finish="plain"))
    assert reading.as_params().get("finish") == "hex", name


def test_a_curved_vessel_refuses_the_families_that_need_a_straight_run():
    """
    A rib is one long cut and cannot follow a silhouette that bends. Refused
    by name, with the ones that DO follow a curve, rather than built wrong.
    """
    from whittle.build.templates.vessel import VesselParams

    with pytest.raises(ValueError) as caught:
        VesselParams(profile="flared", finish="ribs")
    message = str(caught.value)
    assert "bends" in message and "hex" in message

    VesselParams(profile="flared", finish="hex")          # follows the curve
    VesselParams(profile="cylinder", finish="ribs")       # straight run


def test_the_finish_depth_comes_from_the_wall_and_not_from_a_constant():
    """
    A fixed default is wrong on every template with a different wall: 0.7 mm
    is a quarter of a 2.8 mm box wall and more than a third of a 2.0 mm tray
    wall, so "a ribbed tray" was refused over five hundredths of a millimetre.
    """
    from whittle.build.templates.gridfinity import GridfinityParams
    from whittle.build.templates.tray import TrayParams

    # The same hair of tolerance the module itself allows, and for the same
    # reason: a third of 1.2 is not 0.4 in binary, so a depth this code
    # derived from the wall reads as fractionally over the wall it came from.
    for model in (TrayParams(finish="ribs"), GridfinityParams(finish="ribs")):
        depth = model.finish_spec(model.wall_mm).depth_mm
        assert depth <= model.wall_mm / 3.0 + 1e-9
        assert surface.check(model.finish_spec(model.wall_mm),
                             model.wall_mm) is None

    # Given explicitly it is checked, not clamped.
    with pytest.raises(ValueError):
        TrayParams(finish="ribs", wall_mm=2.0, finish_depth_mm=1.5)


@pytest.mark.parametrize("name", FINISHED)
def test_a_finished_template_can_be_asked_for_a_different_look(name):
    """
    The same prompt twice has to give two designs, and the outside is the
    thing people have an opinion about. Every finished template declares the
    finish as a variation axis.
    """
    from whittle.agent.variations import AXES, STYLE_AXES

    axes = dict(AXES.get(name, []))
    assert "finish" in axes, "%s offers no alternative look" % name
    assert len(axes["finish"]) >= 3
    assert "finish" in STYLE_AXES
