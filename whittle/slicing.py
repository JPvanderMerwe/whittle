"""
How long it will take and how much filament it will use - from a slicer,
because nowhere else can honestly say.

WHY THIS SHELLS OUT INSTEAD OF WORKING IT OUT
---------------------------------------------
A print's time and its filament are decided by walls, infill, speeds,
accelerations, retractions and the machine's own limits. None of that is a
property of the mesh: the same object at 15% infill and at 60% is two
different prints, and a figure derived from solid volume is not an estimate
of either - it is a different quantity wearing the same units.

So whittle does not estimate them. It asks a slicer, and reports what the
slicer said, naming the slicer. That is the same rule the rest of this
program follows for a dimension: measure it, or say you do not know.

WHAT COUNTS AS AN ANSWER HERE
-----------------------------
PrusaSlicer and Slic3r write their own estimates into the G-code as
comments, which is where these figures come from - they are the slicer's
arithmetic over the toolpaths it actually generated, not a second guess made
here. If the G-code carries no such comments this returns nothing rather
than a number: a wrong weight is worse than an absent one, and somebody
loading a spool is acting on it.

OPTIONAL, AND ABSENT IS A NORMAL STATE. No slicer is installed on the
machine this was written on. Rule 11 says the system stays fully usable with
nothing else working: with no slicer, everything else about a print - does
it fit, how many layers, does it need support - is still measured and still
shown, and this part says plainly that it needs a slicer and which one.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

#: Slicers this knows how to drive, in the order they are looked for.
#:
#: Both are the same lineage - Slic3r is PrusaSlicer's ancestor - and both
#: take `--export-gcode` and write their estimates into the file as comments.
#: Cura's engine is deliberately not here: CuraEngine takes a definition tree
#: rather than a printer name, and wiring it blind would be guessing at an
#: interface (rule 9). It is worth adding against a real installation.
KNOWN_SLICERS = ("prusa-slicer", "prusaslicer", "slic3r")

#: How long a slice may run before it is abandoned.
#:
#: A slice of an ordinary part is seconds. A minute means something is very
#: wrong - a mesh with a million faces, or a slicer waiting on a prompt that
#: will never be answered - and a web request hanging on it is worse than no
#: figures.
TIMEOUT_S = 120


@dataclass
class Sliced:
    """What a slicer said about one part, and which slicer said it."""

    ok: bool = False
    #: The slicer's own name and version, so the figures can be attributed.
    slicer: str = ""
    #: Seconds, as the slicer reported them. None when it did not say.
    seconds: float | None = None
    #: Grams of filament, as the slicer reported them.
    grams: float | None = None
    #: Millimetres of filament off the spool.
    filament_mm: float | None = None
    #: Cubic centimetres of filament off the spool.
    #:
    #: REPORTED BECAUSE GRAMS OFTEN CANNOT BE. A slicer only knows a weight
    #: if its filament profile carries a density, and the stock profile ships
    #: with `filament_density = 0` - so a real slice of a real part came back
    #: "total filament used [g] = 0.00". Volume it always knows, because it
    #: is the length it just extruded times the area of the nozzle.
    filament_cm3: float | None = None
    layers: int | None = None
    #: Why there are no figures, in words, when there are none.
    why: str = ""
    #: Every comment line the estimates were read out of, for checking.
    evidence: list[str] = field(default_factory=list)


def which_slicer() -> str | None:
    """The slicer on this machine, or None. Looked up fresh every time."""
    for name in KNOWN_SLICERS:
        found = shutil.which(name)
        if found:
            return found
    return None


def how_to_install() -> str:
    """
    The one command that makes this work, for the answer that says it cannot.

    A feature that is missing and says only "not available" is a dead end.
    Naming the package turns it into a decision somebody can make.
    """
    return ("No slicer is installed, so time and filament cannot be known. "
            "Install one with `sudo apt install prusa-slicer` and this will "
            "use it.")


#: What the estimates look like in a PrusaSlicer or Slic3r G-code file.
#:
#: WRITTEN AGAINST THE DOCUMENTED COMMENT FORMAT and deliberately forgiving
#: of the parts that vary: the bracketed unit, the "(normal mode)" a
#: PrusaSlicer build adds to its time line, and the spacing around the
#: equals. What it is NOT forgiving of is a missing key - see `read_estimates`
#: for why a silent zero is not an option.
_TIME = re.compile(
    r";\s*estimated printing time[^=]*=\s*(.+)", re.I)
_GRAMS = re.compile(
    r";\s*(?:total\s+)?filament used\s*\[g\]\s*=\s*([0-9.]+)", re.I)
_MM = re.compile(
    r";\s*(?:total\s+)?filament used\s*\[mm\]\s*=\s*([0-9.]+)", re.I)
_CM3 = re.compile(
    r";\s*(?:total\s+)?filament used\s*\[cm3\]\s*=\s*([0-9.]+)", re.I)
_LAYERS = re.compile(r";\s*(?:total layer(?: count|s)|layer count)\s*=\s*(\d+)", re.I)

#: "1h 23m 45s", "23m 45s", "45s" - the shape PrusaSlicer writes.
_DURATION = re.compile(r"(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?", re.I)


def as_seconds(text: str) -> float | None:
    """
    "1h 23m 45s" as seconds, or None if it is not a duration at all.

    NONE RATHER THAN ZERO on something unrecognised. A print reported as
    taking no time is a figure somebody might believe; an absent one is a
    question they will ask.
    """
    match = _DURATION.fullmatch(text.strip())
    if not match or not any(match.groups()):
        return None
    days, hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    total = days * 86400 + hours * 3600 + minutes * 60 + seconds
    return float(total) if total else None


def read_estimates(gcode: str) -> Sliced:
    """
    The slicer's own figures, out of the G-code it wrote.

    NOTHING IS DERIVED HERE. Grams are not computed from millimetres and a
    density, and time is not computed from length and a speed - both would
    be this program inventing a number and attributing it to the slicer.
    Every field is either something the file states or absent.
    """
    out = Sliced()
    evidence: list[str] = []

    for line in gcode.splitlines():
        if not line.lstrip().startswith(";"):
            continue

        found = _TIME.match(line.strip())
        if found and out.seconds is None:
            seconds = as_seconds(found.group(1))
            if seconds is not None:
                out.seconds = seconds
                evidence.append(line.strip())

        for pattern, attr in ((_GRAMS, "grams"), (_MM, "filament_mm"),
                              (_CM3, "filament_cm3")):
            found = pattern.match(line.strip())
            if found and getattr(out, attr) is None:
                value = float(found.group(1))
                # ZERO IS NOT A MEASUREMENT, IT IS A MISSING PROFILE.
                #
                # A real slice of a real hinge reported "total filament used
                # [g] = 0.00", because PrusaSlicer's stock filament profile
                # carries `filament_density = 0` and it will not divide by
                # nothing. Accepting that put "0 g" on a screen as the weight
                # of a part that plainly weighs something - a figure somebody
                # would load a spool against. No print uses no filament and
                # no print takes no time, so a zero here means "not known".
                if value <= 0:
                    continue
                setattr(out, attr, value)
                evidence.append(line.strip())

        found = _LAYERS.match(line.strip())
        if found and out.layers is None:
            out.layers = int(found.group(1))
            evidence.append(line.strip())

    out.evidence = evidence
    # VOLUME COUNTS AS AN ANSWER. Grams need a density the profile may not
    # carry; cm3 the slicer always knows. An answer with a time and a volume
    # and no weight is still worth having, and it is honest about which.
    out.ok = any(v is not None for v in
                 (out.seconds, out.grams, out.filament_cm3))
    if not out.ok:
        out.why = ("the slicer produced G-code with no estimates in it - this "
                   "reads the comment lines PrusaSlicer and Slic3r write, and "
                   "found none")
    return out


def slice_part(stl: str | Path, *, layer_mm: float | None = None,
               nozzle_mm: float | None = None,
               density_g_cm3: float | None = None,
               extra: list[str] | None = None) -> Sliced:
    """
    Run the slicer over one STL and read back what it said.

    INTO A TEMPORARY DIRECTORY. The G-code is wanted for the two numbers in
    its header; keeping it beside the part would put a file in the library
    that nothing reads and that goes stale the moment a setting changes.

    THE SLICER'S OWN DEFAULTS, plus the layer height and nozzle this part was
    built for. Anything else - infill, walls, speeds - is left to the slicer's
    configuration, because those are the person's printing preferences and
    whittle has no business having an opinion about them. The figures that
    come back are therefore the figures they would get by slicing it
    themselves, which is the only thing worth reporting.
    """
    binary = which_slicer()
    if binary is None:
        return Sliced(why=how_to_install())

    source = Path(stl)
    if not source.is_file():
        return Sliced(why="%s is not a file this can slice" % source.name)

    with tempfile.TemporaryDirectory(prefix="whittle-slice-") as scratch:
        target = Path(scratch) / (source.stem + ".gcode")
        command = [binary, "--export-gcode", "--output", str(target)]
        if layer_mm:
            command += ["--layer-height", "%g" % layer_mm]
        if nozzle_mm:
            command += ["--nozzle-diameter", "%g" % nozzle_mm]
        # THE DENSITY, OR NO WEIGHT AT ALL.
        #
        # The stock profile's is 0, so without this the slicer reports a
        # weight of zero for everything. Passed in by the caller from the
        # material config rather than chosen here, because it is a property
        # of a spool somebody bought and the config records where each figure
        # came from.
        if density_g_cm3:
            command += ["--filament-density", "%g" % density_g_cm3]
        command += list(extra or [])
        command.append(str(source))

        try:
            done = subprocess.run(command, capture_output=True, text=True,
                                  timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return Sliced(why="the slicer did not finish within %ds" % TIMEOUT_S)
        except OSError as exc:
            return Sliced(why="could not run %s: %s" % (binary, exc))

        if done.returncode != 0 or not target.is_file():
            # THE SLICER'S OWN COMPLAINT, not a summary of it. "Object too
            # large for the bed" is the answer, and rewording it here would
            # lose the one sentence worth reading.
            said = (done.stderr or done.stdout or "").strip().splitlines()
            return Sliced(why=(said[-1][:300] if said
                               else "the slicer produced no G-code and said nothing"))

        result = read_estimates(target.read_text(errors="replace"))

    result.slicer = _version_of(binary)
    return result


def _version_of(binary: str) -> str:
    """
    The slicer's name and version, so a figure can be attributed to it.

    Attribution matters here in the same way a measurement's source does: a
    time in an app with no name against it is a claim the app is making, and
    this program does not make that claim - the slicer does.
    """
    try:
        done = subprocess.run([binary, "--version"], capture_output=True,
                              text=True, timeout=15)
        line = (done.stdout or done.stderr or "").strip().splitlines()
        if line:
            return line[0][:80]
    except (OSError, subprocess.SubprocessError):
        pass
    return Path(binary).name
