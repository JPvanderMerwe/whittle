"""
Measure a public corpus of printed models, so vague requests have priors.

WHAT THIS IS FOR
----------------
Somebody types "a phone stand" and every number in the answer is chosen
rather than given. The knowledge base answers that from things this machine
has measured - which, on a new install, is nothing. This fills it: Thingi10K
is 10,000 models people actually printed, published as a research dataset,
each with its author, its licence, a name and usually tags.

WHY NOT SCRAPE PRINTABLES OR THINGIVERSE DIRECTLY. Because it is other
people's work and their terms say not to. Thingi10K exists precisely so
this kind of study does not need scraping: it is a curated snapshot with
per-model licence metadata, and every entry here keeps the licence and the
author it came with.

WHAT IT WRITES, AND WHERE IT DOES NOT WRITE IT
----------------------------------------------
NOT into the library. Ten thousand entries in parts/ or library/ would bury
the handful of things somebody actually made under a corpus they did not ask
to see, and the gallery is theirs. This writes ONE file - corpus/thingi10k
.jsonl - holding a measured line per model, which the knowledge base reads
as evidence and nothing else reads at all.

MEASURED, ONE MESH AT A TIME, AND RESUMABLE. Loading ten thousand meshes is
tens of minutes of CPU; the file is appended as it goes and a re-run skips
what is already in it, so this can be stopped and started. Half a corpus is
useful - the priors are better with five hundred than with none.

WHAT IS DELIBERATELY DROPPED. Half the dataset is non-solid and a fifth is
non-manifold - these are real files off a real site, not clean CAD. A mesh
whose volume cannot be trusted keeps its envelope and loses its volume, the
same rule the importer follows, because a volume off an open mesh is a
number that means nothing.

    python tools/ingest_thingi10k.py --limit 500
    python tools/ingest_thingi10k.py --category household --limit 2000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

#: Where the measured corpus lands. One file, read by whittle.knowledge.
CORPUS = Path("corpus") / "thingi10k.jsonl"

#: Meshes bigger than this are skipped rather than measured.
#:
#: The dataset holds some enormous scans - hundreds of thousands of facets -
#: and loading one costs seconds for a bounding box that a simpler model
#: gives just as well. The corpus is for scale priors, not for fidelity.
MAX_FACETS = 200_000


def already_done(path: Path) -> set[int]:
    """Which file_ids the corpus already holds, so a re-run resumes."""
    done: set[int] = set()
    if not path.is_file():
        return done
    with path.open() as handle:
        for line in handle:
            try:
                done.add(int(json.loads(line)["file_id"]))
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
    return done


def measure(mesh) -> dict:
    """
    The envelope, and a volume only when the mesh is closed.

    THE SAME RULE THE IMPORTER FOLLOWS. On an open mesh trimesh still returns
    a number and that number means nothing - half of this dataset is
    non-solid, so this is the common case rather than the edge one.
    """
    box = [round(float(v), 2) for v in mesh.extents]
    out: dict = {"envelope_mm": box}
    if bool(mesh.is_watertight):
        out["volume_cm3"] = round(float(mesh.volume) / 1000.0, 3)
    out["bodies"] = int(mesh.body_count) if hasattr(mesh, "body_count") else None
    return out


def run(limit: int, category: str | None, out: Path) -> int:
    import numpy as np
    import thingi10k
    import trimesh

    thingi10k.init()
    rows = thingi10k.dataset(category=category) if category else thingi10k.dataset()

    done = already_done(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = skipped = failed = 0
    started = time.time()

    with out.open("a") as handle:
        for row in rows:
            if written >= limit:
                break
            file_id = int(row["file_id"])
            if file_id in done:
                continue
            if (row.get("num_facets") or 0) > MAX_FACETS:
                skipped += 1
                continue

            try:
                vertices, facets = thingi10k.load_file(row["file_path"])
                mesh = trimesh.Trimesh(
                    vertices=np.asarray(vertices), faces=np.asarray(facets),
                    process=False)
                measured = measure(mesh)
            except Exception:
                # A FILE THAT WILL NOT LOAD IS SKIPPED, NOT RECORDED. This is
                # a corpus of real uploads and some of them are broken; one
                # that cannot be measured has nothing to contribute and an
                # entry with no dimensions would be a row that never matches.
                failed += 1
                continue

            if not measured["envelope_mm"] or not all(
                    v > 0 for v in measured["envelope_mm"]):
                failed += 1
                continue

            handle.write(json.dumps({
                "file_id": file_id,
                "name": (row.get("name") or "").strip(),
                "tags": [str(t).replace("_", " ").lower()
                         for t in (row.get("tags") or [])],
                "category": row.get("category") or "",
                "subcategory": row.get("subcategory") or "",
                # THE LICENCE AND THE AUTHOR TRAVEL WITH IT. This is somebody
                # else's work being used as evidence about scale, and the
                # attribution is part of the record rather than something to
                # look up later.
                "license": row.get("license") or "",
                "author": row.get("author") or "",
                "closed": bool(row.get("closed")),
                **measured,
            }) + "\n")
            handle.flush()
            written += 1
            if written % 50 == 0:
                print("  %d measured, %.0fs" % (written, time.time() - started),
                      flush=True)

    print("%d measured, %d too big, %d unreadable -> %s"
          % (written, skipped, failed, out))
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--limit", type=int, default=500,
                        help="how many to measure this run (default 500)")
    parser.add_argument("--category", default=None,
                        help="only this Thingiverse category")
    parser.add_argument("--out", type=Path, default=CORPUS)
    args = parser.parse_args(argv)

    try:
        run(args.limit, args.category, args.out)
    except ImportError as exc:
        print("this needs the dataset package: pip install thingi10k\n  (%s)" % exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
