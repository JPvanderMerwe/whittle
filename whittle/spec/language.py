"""
English that changes a part's design. CLAUDE.md rule 32.

    "make this roof a triangular roof"  ->  roof_style: mono -> gable
    "make it 200mm tall"                ->  height_mm: 140 -> 200
    "make it a bit wider"               ->  width_mm: 120 -> 138
    "no roof"                           ->  roof: true -> false

WHY THIS IS A PARSER AND NOT A PROMPT
-------------------------------------
The same argument M3 settled for the mesh operations, which this repo has now
paid for twice on the generate path: a 7B model on a CPU does not do anything
ten times out of ten, and an edit that works four times in five is worse than
one that refuses, because the fifth silently changes something nobody asked to
change. So the common case - somebody naming a shape or a dimension of the
thing in front of them - is decided here, deterministically, and the model is
left for the request that genuinely needs composing.

WHAT SEPARATES THIS FROM whittle/edit/intent.py
------------------------------------------------
intent.py reads sentences about a MESH: hollow it, cut it to fit the bed. It
works on somebody else's geometry and cannot do anything a triangle soup cannot
do. This reads sentences about a SPEC: the part is ours, there is a parametric
model behind it, and changing roof_style and rebuilding produces a real
triangular roof rather than a mesh operation that approximates one.

Both are needed and neither replaces the other. Which one applies is decided by
whether the thing open has a spec behind it.

THE VOCABULARY COMES FROM THE SCHEMA
------------------------------------
Nothing here hardcodes "roof" or "birdhouse". A field is reachable by the words
in its own name, plus whatever synonyms it declares. That is what makes this
work for the next template without editing this file - and what makes rule 32
testable rather than aspirational: tests/test_spec_language.py fails a template
whose choices have no English route to them.

Declare synonyms on the field:

    roof_style: Literal["flat", "mono", "gable"] = Field(
        "mono",
        json_schema_extra={"says": {
            "gable": ["triangular", "pitched", "apex", "peaked", "a-frame"],
            "flat":  ["flat", "lid"],
            "mono":  ["lean-to", "single slope"],
        }},
    )
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal, get_args, get_origin

#: How much "a bit" moves a dimension, and how much "much" moves it. Stated
#: rather than guessed, and reported with every change, because a number that
#: appears without a reason is the thing rule 29 exists to stop.
NUDGE = {"a bit": 0.15, "slightly": 0.10, "": 0.25, "much": 0.5, "a lot": 0.5}

#: Words that mean "bigger on this axis", and which axis they mean. The axis
#: names are FIELD SUFFIXES, matched against the schema - "tall" finds
#: height_mm on any template that has one, and finds nothing on one that does
#: not, rather than guessing.
COMPARATIVES: dict[str, tuple[str, float]] = {
    "taller": ("height", +1.0),
    "higher": ("height", +1.0),
    "shorter": ("height", -1.0),
    "lower": ("height", -1.0),
    "wider": ("width", +1.0),
    "narrower": ("width", -1.0),
    "deeper": ("depth", +1.0),
    "shallower": ("depth", -1.0),
    "thicker": ("wall", +1.0),
    "thinner": ("wall", -1.0),
}

#: The adjectives people use for a dimension, against the noun the schema uses.
#: Nobody says "make it 200mm height" - they say "tall". Without these the
#: explicit-dimension path silently misses the most ordinary sentence there is,
#: which is exactly the failure rule 32 names.
AXIS_WORDS: dict[str, list[str]] = {
    "height": ["tall", "high"],
    "width": ["wide", "across"],
    "depth": ["deep", "front to back"],
    "wall": ["thick", "thickness"],
    "roof": ["roof"],
    "entrance": ["entrance", "hole", "opening"],
    "thick": ["thick", "thickness"],
    "dia": ["diameter", "across", "wide"],
    "pitch": ["pitch", "slope", "angle"],
}

#: The dimensions of the OBJECT, as opposed to of a feature on it. "Make it
#: 15cm wide" means these; it does not mean the drain holes, even though a
#: hole has a width too.
PRINCIPAL = ("width", "depth", "height")

#: "make it bigger" has no axis, so it takes every principal dimension at once.
OVERALL = {"bigger": +1.0, "larger": +1.0, "smaller": -1.0, "tinier": -1.0}

#: Units people type, to millimetres.
UNITS = {"mm": 1.0, "millimetre": 1.0, "millimeter": 1.0,
         "cm": 10.0, "centimetre": 10.0, "centimeter": 10.0,
         "m": 1000.0, "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4}

_NUMBER = r"(\d+(?:\.\d+)?)"
_UNIT = (r"(mm|millimetres?|millimeters?|cm|centimetres?|centimeters?|m|in|inch"
         r"|inches|deg|degrees?|\"|°)")

#: Angle units. A _deg field takes the number as written; a length field must
#: never accept one, or "30 degrees" becomes 30 mm somewhere.
ANGLES = {"deg", "degree", "degrees", "°"}


@dataclass
class Change:
    """One parameter moving, and the words that moved it."""

    field: str
    before: Any
    after: Any
    #: The phrase from the person's own sentence that caused this.
    because: str

    #: True when nobody asked for this directly - it followed from something
    #: else. Shown differently, because a number that moved on its own has to
    #: be visible or it is a surprise at the printer.
    derived: bool = False

    def describe(self) -> str:
        def show(v: Any) -> str:
            if isinstance(v, float):
                return ("%g" % v)
            return str(v)

        return "%s %s -> %s" % (self.field, show(self.before), show(self.after))


@dataclass
class Reading:
    """What a sentence asked for, and what it did not."""

    changes: list[Change] = field(default_factory=list)

    #: Phrases that mapped to nothing. RULE 32: said out loud every time, in
    #: the person's own words.
    unmapped: list[str] = field(default_factory=list)

    #: What this template could have done with an instruction like that.
    options: list[str] = field(default_factory=list)

    #: Where the sentence was genuinely ambiguous. Asked, never guessed at.
    questions: list[str] = field(default_factory=list)

    def as_params(self) -> dict[str, Any]:
        return {c.field: c.after for c in self.changes}

    def echo(self) -> str:
        if not self.changes and not self.unmapped and not self.questions:
            return "nothing to do"
        lines = [c.describe() for c in self.changes]
        if self.unmapped:
            lines.append("nothing geometric in: %s" % "; ".join(self.unmapped))
        for question in self.questions:
            lines.append("which did you mean: %s" % question)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# reading the schema
# ---------------------------------------------------------------------------


def _fields(model: type) -> dict[str, Any]:
    return getattr(model, "model_fields", {})


def _says(info: Any) -> dict[str, list[str]]:
    """The synonyms a field declares, or nothing."""
    extra = getattr(info, "json_schema_extra", None) or {}
    if callable(extra):
        return {}
    said = extra.get("says") or {}
    return {k: [w.lower() for w in v] for k, v in said.items()}


def _named_by(info: Any) -> list[str]:
    """
    The words a NUMERIC field declares as naming it.

    Written as a list rather than the per-value dict a choice field uses:

        entrance_dia_mm: float = Field(
            32.0, json_schema_extra={"says": ["entrance", "hole", "opening"]})

    This is what settles "make the entrance 28mm" between entrance_dia_mm and
    entrance_height_mm - both contain the word "entrance", and only one of them
    is what a person means by it.
    """
    extra = getattr(info, "json_schema_extra", None) or {}
    if callable(extra):
        return []
    said = extra.get("says")
    return [w.lower() for w in said] if isinstance(said, list) else []


def choices_of(info: Any) -> tuple[str, ...]:
    """The legal values of a Literal field, or ()."""
    annotation = getattr(info, "annotation", None)
    if get_origin(annotation) is Literal:
        return tuple(str(v) for v in get_args(annotation))
    return ()


def _is_bool(info: Any) -> bool:
    return getattr(info, "annotation", None) is bool


def _is_number(info: Any) -> bool:
    annotation = getattr(info, "annotation", None)
    if annotation in (int, float):
        return True
    # `float | None` is how an "unset means derive it" dimension is written.
    return float in get_args(annotation or ())


def words_for(name: str) -> list[str]:
    """
    The English words that name a field.

    `roof_pitch_deg` is reachable by "roof" and "pitch"; the unit suffix is not
    a word anybody says. Kept deliberately dumb - a longer list would start
    matching fields nobody meant.
    """
    parts = [p for p in name.split("_") if p not in ("mm", "deg", "style", "count")]
    words = list(parts)
    for part in parts:
        for extra in AXIS_WORDS.get(part, []):
            if extra not in words:
                words.append(extra)
    return words or [name]


# ---------------------------------------------------------------------------
# reading a sentence
# ---------------------------------------------------------------------------


def read(sentence: str, model: type, current: dict[str, Any]) -> Reading:
    """
    Turn one English instruction into parameter changes on `model`.

    `current` is the part's parameters as they stand, because almost every
    instruction here is relative to them - "taller" has no meaning without a
    height, and reporting `before` is what lets the UI show a diff rather than
    a new number appearing from nowhere.
    """
    reading = Reading()
    text = " %s " % sentence.lower().strip()
    if not text.strip():
        return reading

    fields = _fields(model)

    # A SPEC ONLY LISTS WHAT IT OVERRODE. parts/birdhouse/spec.yaml names five
    # parameters and the template has thirty, so `current` is full of holes -
    # and a change reported as "roof_style None -> gable" is telling somebody
    # their roof had no style, which is both wrong and alarming. The schema's
    # own default is what the part was actually built with.
    current = {**{name: info.default for name, info in fields.items()
                  if info.default is not None}, **current}

    claimed: list[tuple[int, int]] = []

    def claim(match: re.Match) -> None:
        claimed.append((match.start(), match.end()))

    def already(name: str) -> bool:
        return any(c.field == name for c in reading.changes)

    # -- 1. named shapes: "a triangular roof", "flat lid" -------------------
    #
    # FIRST, because a shape word is the most specific thing in a sentence and
    # the one a person is most likely to have meant. "Make the roof triangular
    # and 20mm thick" should set the style AND the thickness.
    for name, info in fields.items():
        options = choices_of(info)
        if not options:
            continue
        said = _says(info)
        for value in options:
            if str(current.get(name)) == value:
                continue  # already that; saying so is not a change
            for word in [value.lower()] + said.get(value, []):
                pattern = re.compile(r"\b%s\b" % re.escape(word))
                hit = pattern.search(text)
                if hit:
                    reading.changes.append(Change(
                        field=name, before=current.get(name), after=value,
                        because=word))
                    claim(hit)
                    break
            if already(name):
                break

    # -- 2. explicit dimensions: "200mm tall", "the entrance 28mm" ---------
    #
    # ONE FIELD PER NUMBER, AND IT HAS TO BE NAMED. The first version of this
    # let every field whose words matched take the number, so "make it 15cm
    # wide" set the width AND the entrance diameter AND the drain diameter AND
    # the mounting hole, because a diameter is a width too. Changing three
    # things nobody asked about is worse than changing none: it is invisible
    # in a render and it comes out of the printer wrong.
    #
    # So a number goes to exactly one field, which must either declare the
    # word, own the word in its name, or be a principal dimension of the object
    # itself. A tie is a question, not four edits.
    for number, unit, span in _numbers(text):
        angle = unit in ANGLES
        best: list[tuple[int, int, str]] = []

        for name, info in fields.items():
            if already(name) or not _is_number(info):
                continue
            if angle != name.endswith("_deg"):
                continue  # degrees never land in a length, or the reverse

            own = [w for w in name.split("_") if w not in ("mm", "deg")]
            declared = _named_by(info)
            where = _nearest(text, declared, span)
            score = 0
            if where is not None:
                score = 3
            else:
                where = _nearest(text, own, span)
                if where is not None:
                    score = 2
                elif any(name.startswith("%s_" % axis) or name == "%s_mm" % axis
                         for axis in PRINCIPAL):
                    where = _nearest(text, words_for(name), span)
                    score = 1 if where is not None else 0

            if score:
                best.append((score, -abs(where - span[0]), name))

        if not best:
            continue
        best.sort(reverse=True)
        if len(best) > 1 and best[0][:2] == best[1][:2]:
            # AMBIGUITY ASKS ONCE. Two fields with an equal claim on the same
            # number is the one case where guessing is unforgivable.
            reading.questions.append(
                "%g%s could be %s" % (number, unit,
                                      " or ".join(sorted(b[2] for b in best
                                                         if b[:2] == best[0][:2]))))
            continue

        name = best[0][2]
        value = number if angle else number * UNITS[_unit_key(unit)]
        reading.changes.append(Change(
            field=name, before=current.get(name),
            after=_clamp(fields[name], value),
            because=text[span[0]:span[1]].strip()))
        claimed.append(span)

    # -- 3. comparatives: "taller", "a bit wider" --------------------------
    for word, (axis, direction) in COMPARATIVES.items():
        hit = re.search(r"\b%s\b" % word, text)
        if not hit:
            continue
        target = _field_ending(fields, axis)
        if target is None:
            reading.unmapped.append(word)
            continue
        if already(target):
            continue
        before = current.get(target)
        if not isinstance(before, (int, float)):
            continue
        step = _nudge(text)
        reading.changes.append(Change(
            field=target, before=before,
            after=_clamp(fields[target], before * (1.0 + direction * step)),
            because="%s%s" % (_nudge_word(text), word)))
        claim(hit)

    # -- 4. overall size: "make it bigger" ---------------------------------
    for word, direction in OVERALL.items():
        hit = re.search(r"\b%s\b" % word, text)
        if not hit:
            continue
        step = _nudge(text)
        for axis in ("width", "depth", "height"):
            target = _field_ending(fields, axis)
            if target is None or already(target):
                continue
            before = current.get(target)
            if not isinstance(before, (int, float)):
                continue
            reading.changes.append(Change(
                field=target, before=before,
                after=_clamp(fields[target], before * (1.0 + direction * step)),
                because="%s%s" % (_nudge_word(text), word)))
        claim(hit)

    # -- 4b. keep the shape ------------------------------------------------
    #
    # "MAKE IT 200MM TALL" MEANS THE OBJECT, NOT ONE AXIS OF IT. Nobody
    # picturing a birdhouse twice as tall pictures the same footprint with a
    # stretched box on it - they picture a bigger birdhouse. So when exactly
    # one principal dimension is named and the others are not, the others
    # follow by the same factor and the proportions survive.
    #
    # WHAT DELIBERATELY DOES NOT FOLLOW, and this is the whole care of it:
    # wall thickness, clearances and functional holes. A wall is a
    # manufacturing constraint set by the nozzle, not a proportion, and an
    # entrance is 32 mm because that is the size of the bird - scaling either
    # with the body is how a part comes out unprintable or useless while
    # looking correct on screen. Rule 15: the departure is reported with its
    # numeric factor rather than done quietly.
    named = [c for c in reading.changes
             if not c.derived and _axis_of(c.field) in PRINCIPAL]
    if len(named) == 1:
        driver = named[0]
        before = driver.before
        if isinstance(before, (int, float)) and before > 0:
            factor = float(driver.after) / float(before)
            if abs(factor - 1.0) > 1e-9:
                for axis in PRINCIPAL:
                    target = _field_ending(fields, axis)
                    if target is None or already(target):
                        continue
                    was = current.get(target)
                    if not isinstance(was, (int, float)):
                        continue
                    reading.changes.append(Change(
                        field=target, before=was,
                        after=_clamp(fields[target], was * factor),
                        because="kept in proportion, %s x%.3f"
                                % (driver.field, factor),
                        derived=True))

    # -- 5. features on and off: "no roof", "add drainage" -----------------
    for name, info in fields.items():
        if already(name) or not _is_bool(info):
            continue
        for word in words_for(name):
            off = re.search(r"\b(?:no|without|remove|delete|drop)\s+(?:the\s+|a\s+)?%s\b"
                            % re.escape(word), text)
            on = re.search(r"\b(?:add|with|include|give it)\s+(?:the\s+|a\s+)?%s\b"
                           % re.escape(word), text)
            hit = off or on
            if not hit:
                continue
            after = bool(off is None)
            if current.get(name) == after:
                continue
            reading.changes.append(Change(
                field=name, before=current.get(name), after=after,
                because=hit.group(0).strip()))
            claim(hit)
            break

    # -- 6. what was not understood ----------------------------------------
    reading.unmapped.extend(_leftover(text, claimed))
    if reading.unmapped and not reading.changes:
        reading.options = _options(fields, current)

    return reading


def _axis_of(name: str) -> str | None:
    """Which principal axis a field name is, if it is one of them at all."""
    for axis in PRINCIPAL:
        if name == "%s_mm" % axis or name == axis:
            return axis
    return None


def _unit_key(unit: str) -> str:
    """The UNITS key for a unit as it was typed: "centimetres" -> "cm"."""
    unit = unit.lower()
    if unit in UNITS:
        return unit
    for key in UNITS:
        if unit.startswith(key):
            return key
    return "mm"


def _numbers(text: str) -> list[tuple[float, str, tuple[int, int]]]:
    """Every "<number><unit>" in the sentence, with where it sits."""
    out = []
    for hit in re.finditer(r"\b%s\s*%s" % (_NUMBER, _UNIT), text):
        out.append((float(hit.group(1)), hit.group(2).lower(),
                    (hit.start(), hit.end())))
    return out


def _nearest(text: str, words: list[str], span: tuple[int, int]) -> int | None:
    """
    Where the closest of `words` sits to a number, if any is close enough.

    A WINDOW, not the whole sentence. "Make it 200mm tall and put the entrance
    30mm down" has two numbers and two fields, and matching across the whole
    string pairs them at random.
    """
    best = None
    for word in words:
        for hit in re.finditer(r"\b%s\b" % re.escape(word), text):
            distance = min(abs(hit.start() - span[1]), abs(span[0] - hit.end()))
            if distance <= 24 and (best is None or distance < abs(best - span[0])):
                best = hit.start()
    return best


def _field_ending(fields: dict[str, Any], axis: str) -> str | None:
    """
    The numeric field this template calls its `axis`.

    Exact-ish rather than fuzzy: `height_mm` for "height", and nothing at all
    if the template has no such dimension. A template with no width should
    refuse "wider" rather than move whatever field sorts first.
    """
    for suffix in ("%s_mm" % axis, axis):
        if suffix in fields and _is_number(fields[suffix]):
            return suffix
    for name, info in fields.items():
        if name.startswith("%s_" % axis) and _is_number(info):
            return name
    return None


def _nudge(text: str) -> float:
    for word, amount in NUDGE.items():
        if word and re.search(r"\b%s\b" % word, text):
            return amount
    return NUDGE[""]


def _nudge_word(text: str) -> str:
    for word in NUDGE:
        if word and re.search(r"\b%s\b" % word, text):
            return "%s " % word
    return ""


def _clamp(info: Any, value: float) -> float:
    """
    Keep a nudge inside the field's own declared bounds.

    The bounds are on the schema already - `gt`, `le` - and a comparative that
    walks a dimension past them would be refused by pydantic with a message
    about a number the person never typed. Stopping here means "make it taller"
    against the ceiling does the most it can rather than failing.
    """
    low = high = None
    for meta in getattr(info, "metadata", []) or []:
        for attr, name in (("gt", "low"), ("ge", "low"), ("lt", "high"), ("le", "high")):
            if hasattr(meta, attr):
                bound = getattr(meta, attr)
                if name == "low":
                    low = bound if low is None else max(low, bound)
                else:
                    high = bound if high is None else min(high, bound)
    if low is not None:
        value = max(value, low + 1e-6)
    if high is not None:
        value = min(value, high)
    return round(value, 3)


def _leftover(text: str, claimed: list[tuple[int, int]]) -> list[str]:
    """
    The clauses of the sentence nothing matched.

    RULE 32, third part: what was not understood is said out loud in the words
    the person used. Split on the joins people actually type, and a clause is
    reported only if no match landed inside it - so "make it taller and look
    fierce" reports the poetry and keeps the height.
    """
    out: list[str] = []
    for piece in re.split(r"\band\b|[,.;]", text):
        stripped = piece.strip()
        if len(stripped) < 3:
            continue
        start = text.index(piece)
        end = start + len(piece)
        if any(s < end and e > start for s, e in claimed):
            continue
        if not re.search(r"[a-z]", stripped):
            continue
        # "make it" on its own is a carrier phrase, not an instruction.
        if re.fullmatch(r"(please\s+)?(can you\s+)?(make|turn|set|give)\s*(it|this|them)?",
                        stripped):
            continue
        out.append(stripped)
    return out


def _options(fields: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """
    What this template could actually have been asked, for when nothing landed.

    Section 12's rule, applied to the spec: a vague ask gets the real options
    rather than a shrug. Built from the schema, so it is true of whatever
    template is in front of the person.
    """
    out: list[str] = []
    for name, info in fields.items():
        options = choices_of(info)
        if options:
            said = _says(info)
            words = [said.get(v, [v])[0] for v in options]
            out.append("%s: %s" % (" ".join(words_for(name)), ", ".join(words)))
    for axis in ("width", "depth", "height"):
        target = _field_ending(fields, axis)
        if target and isinstance(current.get(target), (int, float)):
            out.append("%s: %g mm now" % (axis, current[target]))
    return out[:6]
