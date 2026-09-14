"""
Words to operations. Build plan v8 section 12.

    "hollow it to 2mm and cut it to fit my bed"
        -> hollow(wall_mm=2.0), cut_plane(at_mm=<from the bed>, keep=lower)

INTENT EXTRACTION PRODUCES AN OPERATION, NEVER GEOMETRY. Nothing here touches
a mesh. It reads a sentence and returns what to put on the stack, which is
what makes every edit a slider the user tunes afterwards rather than a
one-shot they have to re-ask for - section 12's first rule, and the cost model
as much as the experience.

WHY THIS IS A PARSER AND NOT A PROMPT
--------------------------------------
M3's acceptance is that a sentence produces the right two operations "ten
times out of ten". A 7B model on a CPU does not do anything ten times out of
ten - measured in this repo, twice, on the generate path: four attempts at one
request produced the identical wrong answer four times, and a later run lost
384 seconds to a JSON spelling detail.

whittle already has the right precedent in whittle/agent/command.py: the command
line parses deterministically, in Python, once, for both clients, and it
refuses to guess. `wall` with no number is an incomplete command rather than a
default. This follows it exactly.

A model still has a job here - a sentence this cannot read goes to it - but
the common vocabulary resolves without one, which is what makes it reliable
and free.

WHAT IS NEVER DONE
-------------------
Nothing is invented. A phrase that carries no geometric meaning goes into
`unmapped` and is shown, every time: section 12 is blunt that "make it look
fierce" is not a geometric operation and "pretending otherwise is how trust
dies". A vague ask that DOES have real answers - "make it stronger" - returns
those answers as options rather than picking one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Millimetres per unit, for the units people type.
UNITS = {
    "mm": 1.0, "millimetre": 1.0, "millimeter": 1.0, "millimetres": 1.0,
    "millimeters": 1.0,
    "cm": 10.0, "centimetre": 10.0, "centimeter": 10.0, "centimetres": 10.0,
    "centimeters": 10.0,
    "m": 1000.0, "metre": 1000.0, "meter": 1000.0,
    "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4,
}

_NUMBER = r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mm|cm|m|in|inch(?:es)?|millimet(?:re|er)s?|centimet(?:re|er)s?|met(?:re|er)s?|\")?"


@dataclass
class Proposal:
    """One operation the sentence asked for, ready to go on the stack."""

    operation: str
    parameters: dict[str, Any] = field(default_factory=dict)
    selector: dict[str, Any] = field(default_factory=lambda: {"mode": "all"})

    #: How sure the reading is. 1.0 means a phrase matched exactly; anything
    #: lower means something was inferred and the UI should show it before
    #: applying - section 12: "Show the selection before applying it".
    confidence: float = 1.0

    #: What the sentence said that produced this, quoted back.
    source: str = ""

    #: Parameters the sentence did not give that were filled from the machine
    #: or the model, named so the diff can show them. Section 13.3: "Every
    #: language edit shows a parameter diff".
    derived: dict[str, str] = field(default_factory=dict)

    def describe(self) -> str:
        inner = ", ".join("%s %s" % (k, _tidy(v))
                          for k, v in sorted(self.parameters.items()))
        return "%s(%s)" % (self.operation, inner)


@dataclass
class Question:
    """One thing the sentence left genuinely open. Asked once, with options."""

    about: str
    prompt: str
    options: list[str] = field(default_factory=list)


@dataclass
class Reading:
    """Everything a sentence produced: operations, questions, and leftovers."""

    proposals: list[Proposal] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        if not self.proposals:
            return 0.0
        return min(p.confidence for p in self.proposals)

    def echo(self) -> str:
        """
        What to print back. The same words the panel controls use, both ways -
        the rule whittle/agent/command.py already follows.
        """
        lines = [p.describe() for p in self.proposals]
        for question in self.questions:
            lines.append("? %s" % question.prompt)
        for phrase in self.unmapped:
            lines.append("- nothing geometric in %r" % phrase)
        return "\n".join(lines) if lines else "nothing to do"


def _tidy(value: Any) -> str:
    if isinstance(value, float):
        text = ("%.3f" % value).rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def _measure(text: str) -> float | None:
    """The first length in a phrase, in millimetres, or None."""
    match = re.search(_NUMBER, text, re.I)
    if match is None:
        return None
    value = float(match.group("value"))
    unit = (match.group("unit") or "mm").lower()
    return value * UNITS.get(unit, 1.0)


# ---------------------------------------------------------------------------
# the vocabulary
# ---------------------------------------------------------------------------

#: A vague ask that has real answers. Section 12: "Offer the operation the
#: user actually needs" - respond with the options rather than guessing which
#: one they meant.
VAGUE = {
    "stronger": Question(
        about="stronger",
        prompt="\"Stronger\" can mean several things. Which?",
        options=["thicken_thin_walls - more material everywhere",
                 "hollow with a thicker wall - if it is already hollow",
                 "rotate - so the layers run across the load rather than along it"],
    ),
    "lighter": Question(
        about="lighter",
        prompt="\"Lighter\" can mean several things. Which?",
        options=["hollow - take the middle out",
                 "scale_uniform - make the whole thing smaller"],
    ),
    "smoother": Question(
        about="smoother",
        prompt="Smoothing is not built yet. What is the surface problem?",
        options=["the model is faceted - that is smooth, which is M6",
                 "the layers show - that is a slicer setting, not the model"],
    ),
}

#: Phrases with no geometric meaning at all. Listed so the refusal can be
#: specific rather than "could not understand", and so a future model call
#: does not waste a trip on them.
NOT_GEOMETRY = re.compile(
    r"\b(fierce|scary|cool|nice|beautiful|pretty|realistic|detailed|"
    r"cute|angry|happy|better looking|prettier)\b", re.I)


def _hollow(clause: str) -> Proposal | None:
    if not re.search(r"\bhollow(ed|ing)?\b", clause, re.I):
        return None
    wall = _measure(clause)
    proposal = Proposal("hollow", {}, source=clause)
    if wall is not None:
        proposal.parameters["wall_mm"] = wall
    else:
        # NO NUMBER IS NOT A DEFAULT. The command parser's rule: a command
        # that silently invents a dimension is worse than one that fails. The
        # operation still goes on the stack - hollowing was clearly asked for
        # - with its own default, flagged as derived so the diff shows it.
        proposal.derived["wall_mm"] = "not given; the operation's default"
        proposal.confidence = 0.8
    return proposal


def _thicken(clause: str) -> Proposal | None:
    if not re.search(r"\bthick(en|er)?\b.*\bwall|wall.*\bthick(en|er)?\b",
                     clause, re.I):
        return None
    minimum = _measure(clause)
    proposal = Proposal("thicken_thin_walls", {}, source=clause)
    if minimum is not None:
        proposal.parameters["minimum_mm"] = minimum
    else:
        proposal.derived["minimum_mm"] = "not given; two nozzle widths"
        proposal.confidence = 0.8
    return proposal


def _scale(clause: str) -> Proposal | None:
    # "make it 80mm tall", "scale to 120 mm"
    tall = re.search(r"\b(\d+(?:\.\d+)?)\s*(mm|cm|m|in|inch(?:es)?)?\s*"
                     r"(tall|high|long|wide|across)\b", clause, re.I)
    if tall:
        size = _measure(tall.group(0))
        axis = "z" if tall.group(3).lower() in ("tall", "high") else "x"
        return Proposal("scale_to_height",
                        {"height_mm": size, "axis": axis}, source=clause)

    times = re.search(r"\b(?:scale|resize)\b.*?(\d+(?:\.\d+)?)\s*(?:x|times)",
                      clause, re.I)
    if times:
        return Proposal("scale_uniform",
                        {"factor": float(times.group(1))}, source=clause)

    if re.search(r"\b(bigger|larger|smaller)\b", clause, re.I):
        # A direction with no amount. The operation is right and the number is
        # the user's, so it goes on with its default and says so.
        proposal = Proposal("scale_uniform", {}, source=clause, confidence=0.6)
        proposal.derived["factor"] = "no amount given - drag it"
        return proposal
    return None


def _floaters(clause: str) -> Proposal | None:
    if re.search(r"\b(floaters?|debris|specks?|stray|loose bits?|fragments?)\b",
                 clause, re.I) or re.search(
                     r"\bclean(\s+it)?\s+up\b", clause, re.I):
        return Proposal("remove_floaters", {}, source=clause)
    return None


def _flatten(clause: str) -> Proposal | None:
    if not re.search(r"\bflat(ten)?\b.*\b(base|bottom)\b|\bstand\b|"
                     r"\b(base|bottom)\b.*\bflat", clause, re.I):
        return None
    depth = _measure(clause)
    proposal = Proposal("flatten_base", {}, source=clause)
    if depth is not None:
        proposal.parameters["depth_mm"] = depth
    else:
        proposal.derived["depth_mm"] = "not given; the operation's default"
        proposal.confidence = 0.8
    return proposal


def _cut(clause: str) -> Proposal | None:
    if not re.search(r"\b(cut|split|slice|chop)\b", clause, re.I):
        return None

    proposal = Proposal("cut_plane", {}, source=clause)

    # "to fit my bed" is a GOAL, not a number. The operation is known; the
    # parameter comes from the machine and the model, and is marked derived so
    # the user sees where it came from rather than a figure appearing.
    if re.search(r"\bfit\b.*\bbed\b|\bbed\b.*\bfit\b|\bin half\b|\bto fit\b",
                 clause, re.I):
        proposal.parameters["keep"] = "both"
        proposal.derived["at_mm"] = "from the bed height and the model"
        proposal.confidence = 0.9
        return proposal

    at = _measure(clause)
    if at is not None:
        proposal.parameters["at_mm"] = at
    else:
        proposal.derived["at_mm"] = "no height given - drag it"
        proposal.confidence = 0.6

    if re.search(r"\b(keep|take)\b.*\b(top|upper)\b", clause, re.I):
        proposal.parameters["keep"] = "upper"
    elif re.search(r"\b(keep|take)\b.*\b(bottom|lower)\b", clause, re.I):
        proposal.parameters["keep"] = "lower"
    return proposal


def _mirror(clause: str) -> Proposal | None:
    if not re.search(r"\bmirror|\bflip\b", clause, re.I):
        return None
    axis = "x"
    for name in ("x", "y", "z"):
        if re.search(r"\b%s\b" % name, clause, re.I):
            axis = name
            break
    return Proposal("mirror", {"axis": axis}, source=clause)


def _rotate(clause: str) -> Proposal | None:
    match = re.search(r"\b(?:rotate|turn|spin)\b[^\d]*(\d+(?:\.\d+)?)\s*"
                      r"(?:deg|degrees?)?", clause, re.I)
    if not match:
        return None
    axis = "z"
    for name in ("x", "y", "z"):
        if re.search(r"\babout\s+%s\b|\b%s\s*axis\b" % (name, name),
                     clause, re.I):
            axis = name
            break
    return Proposal("rotate",
                    {"degrees": float(match.group(1)), "axis": axis},
                    source=clause)


#: Order matters: the first reader that claims a clause wins it. `thicken`
#: comes before `hollow` because "thicken the walls" contains neither, and
#: before `scale` because "thicker" is not "bigger".
READERS = (_thicken, _hollow, _floaters, _flatten, _cut, _mirror, _rotate,
           _scale)


def _clauses(sentence: str) -> list[str]:
    """
    Split on the joins people actually use.

    "hollow it to 2mm and cut it to fit my bed" is two instructions, and
    reading it as one is how a sentence produces one operation where it asked
    for two.
    """
    parts = re.split(r"\s*(?:,|;|\band then\b|\bthen\b|\band\b)\s*",
                     sentence, flags=re.I)
    return [p.strip() for p in parts if p.strip()]


def read(sentence: str) -> Reading:
    """
    Turn a sentence into operations, questions and leftovers.

    Never raises on input it cannot read: an unreadable clause is a fact about
    the sentence, reported in `unmapped`, not an error.
    """
    reading = Reading()
    if not sentence or not sentence.strip():
        return reading

    for clause in _clauses(sentence):
        # A vague word with real answers gets the answers, not a guess.
        vague = None
        for word, question in VAGUE.items():
            if re.search(r"\b%s\b" % word, clause, re.I):
                vague = question
                break
        if vague is not None:
            if not any(q.about == vague.about for q in reading.questions):
                reading.questions.append(vague)
            continue

        proposal = None
        for reader in READERS:
            proposal = reader(clause)
            if proposal is not None:
                break

        if proposal is not None:
            reading.proposals.append(proposal)
            continue

        # Nothing geometric in it. Said plainly rather than swallowed.
        if NOT_GEOMETRY.search(clause) or len(clause.split()) <= 12:
            reading.unmapped.append(clause)
        else:
            reading.unmapped.append(clause)

    return reading


def resolve(reading: Reading, *, bounds_mm, bed_mm, nozzle_mm: float = 0.4) -> Reading:
    """
    Fill in the parameters that come from the machine rather than the sentence.

    "cut it to fit my bed" names an operation and a goal. The height to cut at
    is arithmetic on the model and the bed, and doing it here rather than in
    the parser keeps the parser a parser - it reads words, it does not measure
    models.

    `bounds_mm` IS THE BOUNDS AND NOT THE EXTENTS, which is a bug this had.
    A cut plane is a position in the model's own coordinates, and a model that
    happens to be centred on the origin runs -150 to +150 rather than 0 to
    300. Given the extents alone this computed 150 and put the plane exactly
    on the top face, where it cut nothing: "the cut at z 150.00 mm is outside
    the model, which runs -150.00 to 150.00".
    """
    import numpy as np

    low = np.asarray(bounds_mm[0], dtype=float)
    high = np.asarray(bounds_mm[1], dtype=float)
    for proposal in reading.proposals:
        if proposal.operation != "cut_plane":
            continue
        if "at_mm" in proposal.parameters:
            continue
        if "from the bed" not in proposal.derived.get("at_mm", ""):
            continue

        if not bed_mm:
            proposal.derived["at_mm"] = (
                "no bed is configured, so there is no height to fit to")
            proposal.confidence = 0.4
            continue

        floor = float(low[2])
        height = float(high[2] - low[2])
        limit = float(bed_mm[2])
        if height <= limit:
            # IT ALREADY FITS. Cutting it anyway because the sentence said
            # "cut" would be obeying the words over the intent - the user
            # asked for it to fit the bed, and it does.
            proposal.parameters["at_mm"] = round(floor + height / 2.0, 2)
            proposal.derived["at_mm"] = (
                "the model is %.0f mm and the bed takes %.0f, so it already "
                "fits - this cuts it in half instead" % (height, limit))
            proposal.confidence = 0.5
        else:
            pieces = int(height // limit) + 1
            proposal.parameters["at_mm"] = round(floor + height / pieces, 2)
            proposal.derived["at_mm"] = (
                "%.0f mm tall against a %.0f mm bed, so %d pieces of %.0f mm"
                % (height, limit, pieces, height / pieces))
    return reading


def apply_to(reading: Reading, stack: Any) -> list[Any]:
    """
    Put a reading's operations on an edit stack.

    SEPARATE FROM READING ON PURPOSE. Section 12: "Show the selection before
    applying it." A caller reads first, shows the user what it understood and
    what it did not, and applies only when they say so - which is impossible
    if parsing and applying are the same call.

    Returns the EditOps added, so the caller can show the parameter diff that
    section 13.3 asks for.
    """
    added = []
    for proposal in reading.proposals:
        op = stack.add(proposal.operation, **proposal.parameters)
        added.append(op)
    return added


def diff(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """
    What changed, in the form section 13.3 asks for: `wall_mm 1.2 -> 2.0`.

    Every language edit shows one of these, because a number that changed
    without being shown changing is a number nobody can trust.
    """
    lines = []
    for name in sorted(set(before) | set(after)):
        was, now = before.get(name), after.get(name)
        if was is None:
            lines.append("%s %s" % (name, _tidy(now)))
        elif now is not None and _tidy(was) != _tidy(now):
            # BOTH SIDES AT THE SAME PRECISION. The plan's own example is
            # "wall_mm 1.2 -> 2.0", and trimming that to "1.2 -> 2" makes the
            # two ends of one change look like different kinds of number.
            lines.append("%s %s -> %s" % (name, *_pair(was, now)))
    return lines


def _pair(was: Any, now: Any) -> tuple[str, str]:
    """Two numbers written to the same number of decimals."""
    if not isinstance(was, (int, float)) or not isinstance(now, (int, float)):
        return str(was), str(now)
    places = max(_decimals(was), _decimals(now))
    return ("%.*f" % (places, was), "%.*f" % (places, now))


def _decimals(value: Any) -> int:
    text = ("%.6f" % float(value)).rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0
