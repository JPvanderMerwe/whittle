"""
English to the operation that makes it.

THE FAILURE BEING GUARDED. Asked for "a Redbull can" the engine built a
hollowed box with two plates floating below the bed - not because a
dimension was wrong but because nothing said a can is a turned shape. These
tests are mostly about the ways a word map goes wrong: naming an op that
does not exist, matching inside another word, and being confidently wrong
about an ambiguous one.
"""

from __future__ import annotations

import pytest

from whittle.spec import vocabulary as V
from whittle.spec.dsl import OP_NAMES


def test_every_op_it_names_actually_exists():
    """
    THE ONE THAT MATTERS MOST.

    Advice to use an op the DSL does not have is worse than no advice: it
    reads authoritative, the model follows it, and the spec cannot compile.
    A word map is exactly the kind of file where a plausible-sounding op
    name gets typed from memory.
    """
    named = {s.op for s in V.STRATEGIES}
    missing = named - set(OP_NAMES)
    assert not missing, (
        "the vocabulary steers towards %s, which the DSL does not have. "
        "Real ops: %s" % (", ".join(sorted(missing)), ", ".join(sorted(OP_NAMES)))
    )


def test_a_can_is_turned():
    """The part this file exists for."""
    assert [s.op for s in V.strategies_for("a Redbull can")] == ["revolve"]
    assert [s.op for s in V.strategies_for("a tin can")] == ["revolve"]
    assert "revolve" in [s.op for s in V.strategies_for("a water bottle")]


@pytest.mark.parametrize("request_text, expected", [
    ("a vase for the table", "revolve"),
    ("a plant pot", "revolve"),
    ("a storage box with a lid", "hollow"),
    ("a gear with 40 teeth", "profile_extrude"),
    ("a phone stand", "wedge"),
    ("a hook for the wall", "arc_rod"),
    ("a name plate for a door", "emboss_text"),
    ("an adapter from 40 mm to 25 mm", "loft"),
    ("a hinge", "free_joint"),
])
def test_ordinary_requests_reach_the_right_family(request_text, expected):
    ops = [s.op for s in V.strategies_for(request_text)]
    assert expected in ops, "%r steered to %s" % (request_text, ops or "nothing")


@pytest.mark.parametrize("request_text, wrong", [
    # A SUBSTRING MATCH IS ONE BUG AWAY FROM ADVISING A LATHE FOR A SCANNER,
    # in the confident voice of a fact.
    ("a flatbed scanner", "revolve"),          # scanner contains "can"
    ("chainmail sheet", "articulated_chain"),  # chainmail contains "chain"
    ("a candle", "revolve"),                   # candle contains "can"
    ("a boxer figure", "hollow"),              # boxer contains "box"
])
def test_it_does_not_match_inside_another_word(request_text, wrong):
    ops = [s.op for s in V.strategies_for(request_text)]
    assert wrong not in ops, "%r matched %s on a substring" % (request_text, wrong)


@pytest.mark.parametrize("request_text, expected", [
    # THE SPECIFIC PHRASE BEATS THE GENERAL WORD IT CONTAINS. A bottle
    # opener is a flat plate; a bottle is turned. Whichever family sat
    # earlier in the list used to win regardless.
    ("a bottle opener", "profile_extrude"),
    ("a name plate", "emboss_text"),
    ("a phone stand", "wedge"),
])
def test_the_longer_phrase_wins(request_text, expected):
    ops = [s.op for s in V.strategies_for(request_text)]
    assert ops and ops[0] == expected, "%r led with %s" % (request_text, ops)


def test_nothing_matched_is_silence_not_a_guess():
    """
    An unusual request gets the full op reference and no push in a direction
    nobody checked. Rule 31: "no template fits" is the normal case, and the
    same is true of "no word matches".
    """
    assert V.strategies_for("a widget for the thing") == []
    assert V.advice_for("a widget for the thing") == []
    assert V.strategies_for("") == []
    assert V.advice_for("   ") == []


def test_more_than_one_family_is_allowed_and_capped():
    """
    A vented box is hollow AND patterned, and saying both is closer to the
    truth than picking one. But a wall of advice competes with the request
    itself, so it stops at two.
    """
    several = V.strategies_for("an articulated dragon")
    assert len(several) >= 2
    assert len(V.advice_for("an articulated dragon")) == 2
    assert len(V.advice_for("an articulated dragon", limit=1)) == 1


def test_the_advice_uses_the_words_the_person_typed():
    """
    Rule 32's third clause: what happened is reported in the words they
    used. "a Redbull can is usually a turned shape" is recognisable; "can is
    usually a turned shape" is the machine talking about its own word list.
    """
    line = V.advice_for("a Redbull can")[0]
    assert line.startswith("a Redbull can is usually")
    assert "`revolve`" in line


def test_every_entry_explains_itself():
    """
    A steer with no reasoning is an instruction, and the model cannot tell
    when it does not apply. Every family says why in a sentence.
    """
    for strategy in V.STRATEGIES:
        assert strategy.words, "%s claims no words" % strategy.op
        assert len(strategy.why) > 40, "%s does not explain itself" % strategy.op
        assert strategy.kind
        # And no word is blank or punctuation, which would match everything.
        for word in strategy.words:
            assert word.strip() and any(c.isalpha() for c in word), (
                "%s claims %r" % (strategy.op, word)
            )


def test_no_word_is_claimed_by_two_families_with_different_answers():
    """
    A word in two families is a coin toss dressed as advice. Where a word
    genuinely belongs to both - "vent" is patterned and often hollow - the
    longer phrase in each keeps them apart, so a bare duplicate is a
    mistake rather than a nuance.
    """
    seen: dict[str, str] = {}
    clashes = []
    for strategy in V.STRATEGIES:
        for word in strategy.words:
            if word in seen and seen[word] != strategy.op:
                clashes.append("%r is claimed by both %s and %s"
                               % (word, seen[word], strategy.op))
            seen[word] = strategy.op
    assert not clashes, "; ".join(clashes)


def test_the_steer_reaches_the_prompt():
    from whittle.agent import prompts

    text = prompts.build_dsl_prompt("a Redbull can", "petg", 0.4, 0.2)
    assert "WHAT KIND OF SHAPE THIS IS" in text
    assert "`revolve`" in text

    # AND IS ABSENT WHEN NOTHING MATCHED. A heading over no advice tells the
    # model it has a steer it has not been given.
    bare = prompts.build_dsl_prompt("a widget for the thing", "petg", 0.4, 0.2)
    assert "WHAT KIND OF SHAPE THIS IS" not in bare


def test_the_worked_turned_example_actually_builds():
    """
    AN EXAMPLE THAT DOES NOT COMPILE IS WORSE THAN NONE, because it is the
    one thing in the prompt the model trusts completely - it will copy the
    shape of it exactly.

    So the example in the prompt is built here, from the prompt's own text,
    rather than being a snippet somebody believed was right.
    """
    import json

    from whittle.agent import prompts
    from whittle.spec.dsl import run_ops

    spec = json.loads(prompts.TURNED_EXAMPLE)
    scene = run_ops(spec["ops"], print_axis=spec.get("print_axis", "z"))

    box = scene.solid.val().BoundingBox()
    assert round(box.xlen) == 66 and round(box.zlen) == 115, (
        "the worked can is %.0f x %.0f x %.0f" % (box.xlen, box.ylen, box.zlen)
    )
    # HOLLOW, which is the half the model kept getting wrong - it reached for
    # `hollow` on a turned body instead of a second revolve in cut mode.
    volume_cm3 = scene.solid.val().Volume() / 1000.0
    assert 20 < volume_cm3 < 45, (
        "%.1f cm3 - a solid can of this size would be near 390" % volume_cm3
    )
    assert not [n for n in scene.log.notes if "cut fault" in n], scene.log.notes


def test_the_turned_example_is_offered_only_for_turned_things():
    """
    Every example in the prompt costs context and steers the answer - a
    hollow box example taught the model to answer everything with hollow
    boxes. So this one appears for a can and not for a bracket.
    """
    from whittle.agent import prompts

    assert "drink_can" in prompts.build_dsl_prompt("Redbull can", "petg", 0.4, 0.2)
    assert "drink_can" in prompts.build_dsl_prompt("a vase", "petg", 0.4, 0.2)
    assert "drink_can" not in prompts.build_dsl_prompt("a bracket", "petg", 0.4, 0.2)
    assert "drink_can" not in prompts.build_dsl_prompt("a widget", "petg", 0.4, 0.2)
