#!/usr/bin/env python3
"""
Cut the app's two type families out of the ones this repo already ships.

    python3 tools/app_fonts.py

WHY THE NATIVE CLIENT NEEDS ITS OWN COPIES
------------------------------------------
Product brief 11.3: "Archivo or Space Grotesk for UI, JetBrains Mono for
dimensions. Bundle both as local font files in all three builds. No CDN font
loads; the apps must render offline."

The web client does that. The phone did not, and the token export made it look
as though it had: `type.mono` and `type.prose` named 'IBM Plex Mono' and
'Inter', neither of which is on an Android device, so React Native silently
drew BOTH in the system face. Two families that the design says must be clearly
distinct, rendering identically, on every screen. Naming the system faces
instead - `monospace` and `sans-serif` - fixed the "identically" half and left
the app set in whatever the phone happened to ship.

So the same files the browser gets are cut into static TTFs here and embedded
by the expo-font config plugin at build time. No runtime loading, no async font
state, no splash held open waiting for a download that cannot happen anyway.

ONE SOURCE, STILL. These are derived from whittle/web/static/fonts/*.woff2 -
the same bytes the web client serves - so the phone and the browser cannot come
to be set in different cuts of the same name.

WEIGHTS: the three the token source declares, and no others. `design/tokens.json`
has regular 400, medium 500, bold 600; a family shipping weights nothing asks
for is bytes inside an APK for nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SRC = ROOT / "whittle" / "web" / "static" / "fonts"
OUT = ROOT / "app" / "assets" / "fonts"

#: (source woff2, the family name the app asks for, weights)
#:
#: The family name is what `fontFamily` resolves to on the device, and it is
#: declared in app.json beside the files. It is NOT read out of the font: the
#: variable Space Grotesk names itself "Space Grotesk Light" after its default
#: instance, which is the sort of thing that silently picks the wrong cut.
FAMILIES = [
    ("spacegrotesk-latin.woff2", "Space Grotesk", (400, 500, 600)),
    ("jetbrainsmono-latin.woff2", "JetBrains Mono", (400, 500, 600)),
]


def main() -> int:
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    OUT.mkdir(parents=True, exist_ok=True)
    written = []

    for filename, family, weights in FAMILIES:
        source = SRC / filename
        if not source.is_file():
            print("missing %s" % source.relative_to(ROOT))
            return 1

        for weight in weights:
            font = TTFont(source)
            axis = next((a for a in font["fvar"].axes if a.axisTag == "wght"), None)
            if axis is None:
                print("%s has no weight axis" % filename)
                return 1
            # CLAMPED TO WHAT THE AXIS HAS. JetBrains Mono starts at 400, so a
            # 300 would be silently snapped by the instancer; asking for a
            # weight a family does not have is a decision, not a rounding.
            wanted = min(max(weight, axis.minValue), axis.maxValue)
            if wanted != weight:
                print("  %s has no %d - using %d" % (family, weight, wanted))

            cut = instancer.instantiateVariableFont(
                font, {"wght": wanted}, inplace=False
            )
            # The flavour is inherited from the woff2 source; an Android
            # resource has to be a plain TTF or it is not registered at all.
            cut.flavor = None
            target = OUT / ("%s-%d.ttf" % (family.replace(" ", ""), weight))
            cut.save(target)
            written.append(target)

    for path in written:
        print("wrote %-44s %6.1f KB"
              % (path.relative_to(ROOT), path.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
