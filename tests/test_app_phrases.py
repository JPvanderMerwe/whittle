"""
Every sentence the phone offers, read by the parser that has to carry it out.

THE FAILURE THIS EXISTS TO CATCH IS SILENT. The app suggests phrases - "hollow
it to 2mm", "clean it up" - as one-tap chips, because an empty box labelled
"say what you want" only works for somebody who already knows what the parser
accepts. Every one of those phrases is a promise, and the parser is a set of
regexes in another language in another directory. Change
`\\b(floaters?|debris|specks?)\\b` and "clean it up" quietly becomes a chip that
puts a sentence in the box, sends it, and is told nothing matched.

Nothing in either codebase would have noticed. The app's own tests check the
chips are well-formed; the parser's tests check the regexes match the phrases
the PARSER'S authors thought of. This is the only place the two meet.

SO THE PHRASES ARE READ OUT OF THE APP'S SOURCE, not copied here. A copy is a
second list that drifts, and a test that asserts a copy of the app's behaviour
proves the copy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TWEAKS = ROOT / "app" / "src" / "tweaks.ts"


def _mesh_phrases() -> list[tuple[str, str]]:
    """
    The (operation, sentence) pairs out of MESH_TWEAKS in app/src/tweaks.ts.

    Parsed with a regex rather than by running the TypeScript: node is not a
    dependency of this suite, and the shape being read is a literal array of
    object literals that the app's own typecheck already guarantees.
    """
    if not TWEAKS.is_file():
        pytest.skip("the native client is not in this checkout")

    source = TWEAKS.read_text()
    block = re.search(
        r"const MESH_TWEAKS[^=]*=\s*\[(.*?)\n\];", source, re.S
    )
    assert block, (
        "MESH_TWEAKS is not in app/src/tweaks.ts in the shape this test reads. "
        "If it moved, move this test with it - do not delete the coupling."
    )

    pairs = re.findall(
        r"kind:\s*'([^']+)'\s*,\s*\n?\s*say:\s*'([^']+)'", block.group(1)
    )
    assert pairs, "no phrases found in MESH_TWEAKS"
    return pairs


def test_every_phrase_the_app_offers_is_one_the_parser_reads():
    from whittle.edit import intent

    for operation, sentence in _mesh_phrases():
        reading = intent.read(sentence)
        got = [p.operation for p in reading.proposals]

        assert operation in got, (
            "the app offers %r as a one-tap way to %s, and the parser reads it "
            "as %s. That chip puts a sentence in the box, sends it, and gets "
            "'nothing matched' back." % (sentence, operation, got or "nothing")
        )
        # AND NOTHING LEFT OVER. Rule 32 says an instruction that mapped to
        # nothing is reported every time, so a suggested phrase with a dangling
        # clause makes the app report its own suggestion as partly ignored.
        assert not reading.unmapped, (
            "%r is offered by the app but the parser could not place %s"
            % (sentence, reading.unmapped)
        )


def test_the_app_never_offers_an_operation_that_is_not_built():
    """
    `not_built_yet` is a real list - auto_orient, emboss_text and nine others
    are named in the registry and not implemented. The app filters its
    suggestions against the catalogue at runtime, and this checks the list it
    filters FROM has nothing impossible in it, so the filter is a safety net
    rather than the only thing standing between a person and a dead chip.
    """
    from whittle.web import projects as P

    catalogue = P.catalogue()
    built = {op["kind"] for op in catalogue["operations"]}
    pending = set(catalogue["not_built_yet"])

    for operation, sentence in _mesh_phrases():
        assert operation not in pending, (
            "the app offers %r, which asks for %s - a registered operation that "
            "is not built yet" % (sentence, operation)
        )
        assert operation in built, (
            "%r asks for %s, which the registry does not have at all"
            % (sentence, operation)
        )


# ---------------------------------------------------------------------------
# the other parser: sentences about a spec
# ---------------------------------------------------------------------------
#
# The mesh phrases above are a fixed list, so they can be read out of the app's
# source. The SPEC phrases are generated per template - the app builds them
# from the schema, so that a part with no width is never offered "wider" - and
# there is no list to read.
#
# What IS fixed is the shape: "make it <comparative>", "make the <noun>
# <choice>", "no <noun>", "add a <noun>". Those shapes are built here from the
# same schemas and handed to the parser, which is the thing that has to carry
# them out. A change to COMPARATIVES, to the boolean prefixes, or to how a
# choice is matched breaks this rather than turning the phone's chips into
# sentences that report themselves as not understood.


def _templates():
    from whittle import api

    for name in api.templates():
        yield name, api.template_info(name)


def _read(spec_params: dict, template_name: str, sentence: str):
    from whittle.spec import language, registry

    template = registry.get(template_name)
    return language.read(sentence, template.params_model, dict(spec_params))


@pytest.mark.parametrize("word", ["bigger", "smaller"])
def test_the_overall_words_move_every_principal_dimension(word):
    """"Make it bigger" is the first thing anybody says, and it has no axis."""
    for name, info in _templates():
        principal = [
            p["name"] for p in info["params"]
            if p["name"] in ("width_mm", "depth_mm", "height_mm")
        ]
        if not principal:
            continue
        reading = _read({}, name, "make it %s" % word)
        moved = {c.field for c in reading.changes}
        assert moved, "%s: 'make it %s' moved nothing" % (name, word)
        assert not reading.unmapped, (
            "%s: 'make it %s' left %s unread" % (name, word, reading.unmapped)
        )


def test_a_comparative_is_only_offered_when_the_template_has_that_axis():
    """
    The filter the app applies, checked against the parser it is mirroring.

    The app hides "make it taller" on a template with no height, because the
    parser refuses it - `_field_ending` returns nothing rather than moving
    whatever field sorts first. If the parser ever started guessing, the app's
    filter would be hiding a change that now works; if the app's mirror of
    `_field_ending` drifts, it offers one that does not. This catches both.
    """
    axes = {
        "taller": "height", "shorter": "height",
        "wider": "width", "narrower": "width",
        "deeper": "depth", "shallower": "depth",
        "thicker": "wall", "thinner": "wall",
    }
    for name, info in _templates():
        names = [p["name"] for p in info["params"]]
        for word, axis in axes.items():
            has = any(
                n == "%s_mm" % axis or n == axis or n.startswith("%s_" % axis)
                for n in names
            )
            reading = _read({}, name, "make it %s" % word)
            moved = bool(reading.changes)
            assert moved == has, (
                "%s has%s a %s field, and the parser %s 'make it %s'"
                % (name, "" if has else " no", axis,
                   "moved something for" if moved else "refused", word)
            )


def test_every_choice_is_reachable_by_the_sentence_the_app_builds():
    """
    "Make this roof a triangular roof" is the sentence rule 32 was written for.

    The app offers "make the <noun> <choice>" for every choice not already in
    force, with the schema's `_style`/`_kind` suffix dropped - because nobody
    says "make the roof style gable". This checks each one lands on the right
    field with the right value.
    """
    import re

    for name, info in _templates():
        for parameter in info["params"]:
            if not parameter["choices"]:
                continue
            noun = re.sub(r"_(style|kind|type|mode)$", "", parameter["name"])
            noun = noun.replace("_", " ")
            for choice in parameter["choices"]:
                if str(parameter["default"]) == choice:
                    continue
                sentence = "make the %s %s" % (noun, choice)
                reading = _read({}, name, sentence)
                landed = {c.field: c.after for c in reading.changes}
                assert landed.get(parameter["name"]) == choice, (
                    "%s: %r should set %s to %r, and the parser did %s"
                    % (name, sentence, parameter["name"], choice, landed or "nothing")
                )


def test_a_boolean_is_reachable_both_ways():
    """`no roof` and `add a gusset` - the two prefixes the app builds from."""
    for name, info in _templates():
        for parameter in info["params"]:
            if parameter["type"] != "bool":
                continue
            noun = parameter["name"].replace("_", " ")

            off = _read({parameter["name"]: True}, name, "no %s" % noun)
            assert any(
                c.field == parameter["name"] and c.after is False for c in off.changes
            ), "%s: 'no %s' did not turn %s off" % (name, noun, parameter["name"])

            on = _read({parameter["name"]: False}, name, "add a %s" % noun)
            assert any(
                c.field == parameter["name"] and c.after is True for c in on.changes
            ), "%s: 'add a %s' did not turn %s on" % (name, noun, parameter["name"])


def test_the_fixtures_the_app_is_tested_against_are_not_stale():
    """
    The staleness check, which is the one that matters.

    The app's own tests read app/tests/fixtures/*.json - the real schemas, so
    that "a bracket is never offered taller" is checked against the bracket
    rather than against a made-up template. A fixture is a copy, and a copy
    drifts: a template that gains a field or renames a choice leaves those
    tests passing against last month while the app offers a change the engine
    no longer has.

    Same argument tools/tokens.py makes about a hex value in two places. The
    drift is invisible until somebody puts the two side by side, so this puts
    them side by side on every run.
    """
    from tools import app_fixtures

    assert app_fixtures.main(["--check"]) == 0, (
        "the app's schema fixtures no longer match the engine. "
        "Run: python3 tools/app_fixtures.py"
    )


# ---------------------------------------------------------------------------
# the other cross-language contract: a slider's payload
# ---------------------------------------------------------------------------


def test_the_app_reads_every_field_the_engine_sends_for_a_slider():
    """
    THE SAME SILENT FAILURE, ONE PAYLOAD OVER.

    A part built from operations has no template and no parameter names, so
    the server reads the bounds off the op models and sends its numbers as a
    list - and `dimensionsFromOps` in app/src/tweaks.ts turns each one into a
    slider by picking fields off it by name. Rename `bound_high` in Python and
    the app gets `undefined`: no type error, no test failure, just a control
    whose limits are gone.

    Nothing else checks this. The engine's tests assert the payload; the app's
    typecheck asserts its own interface, which is hand-written from that
    payload and is exactly the copy that drifts.

    Read out of both sources rather than listed here, for the reason at the
    top of this file.
    """
    if not TWEAKS.is_file():
        pytest.skip("the native client is not in this checkout")

    from whittle.spec.dsl import op_dimensions

    sent = op_dimensions([
        {"op": "rounded_prism", "width_mm": 80, "depth_mm": 40, "height_mm": 6,
         "corner_r_mm": 2},
    ])
    assert sent, "op_dimensions offered nothing for a part with four numbers"
    keys = set(sent[0])

    block = re.search(
        r"export function dimensionsFromOps\b.*?\n}\n", TWEAKS.read_text(), re.S)
    assert block, "dimensionsFromOps is no longer in app/src/tweaks.ts"

    read = set(re.findall(r"\bone\.([a-z_][a-z0-9_]*)", block.group(0)))
    assert read, "the mapper reads nothing off the payload"

    missing = read - keys
    assert not missing, (
        "app/src/tweaks.ts reads %s off a dimension and the engine does not "
        "send it - those sliders would have undefined in them. The engine "
        "sends: %s"
        % (", ".join(sorted(missing)), ", ".join(sorted(keys)))
    )
