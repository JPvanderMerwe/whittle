"""
The local library: everything you have made, findable.

WHY SPECS AND NOT MESHES
------------------------
A downloaded STL is a frozen mesh. You cannot make it 20 mm wider, cannot
change it for a different printer, cannot ask it anything. Every part here is a
SPEC - twenty lines of readable text carrying the template, the numbers, the
assumptions and the deliberate departures from scale - so it rebuilds exactly,
at whatever size you need, in your material, for your nozzle.

That makes a library of specs a better thing to keep and a better thing to
share than a library of meshes, and it is why this indexes spec.yaml rather
than *.stl.

FULLY OFFLINE. It reads directories you name. Nothing here opens a socket.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

# Where things live, and there are TWO PLACES.
#
# THIS WAS ONE, AND IT IS WHY AN IMPORTED STL DISAPPEARED. Everything the
# engine builds lands in parts/; everything a person brings in lands in
# library/ - whittle.imports.IMPORT_ROOT - with its measurements in
# import.json. Only parts/ was ever scanned, so a mesh you imported was
# editable for exactly as long as that session stayed open and then was gone
# from every list in the product. You could not find it, search it, open it
# again or see it had ever existed.
#
# They are one library with two origins. The distinction is real and worth
# keeping - a part has a spec behind it and can be changed by describing the
# change, an import is somebody else's triangles and can only be worked on as
# a mesh - but that is a fact ABOUT an entry, not a reason to hide half of
# them.
DEFAULT_ROOTS = ("parts", "library")

# Files that make a directory a part rather than a folder that happens to
# contain YAML.
SPEC_NAMES = ("spec.yaml", "spec.yml")
DRAFT_NAMES = ("spec.draft.yaml", "spec.draft.yml")

#: What an imported mesh leaves behind instead of a spec.
IMPORT_NAME = "import.json"


@dataclass
class LibraryEntry:
    """One part in the library, and everything known about it without building."""

    name: str
    directory: Path
    spec_path: Path | None = None
    draft_path: Path | None = None
    template: str | None = None
    level: int = 1
    material: str = ""
    makes: list[str] = field(default_factory=list)
    prompt: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    stl: Path | None = None
    images: dict[str, Path] = field(default_factory=dict)
    volume_cm3: float = 0.0
    envelope_mm: tuple[float, float, float] | None = None

    # HOW MANY SEPARATE SOLIDS, from the stored regression.
    #
    # For anything with a moving part this is the fact that decides whether it
    # works: two bodies turn, one is fused solid. It was already being read out
    # of regression.json two lines below the envelope and thrown away, so the
    # library could not tell a working hinge from a hinge-shaped brick - and
    # neither could the phone's `Moving` filter or its `moves` badge.
    #
    # None means "not recorded", which is different from 1. A part built
    # before the regression baseline carried a body count has no answer, and
    # saying "1 piece" for it would be a guess.
    body_count: int | None = None
    versions: int = 0
    modified: float = 0.0

    #: Where this came from: "built" here from a spec, or "imported" as a mesh.
    #:
    #: NOT COSMETIC. An imported mesh has no spec, so it cannot be changed by
    #: describing the change - "make it taller" needs a parametric model to
    #: change. It can be hollowed, cut and scaled as a mesh, which is a
    #: different set of things. A screen that does not know which it is holding
    #: will offer one of them the wrong tools.
    origin: str = "built"

    #: For an import: what the file was called when it arrived.
    #:
    #: Kept because it is how a person recognises it. "LCD-knob.stl" is what
    #: they downloaded; `lcd-knob` is what this program called the directory.
    source_name: str = ""

    #: Free-text the importer recorded - which printer it came off, say.
    note: str = ""

    #: Words a person attached to it. Searchable like everything else.
    tags: list[str] = field(default_factory=list)

    @property
    def is_import(self) -> bool:
        return self.origin == "imported"

    @property
    def is_draft(self) -> bool:
        return self.spec_path is None and self.draft_path is not None

    @property
    def built(self) -> bool:
        return self.stl is not None and self.stl.is_file()

    @property
    def thumbnail(self) -> Path | None:
        for key in ("thumb", "3q", "preview", "front", "above"):
            if key in self.images:
                return self.images[key]
        return next(iter(self.images.values()), None)

    @property
    def when(self) -> str:
        if not self.modified:
            return ""
        return datetime.fromtimestamp(self.modified, timezone.utc).strftime("%Y-%m-%d")

    def haystack(self) -> str:
        """
        Everything worth matching a search against, lowercased.

        The `makes` words are in here, so typing "container" finds a part built
        from the enclosure template even though the word appears nowhere in its
        own spec.

        And for an import: the name the FILE had, plus whatever note and tags
        came with it. Somebody looking for a knob they downloaded types
        "LCD-knob", which is not what the directory ended up being called.
        """
        bits = [self.name, self.template or "", self.material, self.prompt]
        bits += self.makes
        bits += [str(k) for k in self.params]
        bits += [self.source_name, self.note, self.origin]
        bits += self.tags
        return " ".join(bits).lower()

    def summary(self) -> str:
        if self.is_draft:
            return "needs editing"
        if not self.built:
            return "spec only"
        if self.envelope_mm:
            return "%.0f x %.0f x %.0f mm, %.0f cm3" % (
                *self.envelope_mm, self.volume_cm3
            )
        return "built"


def _read_import(directory: Path, record: Path) -> LibraryEntry | None:
    """
    One imported mesh, as a library entry.

    EVERYTHING HERE IS MEASURED AND ALREADY ON DISK. import.json is written at
    ingest with the envelope, the volume, the triangle and body counts and
    whether it came out watertight - the same figures a built part carries in
    its regression, from the same measurement code. None of it is re-derived
    and none of it is guessed: an import with no recorded envelope shows none,
    exactly as a part built before regressions did.
    """
    try:
        data = json.loads(record.read_text())
    except (json.JSONDecodeError, OSError):
        # A record that will not parse is not a reason to lose the mesh beside
        # it. The directory still holds an STL somebody imported, so it is
        # listed with the little that can be read off the filesystem.
        data = {}

    out = directory / "out"
    stls = sorted(out.glob("*.stl")) if out.is_dir() else []

    envelope = data.get("envelope_mm")
    if isinstance(envelope, (list, tuple)) and len(envelope) == 3:
        envelope = tuple(float(v) for v in envelope)
    else:
        envelope = None

    entry = LibraryEntry(
        name=str(data.get("name") or directory.name),
        directory=directory,
        stl=stls[0] if stls else None,
        images=_images(out),
        origin="imported",
        source_name=str(data.get("source_name") or ""),
        note=str(data.get("note") or ""),
        tags=[str(t) for t in (data.get("tags") or [])],
        envelope_mm=envelope,
        volume_cm3=float(data.get("volume_cm3") or 0.0),
        body_count=int(data["bodies"]) if data.get("bodies") is not None else None,
    )
    entry.modified = float(data.get("imported_at") or record.stat().st_mtime)
    return entry


def _read_spec(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _template_words(template: str | None) -> list[str]:
    if not template:
        return []
    from whittle.spec import registry

    try:
        return list(registry.get(template).makes)
    except Exception:
        return []


def _images(out_dir: Path) -> dict[str, Path]:
    if not out_dir.is_dir():
        return {}
    found: dict[str, Path] = {}
    for png in sorted(out_dir.glob("*.png")):
        key = png.stem.split("_")[-1] if "_" in png.stem else png.stem
        found[key] = png
    return found


def read_entry(directory: Path) -> LibraryEntry | None:
    """
    Read one directory. Returns None if it holds neither a part nor an import.

    THREE THINGS MAKE A DIRECTORY SOMETHING: a spec, a draft spec, or an
    import record. It used to be the first two, so every mesh a person brought
    in was skipped here even when its root was scanned - the second half of the
    reason imports vanished from the product.
    """
    spec_path = next((directory / n for n in SPEC_NAMES if (directory / n).is_file()), None)
    draft_path = next((directory / n for n in DRAFT_NAMES if (directory / n).is_file()), None)
    if spec_path is None and draft_path is None:
        imported = directory / IMPORT_NAME
        if imported.is_file():
            return _read_import(directory, imported)
        return None

    data = _read_spec(spec_path or draft_path)
    out = directory / "out"
    stls = sorted(out.glob("*.stl")) if out.is_dir() else []

    entry = LibraryEntry(
        name=str(data.get("name") or directory.name),
        directory=directory,
        spec_path=spec_path,
        draft_path=draft_path,
        template=data.get("template"),
        level=int(data.get("level") or 1),
        material=str(data.get("material") or ""),
        params=dict(data.get("params") or {}),
        stl=stls[0] if stls else None,
        images=_images(out),
    )
    entry.makes = _template_words(entry.template)

    session = directory / "session.json"
    if session.is_file():
        try:
            s = json.loads(session.read_text())
            entry.prompt = str(s.get("prompt") or "")
            entry.versions = len(s.get("versions") or [])
        except Exception:
            pass

    run = directory / "run.json"
    if not entry.prompt and run.is_file():
        try:
            entry.prompt = str(json.loads(run.read_text()).get("request") or "")
        except Exception:
            pass

    # Envelope and volume come from regression.json when it exists, so a search
    # does not have to load and measure every mesh on disk.
    regression = directory / "regression.json"
    if regression.is_file():
        try:
            r = json.loads(regression.read_text())
            entry.volume_cm3 = float(r.get("volume_cm3") or 0.0)
            box = r.get("bbox_mm")
            if box and len(box) == 3:
                entry.envelope_mm = tuple(float(v) for v in box)
            if r.get("body_count") is not None:
                entry.body_count = int(r["body_count"])
        except Exception:
            pass

    try:
        entry.modified = (spec_path or draft_path).stat().st_mtime
    except OSError:
        pass
    return entry


#: Everything `read_entry` opens, which is what a cached entry can go stale on.
#:
#: Listed here rather than inferred, because the cache is only safe if this is
#: exactly right: a file read there and missing here would be a change the
#: library never notices. Adding a read to read_entry means adding it here.
WATCHED_FILES = SPEC_NAMES + DRAFT_NAMES + (
    IMPORT_NAME, "session.json", "run.json", "regression.json",
)

#: directory -> (stamp, entry). Process-local and never persisted.
_CACHE: dict[Path, tuple[tuple, "LibraryEntry | None"]] = {}


def _stamp(directory: Path) -> tuple:
    """
    A cheap fingerprint of everything a read of this directory depends on.

    STATS RATHER THAN READS. Re-reading three JSON files and a YAML per
    directory is what makes a scan cost a millisecond each, which is nothing
    at forty parts and most of a second at a thousand - and a gallery that
    searches as you type asks for a scan per keystroke.

    THE DIRECTORY'S OWN MTIME IS NOT ENOUGH, and getting that wrong would be
    worse than no cache at all. A directory's mtime moves when a file is
    created or removed inside it and NOT when an existing file's contents
    change, so a rebuild that rewrites spec.yaml in place would leave the
    library showing the old numbers with no way to notice. Every watched file
    is fingerprinted, plus the out/ listing, which is how a part gains its
    STL.

    ONE PASS, NOT EIGHT STATS. `scandir` yields the names with their metadata
    already attached, so the whole fingerprint costs one directory read - and
    at a thousand models eight separate stats was most of what the cache was
    saving.
    """
    import os

    watched = set(WATCHED_FILES)
    marks: list = [directory.name]
    try:
        with os.scandir(directory) as it:
            for item in it:
                if item.name in watched and item.is_file():
                    st = item.stat()
                    marks.append((item.name, st.st_mtime_ns, st.st_size))
    except OSError:
        return (directory.name,)
    marks.sort(key=lambda m: m if isinstance(m, tuple) else ("",))

    # THE EXPORTS TOO, because a part gains its STL and its renders without
    # anything it already holds changing.
    try:
        with os.scandir(directory / "out") as it:
            marks.append(tuple(sorted(item.name for item in it)))
    except OSError:
        marks.append(())
    return tuple(marks)


def forget(directory: str | Path | None = None) -> None:
    """
    Drop what is remembered about a directory, or all of it.

    For the callers that know they have changed something and would rather say
    so than wait to be noticed - and for tests, which build a library, read
    it, rewrite it and read it again inside one mtime tick.
    """
    if directory is None:
        _CACHE.clear()
        return
    _CACHE.pop(Path(directory).resolve(), None)


def scan(roots: Iterable[str | Path] | None = None,
         use_cache: bool = True) -> list[LibraryEntry]:
    """
    Every part under the given directories, newest first.

    Looks one level down and also at the roots themselves, so both
    `parts/vent/spec.yaml` and a directory handed in directly are found.

    CACHED ON WHAT EACH DIRECTORY CONTAINS - see _stamp. A directory whose
    files have not moved is not read again, which is what lets a search run on
    every keystroke against a library of a thousand models. `use_cache=False`
    reads everything, for a caller that wants to be certain.
    """
    entries: list[LibraryEntry] = []
    seen: set[Path] = set()

    for root in (roots or DEFAULT_ROOTS):
        base = Path(root)
        if not base.is_dir():
            continue
        candidates = [base] + sorted(p for p in base.iterdir() if p.is_dir())
        for directory in candidates:
            resolved = directory.resolve()
            if resolved in seen:
                continue

            entry: LibraryEntry | None
            if use_cache:
                stamp = _stamp(directory)
                remembered = _CACHE.get(resolved)
                if remembered is not None and remembered[0] == stamp:
                    entry = remembered[1]
                else:
                    entry = read_entry(directory)
                    _CACHE[resolved] = (stamp, entry)
            else:
                entry = read_entry(directory)
                _CACHE.pop(resolved, None)

            if entry is not None:
                seen.add(resolved)
                entries.append(entry)

    entries.sort(key=lambda e: e.modified, reverse=True)
    return entries


def search(query: str, entries: list[LibraryEntry] | None = None,
           roots: Iterable[str | Path] | None = None) -> list[LibraryEntry]:
    """
    Find parts by any word that describes them.

    Every word in the query has to match somewhere - the name, the template,
    the material, the prompt that made it, a parameter name, or one of the
    words the template says it makes. That last one is what lets "container"
    find a part built from the enclosure template.
    """
    pool = entries if entries is not None else scan(roots)
    words = [w for w in query.lower().split() if w]
    if not words:
        return pool
    return [e for e in pool if all(w in e.haystack() for w in words)]


# ---------------------------------------------------------------------------
# sharing
# ---------------------------------------------------------------------------


def export_spec(entry: LibraryEntry, target: str | Path) -> Path:
    """
    Write one part's spec to a file you can send someone.

    Just the spec, plus anything it needs to build - a traced logo, say. Not the
    mesh: the recipient rebuilds it at their own size, in their own material,
    for their own nozzle, which is the entire point of keeping specs rather
    than meshes.
    """
    import shutil

    if entry.spec_path is None:
        raise ValueError(
            "%s has no spec.yaml - it is a draft that still needs editing, and "
            "there is nothing to share until it does" % entry.name
        )

    out = Path(target)
    if out.is_dir() or not out.suffix:
        out = out / ("%s.spec.yaml" % entry.name)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(entry.spec_path, out)

    # Anything the spec points at by relative path has to travel with it.
    for value in entry.params.values():
        if not isinstance(value, str) or "/" in value or not value.endswith(".json"):
            continue
        asset = entry.directory / value
        if asset.is_file():
            shutil.copy2(asset, out.parent / asset.name)
    return out


def import_spec(path: str | Path, into: str | Path = "parts") -> LibraryEntry:
    """
    Take a spec someone sent you and put it in the library.

    It is validated on the way in, so a broken file is refused here rather than
    at build time with a confusing error.
    """
    import shutil

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError("no spec at %s" % source)

    data = _read_spec(source)
    if not data:
        raise ValueError("%s is not a spec file whittle can read" % source)

    from whittle.spec.schema import PartSpec, format_validation_error
    from pydantic import ValidationError

    try:
        spec = PartSpec.model_validate(data)
    except ValidationError as exc:
        raise ValueError(
            format_validation_error(exc, "%s is not a valid spec:" % source.name)
        ) from exc

    target = Path(into) / spec.name
    n = 2
    while target.exists():
        target = Path(into) / ("%s_%d" % (spec.name, n))
        n += 1
    target.mkdir(parents=True)
    shutil.copy2(source, target / "spec.yaml")

    for sibling in source.parent.glob("*.json"):
        shutil.copy2(sibling, target / sibling.name)

    entry = read_entry(target)
    if entry is None:
        raise ValueError("the spec was copied but could not be read back")
    return entry
