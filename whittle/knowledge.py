"""
What this machine has actually measured, offered back when something similar
is asked for.

THE PROBLEM THIS SOLVES
-----------------------
Somebody types "a phone stand". Nothing in that sentence is a dimension, and
the engine has to produce a real object in millimetres anyway - so every
number in the result is chosen rather than given (rule 14, and the ordinary
case rather than an edge one). Today those numbers come out of a 7B model's
head. It has never held a phone.

But this machine has measured phone stands. Every model brought in from
Printables, Thingiverse or Creality Cloud is measured on the way in -
envelope, volume, pieces, whether it is closed - and every part whittle has
built carries the same figures in its regression. That is a body of evidence
about how big real objects of a given kind are, sitting on disk, and nothing
was reading it.

So: when a request arrives, find the things already measured that the request
is about, and hand the model their dimensions as FACTS. "A phone stand" stops
being a guess from nowhere and starts from the four phone stands in the
library, each named, each with the size somebody actually printed.

WHAT THIS IS NOT, AND THE DISTINCTION MATTERS
---------------------------------------------
It is not a model trained on your files, and it must never become one. Rule 9
forbids inventing a dimension; rule 13 says measure, never estimate; rule 14
says an unmeasurable dimension becomes a named parameter marked ASSUMPTION.
A statistical blend of four phone stands is a number nobody measured and
nobody can trace, which is exactly the thing those rules exist to stop.

Every figure that leaves here therefore carries WHERE IT CAME FROM: the part
it was measured off, and whether that part was built here or brought in. The
model is given evidence and told it is evidence. What it does with it is
reported in the spec, and the spec is checked the same way it always was.

IT IS ALSO NOT A SEARCH RANKING PROBLEM. There is no corpus of a million
things here and there is not going to be; this is a personal library of
hundreds. Word overlap against the same haystack the gallery searches is
enough, it is explainable, and it costs a millisecond. A vector index would
be a dependency, a build step and an answer nobody can account for.

FULLY OFFLINE, like everything else. It reads directories.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

#: Words that appear in nearly every request and name nothing.
#:
#: Kept deliberately short. A long stop list starts throwing away words that
#: matter - "box" and "case" are stop words in ordinary English writing and
#: are the entire subject here.
STOP_WORDS = frozenset("""
a an the my some this that for with and or of to in on at is it
make made making build built please you i want need
mm cm thick thin wide tall long high deep
""".split())

#: NOT "can". It was in the list to strip "can you make me a..." and it took
#: the noun with it: "a Redbull can" matched nothing at all, on a corpus
#: holding a dozen drink cans. A word that names a thing this program builds
#: earns its place over the phrasing it occasionally costs - and the phrasing
#: is rare here, because people type "a bracket" rather than asking politely.

#: How many measured neighbours are worth showing.
#:
#: Four, because the point is a sense of scale rather than a survey: a model
#: handed twenty examples spends its context on them and starts copying one
#: wholesale, which is the failure this is meant to prevent, arrived at from
#: the other side.
DEFAULT_LIMIT = 4


@dataclass
class Known:
    """One thing that has been measured, and what it is called."""

    name: str
    #: 'made here' or 'brought in' - provenance, in the words a person uses.
    origin: str
    #: Where it lives, so a claim can be chased back to the file.
    directory: str
    envelope_mm: tuple[float, float, float] | None = None
    volume_cm3: float | None = None
    bodies: int | None = None
    #: What the file was called when it arrived, for an import.
    source_name: str = ""
    #: Everything it answers to, lowercased. The gallery's haystack.
    words: str = ""
    #: How well it matched the request that found it. Set by `closest`.
    score: float = 0.0
    #: Which request words it matched on, so the reason can be shown.
    matched: list[str] = field(default_factory=list)

    def line(self) -> str:
        """
        One line a model can read, carrying its own provenance.

        THE SOURCE IS PART OF THE FACT. A dimension with no source is exactly
        the kind of number this file exists to avoid producing: the model
        must be able to tell "measured off a thing somebody printed" from
        "a number that appeared", and so must anybody reading the spec
        afterwards.
        """
        bits = [self.name]
        if self.envelope_mm:
            bits.append("%s mm"
                        % " x ".join("%.0f" % v for v in self.envelope_mm))
        if self.volume_cm3:
            bits.append("%.1f cm3" % self.volume_cm3)
        if self.bodies and self.bodies > 1:
            bits.append("%d pieces" % self.bodies)
        bits.append(self.origin)
        return "  ".join(bits)


def words_of(text: str) -> list[str]:
    """The words of a request that name something, lowercased."""
    found = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [w for w in found if w not in STOP_WORDS and not w.isdigit()]


def index(roots: Iterable[str | Path] | None = None) -> list[Known]:
    """
    Everything on this machine that has been measured, as evidence.

    BOTH KINDS COUNT. A part whittle built is measured by its own regression;
    a model somebody brought in is measured at ingest by the same code. They
    are different provenance and equally real, and the one that is usually
    more useful is the import - somebody chose to download it, which means it
    is a shape that gets printed.

    Anything with no envelope is left out. A draft that never built has
    nothing to say about how big this kind of thing is.
    """
    from whittle import library

    out: list[Known] = []
    # ONE MEASUREMENT PER THING, NOT PER BUILD.
    #
    # A refine writes a new part and leaves the old one alone, so four tweaks
    # to a birdhouse are four directories with the same name and, when the
    # tweak did not change the outside, the same envelope. Handed to a model
    # as four separate pieces of evidence they read as four independent
    # observations - and they filled every slot, so a request for a birdhouse
    # saw one object four times and nothing else.
    seen: set[tuple] = set()
    for entry in library.scan(roots):
        envelope = getattr(entry, "envelope_mm", None)
        if not envelope or len(tuple(envelope)) != 3:
            continue
        if not all(float(v) > 0 for v in envelope):
            continue
        shape = (str(entry.name), tuple(round(float(v), 1) for v in envelope))
        if shape in seen:
            continue
        seen.add(shape)

        imported = getattr(entry, "origin", "built") == "imported"
        out.append(Known(
            name=str(entry.name),
            origin="brought in" if imported else "made here",
            directory=str(getattr(entry, "directory", "") or ""),
            envelope_mm=tuple(round(float(v), 2) for v in envelope),
            volume_cm3=(round(float(entry.volume_cm3), 2)
                        if getattr(entry, "volume_cm3", None) else None),
            bodies=getattr(entry, "body_count", None),
            source_name=str(getattr(entry, "source_name", "") or ""),
            words=entry.haystack(),
        ))
    return out


#: A measured public corpus, if one has been ingested. One JSON object a line.
#:
#: SEPARATE FROM THE LIBRARY ON PURPOSE. Ten thousand models in parts/ would
#: bury the handful somebody actually made under a corpus they did not ask to
#: see. This is reference material: the knowledge base reads it and the
#: gallery never does.
CORPUS = Path("corpus") / "thingi10k.jsonl"


#: The corpus, read once. It is a file that does not change while the program
#: runs, and re-reading ten thousand lines on every request - which is every
#: keystroke of a search and every generate - was two seconds each time.
_CORPUS_CACHE: dict[str, list["Known"]] = {}


def forget_corpus() -> None:
    """Drop what is held, for a caller that has just written a new corpus."""
    _CORPUS_CACHE.clear()


def corpus(path: str | Path | None = None) -> list[Known]:
    """
    The public corpus, measured, as more evidence - or nothing.

    ABSENT IS THE NORMAL STATE. A fresh install has no corpus and works
    exactly as before: the priors come from whatever the person has made or
    brought in. This only ever adds.

    THE LICENCE AND AUTHOR TRAVEL WITH EACH ENTRY, because this is somebody
    else's work being cited as evidence about how big things are. They are
    carried on the record; `line()` does not print them, because the model is
    being told a size rather than being asked to redistribute a model.
    """
    source = Path(path or CORPUS)
    if not source.is_file():
        return []

    key = str(source.resolve())
    held = _CORPUS_CACHE.get(key)
    if held is not None:
        return held

    out: list[Known] = []
    # ONE ENTRY PER THING, NOT PER FILE. A Thingiverse "thing" is often
    # several files - a body, a lid, three variants - all carrying the same
    # name, and handed over as evidence they read as several independent
    # observations. "Universal stand-alone filament spool holder" filled
    # every slot of a four-slot answer on its own.
    seen: set[str] = set()
    with source.open() as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            envelope = row.get("envelope_mm")
            if not envelope or len(envelope) != 3 or not all(
                    float(v) > 0 for v in envelope):
                continue
            # NAMES OFF A WEBSITE ARRIVE HTML-ESCAPED. The corpus holds
            # "Sold&atilde;&euro;&euro;Holder", which is a real entry whose
            # name is unreadable and whose words match nothing. Unescaped
            # once here rather than by everything downstream.
            name = html.unescape(str(row.get("name") or "")).strip()
            key = name.lower() or str(row.get("file_id"))
            if key in seen:
                continue
            seen.add(key)
            words = " ".join([
                name,
                " ".join(str(t) for t in (row.get("tags") or [])),
                str(row.get("category") or ""),
                str(row.get("subcategory") or ""),
            ]).lower()
            out.append(Known(
                name=name or ("thingi10k %s" % row.get("file_id")),
                origin="printed by somebody else",
                directory="thingi10k:%s" % row.get("file_id"),
                envelope_mm=tuple(round(float(v), 2) for v in envelope),
                # A NEGATIVE VOLUME IS AN INVERTED MESH, NOT A MEASUREMENT.
                # "Gunny Sacks 103 x 94 x 125 mm  -486.2 cm3" - the faces
                # point inward, so the integral comes out signed the wrong
                # way. These are real uploads off a real site and a fifth of
                # them are non-manifold; nothing that reads this should have
                # to know that.
                volume_cm3=(round(float(row["volume_cm3"]), 2)
                            if float(row.get("volume_cm3") or 0) > 0 else None),
                bodies=row.get("bodies"),
                words=words,
            ))
    _CORPUS_CACHE[key] = out
    return out


def everything(roots: Iterable[str | Path] | None = None) -> list[Known]:
    """
    The library and the corpus together, which is what a request is matched
    against.

    THE LIBRARY COMES FIRST and that is not arbitrary: a thing somebody on
    this machine made or chose to download is better evidence about what they
    mean than a model somebody else uploaded in 2013. Ties in scoring are
    broken by order, so the local one wins.
    """
    return index(roots) + corpus()


def closest(request: str, known: list[Known] | None = None,
            limit: int = DEFAULT_LIMIT) -> list[Known]:
    """
    The measured things this request is most likely about.

    SCORED, NOT FILTERED. The gallery's search requires every word to match,
    which is right for "find the one I mean" and wrong here: "a stand for my
    phone on the desk" should still reach a phone stand. So each request word
    that appears anywhere in an entry's haystack scores, and a word in the
    entry's own NAME scores double - being called "phone_stand" is stronger
    evidence than containing the word somewhere in a prompt.

    NOTHING MATCHED IS AN EMPTY LIST, and that is a real answer. A request
    for something unlike anything here gets no priors, which is correct: the
    alternative is handing the model the dimensions of an unrelated object
    and calling it evidence.
    """
    pool = everything() if known is None else known
    asked = words_of(request)
    if not asked or not pool:
        return []

    scored: list[Known] = []
    for item in pool:
        hits = [w for w in asked if w in item.words]
        if not hits:
            continue
        name_words = set(re.findall(r"[a-z0-9]+", item.name.lower()))
        score = float(len(hits)) + sum(1.0 for w in hits if w in name_words)
        # A LONG HAYSTACK MATCHES MORE OF EVERYTHING. A template's list of
        # what it makes runs to thirty words, so an enclosure answers to
        # half the language; dividing by the log of the length keeps a part
        # that IS a phone stand above one that merely lists the words.
        import math

        score /= 1.0 + math.log1p(len(item.words) / 200.0)

        # WHAT IS ON THIS MACHINE WINS A CLOSE CALL.
        #
        # Asked for "a phone stand", a public corpus offered "Universal
        # stand-alone filament spool holder" above this machine's own
        # iphone_holder - it matched "stand" inside "stand-alone" and its
        # name is long enough to score well. A thing somebody here made, or
        # chose to download and keep, is better evidence of what they mean
        # than a model somebody else uploaded in 2013. A quarter, so it
        # settles near-ties and never beats a plainly better match.
        if item.origin != "printed by somebody else":
            score *= 1.25

        item.score = round(score, 3)
        item.matched = hits
        scored.append(item)

    # HOW MUCH OF THE REQUEST IS ACCOUNTED FOR, FIRST.
    #
    # Score alone put this machine's `iphone_holder` above an actual
    # "Universal stand-alone filament spool holder" for the request "a spool
    # holder": one matched "holder" and got the name-match bonus, the other
    # matched both words. Covering more of what was asked is the stronger
    # claim, and the score - which is about how specific the match is -
    # settles it only among equals. Otherwise the local preference, which
    # exists to break near-ties, starts beating plainly better matches.
    scored.sort(key=lambda k: (-len(k.matched), -k.score, k.name))
    return scored[:limit]


def facts_for(request: str, known: list[Known] | None = None,
              limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """
    What the model should be told about things like this, or nothing at all.

    THE SHAPE IS THE `facts=` CHANNEL, which already exists for what a
    reference photo measured: context the model reads, never values applied
    to parameters behind its back. That distinction is the whole reason this
    is safe - see api.reference_facts, which draws the same line for the same
    reason.

    THE CAVEAT TRAVELS WITH THE NUMBERS, not beside them. A model handed
    "phone_stand 78 x 62 x 95 mm" with no framing will copy it, and the
    request was for a DIFFERENT phone stand. The line says what these are:
    other objects of roughly this kind, measured, as a guide to scale.
    """
    neighbours = closest(request, known, limit)
    if not neighbours:
        return {}

    return {
        "similar_things_already_measured": [n.line() for n in neighbours],
        "how_to_use_them": (
            "These are OTHER objects of roughly this kind that have been "
            "measured on this machine - not the part being asked for. Use "
            "them for SCALE: a part of this kind is about this big. Do not "
            "copy their dimensions as if they were given in the request."
        ),
    }
