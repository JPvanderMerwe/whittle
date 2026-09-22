"""
What kind of shape a word describes, and therefore which operation makes it.

THE FAILURE THIS EXISTS TO FIX
------------------------------
Asked for "a Redbull can", the engine built a hollowed box with two flat
plates floating 85 mm below the bed. Every number in it was plausible, it
verified watertight, and it was not a can. The model never worked out that a
can is a TURNED shape - a profile spun about an axis - so it never reached
`revolve`, which exists, is tested, and would have made one.

That is not a missing dimension and no corpus of measured objects fixes it. A
mesh contains no language: ten thousand measured cans still do not tell a
model that the word "can" means a body of revolution. The gap is between the
ENGLISH and the OPERATION, and nothing in this program was closing it.

WHY THE TEMPLATES ALREADY HAVE THIS AND LEVEL 2 DID NOT
-------------------------------------------------------
Every template carries a list of what it makes - the enclosure claims
"container, box, bin, crate, tote" - which is why searching for "container"
finds one and why the router can pick it. That is exactly this idea, applied
to the five shapes somebody wrote a template for.

Level 2 is where everything else is built, it is most of what this engine
does (rule 31: "no template fits" is the normal case), and it had no
equivalent. The model got the op reference - nineteen operations with their
fields - and no hint about which of them the thing in front of it is made
with. This is that hint.

WHAT THIS IS NOT
----------------
It does not choose the op, it names the one worth reaching for first, and it
says why in a sentence the model can disagree with. A birdhouse is a box
with a hole and a roof; a "bird bath" is turned. Both contain "bird". So
every entry is advice with its reasoning attached, offered alongside the full
op reference rather than instead of it.

AND IT ONLY EVER NAMES OPS THAT EXIST. An op referred to here and missing
from the DSL would be advice to write a spec that cannot compile - the
worst possible steer, because it reads authoritative. There is a test that
walks every entry against the real op list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Strategy:
    """One family of shapes, the op that makes it, and why."""

    #: The op to reach for. Must be a real DSL op - see the test.
    op: str
    #: Why this shape is made that way, in the words a person would use.
    why: str
    #: What the word describes, for the line the model reads.
    kind: str
    #: Everything that names this kind of thing.
    words: tuple[str, ...]


#: The shapes worth naming, in the order they are checked.
#:
#: ORDERED, AND THE ORDER IS THE POINT. "Bottle opener" contains "bottle" and
#: is a flat plate with a hook, not a turned body; "bird bath" contains "bath"
#: and is turned. So the longer, more specific phrase has to be tested before
#: the bare word it contains, and entries are written longest-phrase-first
#: within each family.
#:
#: EVERY OP NAMED HERE EXISTS. tests/test_vocabulary.py walks this list
#: against whittle.spec.dsl.OP_NAMES, because advice to use an op that is not
#: there is worse than no advice - it reads authoritative and cannot compile.
STRATEGIES: tuple[Strategy, ...] = (
    # -- turned on a lathe -------------------------------------------------
    #
    # THE ONE THAT COST A PART. A can, a bottle, a cup: a single closed
    # profile spun about the vertical axis. `revolve` does it in one op and
    # the model reached for stacked boxes instead.
    Strategy(
        op="revolve",
        kind="a turned shape",
        why=("it is a round body - the same cross-section all the way "
             "around a vertical axis - so it is one profile spun about that "
             "axis, not a stack of discs. `revolve` takes the profile of one "
             "SIDE only; in cut mode it hollows the inside of a vessel"),
        words=(
            "drink can", "soda can", "beer can", "tin can",
            "water bottle", "bottle", "flask", "carafe", "decanter",
            "can", "cup", "mug", "beaker", "tumbler", "glass", "jar",
            "vase", "urn", "goblet", "chalice", "pitcher", "jug",
            # NOT BARE "plate". In maker English a plate is a flat piece of
            # material - "a name plate", "a base plate" - and the dinner
            # sense is the rarer one here. It sent "a name plate for a door"
            # to a lathe.
            "bowl", "dish", "dinner plate", "saucer", "ramekin",
            "pot", "planter", "plant pot", "flowerpot",
            "knob", "handwheel", "wheel", "pulley", "spool", "reel",
            "funnel", "cone", "lampshade", "shade", "dome",
            "candle holder", "egg cup", "bird bath", "vessel",
        ),
    ),

    # -- a drawn outline, given thickness ----------------------------------
    Strategy(
        op="profile_extrude",
        kind="a flat outline given thickness",
        why=("its shape is a single outline seen from one side, the same all "
             "the way through - so draw that outline as points and extrude "
             "it, rather than approximating the curve with boxes"),
        words=(
            "gear", "cog", "sprocket", "cam", "ratchet",
            "gasket", "washer", "shim", "spacer", "template", "stencil",
            # NOT "sign" - what makes a sign a sign is the lettering, and
            # that belongs to emboss_text. A word in two families is a coin
            # toss dressed as advice.
            "silhouette", "outline", "logo", "plaque",
            "bottle opener", "can opener",
            "cookie cutter", "cutter", "jigsaw piece", "star", "heart",
            "arrow", "hexagon", "polygon",
        ),
    ),

    # -- hollow things -----------------------------------------------------
    Strategy(
        op="hollow",
        kind="something that holds something else",
        why=("it is a container, so build the solid body first and then take "
             "the inside out with `hollow` - a wall thickness in one op. A "
             "block with a pocket cut in it is a coaster, not a box"),
        words=(
            "storage box", "parts box", "tool box", "battery box",
            "box", "case", "housing", "enclosure", "shell", "casing",
            "tray", "bin", "caddy", "organiser", "organizer", "tub",
            "container", "crate", "tote", "basket", "bucket",
            "drawer", "sleeve", "cover", "lid",
        ),
    ),

    # -- things that move --------------------------------------------------
    Strategy(
        op="free_joint",
        kind="something with a part that moves",
        why=("it has to move after it is printed, so the moving pair needs a "
             "printed clearance between the faces - `free_joint` places that "
             "gap from the material's own measured figure. Two solids that "
             "touch come off the bed fused"),
        words=(
            "print in place", "print-in-place", "living hinge",
            "hinge", "pivot", "joint", "linkage", "swivel", "articulated",
            "ball joint", "bearing", "gimbal", "clasp", "latch",
        ),
    ),

    Strategy(
        op="articulated_chain",
        kind="a row of linked segments",
        why=("it is a repeated segment joined to the next one so the whole "
             "thing flexes - `articulated_chain` builds the row with the "
             "joints already in it, which is a very long op list by hand"),
        words=(
            "articulated dragon", "flexi", "flexible toy",
            "chain", "snake", "worm", "caterpillar", "dragon", "lizard",
            "bracelet", "cable chain", "drag chain",
        ),
    ),

    # -- repeated features -------------------------------------------------
    Strategy(
        op="pattern_linear",
        kind="the same feature repeated",
        why=("the same feature appears several times in a row, so make it "
             "once and repeat it - `pattern_linear` for a row, "
             "`pattern_polar` for a ring. Writing each one out separately is "
             "where holes end up at uneven spacing"),
        words=(
            "rack", "holder for several", "row of", "grid", "array",
            "comb", "grill", "grille", "louvre", "vent", "slots",
            "pegboard", "honeycomb", "perforated",
        ),
    ),

    # -- a shape that changes along its length -----------------------------
    Strategy(
        op="loft",
        kind="a shape that changes from one end to the other",
        why=("its cross-section is not the same all the way along - it grows, "
             "shrinks or changes shape - so `loft` between the two ends. A "
             "stack of prisms leaves visible steps"),
        words=(
            "adapter", "reducer", "transition", "hopper", "chute",
            "nozzle", "horn", "spout", "taper", "wedge shape",
            "duct", "vent adapter", "hose adapter",
        ),
    ),

    # -- a bent rod --------------------------------------------------------
    Strategy(
        op="arc_rod",
        kind="a bent rod or bar",
        why=("it is a round bar following a curve - `arc_rod` sweeps the "
             "section along the arc, which keeps the thickness constant "
             "round the bend where a stack of cylinders would not"),
        words=(
            "hook", "handle", "grab handle", "loop", "ring", "eyelet",
            "hanger", "bracket arm", "clip arm", "staple", "u bolt",
        ),
    ),

    # -- something to prop a thing up ---------------------------------------
    Strategy(
        op="wedge",
        kind="something that holds an object at an angle",
        why=("it props something up, so the shape is a body with a sloped "
             "face and a lip to stop the thing sliding off - `wedge` makes "
             "the slope in one op, and a `pocket` in the sloped face is the "
             "lip. A vertical slot holds nothing at an angle"),
        words=(
            "phone stand", "tablet stand", "laptop stand", "book stand",
            "monitor stand", "headphone stand", "controller stand",
            "stand", "dock", "cradle", "rest", "prop", "easel",
            "holder for a phone", "phone holder", "wedge",
        ),
    ),

    # -- lettering ---------------------------------------------------------
    Strategy(
        op="emboss_text",
        kind="something with writing on it",
        why=("the words are part of the geometry - `emboss_text` raises or "
             "cuts them into a face at a depth that actually prints, rather "
             "than at a scale the nozzle cannot resolve"),
        words=(
            "name plate", "nameplate", "name tag", "label", "sign",
            "engraved", "embossed", "lettering", "text", "initials",
            "door sign", "desk sign",
        ),
    ),
)


def _normalise(text: str) -> str:
    """Lowercased, punctuation to spaces, so "Red-Bull can" matches "can"."""
    return " %s " % re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def strategies_for(request: str) -> list[Strategy]:
    """
    Which shape families this request is probably about, best first.

    MATCHED ON WHOLE WORDS, with the space padding above doing the work: a
    request for a "scanner" must not match "can", and "chainmail" must not
    match "chain". That is one substring bug away from advising a lathe for a
    flatbed scanner, delivered in the confident voice of a fact.

    LONGER PHRASES WIN. "bottle opener" is a flat plate with a hook and
    "bottle" is turned; the specific phrase is checked first, and once a
    family has matched, the same family is not offered twice.

    MORE THAN ONE IS NORMAL AND USEFUL. A "vented box" is hollow AND
    patterned, and saying both is closer to the truth than picking one.
    """
    text = _normalise(request)
    if not text.strip():
        return []

    # LONGEST PHRASE WINS, ACROSS EVERY FAMILY. Checking each family in turn
    # and taking its first hit is not enough: "bottle opener" is a flat plate
    # and "bottle" is turned, and whichever family sits earlier in the list
    # would have won regardless of which phrase was the better match. So
    # every match is collected with the length of the phrase that made it,
    # and the specific beats the general.
    hits: list[tuple[int, int, Strategy]] = []
    for order, strategy in enumerate(STRATEGIES):
        longest = 0
        for word in strategy.words:
            if (" %s " % word) in text:
                longest = max(longest, len(word))
        if longest:
            hits.append((longest, -order, strategy))

    hits.sort(key=lambda h: (-h[0], -h[1]))

    found: list[Strategy] = []
    for _length, _order, strategy in hits:
        if any(strategy.op == held.op for held in found):
            continue
        found.append(strategy)
    return found


def advice_for(request: str, limit: int = 2) -> list[str]:
    """
    The lines to put in front of the model, or nothing at all.

    TWO AT MOST. The op reference is already in the prompt and this is a
    steer on top of it; a wall of advice competes with the request itself,
    and the second-best guess is usually worth less than the words the person
    actually typed.

    NOTHING WHEN NOTHING MATCHES, which is the ordinary case for anything
    unusual - and the right one. The model still has all nineteen operations
    and the request; what it does not get is a confident push in a direction
    nobody checked.
    """
    return [
        "%s is usually %s: %s. Reach for `%s` first."
        % (_subject(request), strategy.kind, strategy.why, strategy.op)
        for strategy in strategies_for(request)[:limit]
    ]


def _subject(request: str) -> str:
    """
    What to call the thing in the advice line.

    The request itself, trimmed - so the line reads "a Redbull can is usually
    a turned shape" rather than naming the word that happened to match. The
    person's own words are what they will recognise, and rule 32's third
    clause is that anything not understood is reported in the words they
    used.
    """
    said = " ".join((request or "").split())[:60]
    return said or "this"
