# wall_bracket

## Envelope and volume

| | |
|---|---|
| Envelope | 250.00 x 30.00 x 180.00 mm |
| Volume | 117.487 cm3 |
| Watertight | yes |
| Separate bodies | 1 |
| Triangles | 5122 |

## Filament estimate

Roughly **145.7 g** / **48.9 m** of 1.75 mm PLA at 100% infill.

An estimate from the solid volume. It does not model walls,
infill pattern, supports or purge, so treat it as an upper bound
below 100% infill.

## Print orientation

Build direction **Z**. Export is already in print orientation - do not rotate.

| | |
|---|---|
| Supports needed | YES |
| Worst overhang | 90.0 deg from vertical |
| Underside past 45 deg | 122.7 mm2 |
| ...bridged by the layer above | 68.4 mm2 |
| ...falling further | 54.2 mm2 |
| Bed contact | 7365.9 mm2 |

A long drop may still be a **bridge** anchored on both sides, which
prints fine. This check measures the fall, not the span - look at
the section render before adding supports.

## Feature sizes

Against a 0.40 mm nozzle, threshold 0.40 mm.

| Feature | Size (mm) | Status |
|---|---|---|
| gusset thickness | 4.000 | PASS |
| corner fillet | 5.000 | PASS |
| plate thickness | 6.000 | PASS |
| hole edge margin | 7.700 | PASS |

## Assumptions

These dimensions could **not** be measured. Each is a named
parameter standing in for something unknown.

- **edge_margin_mm** = 7.7 mm
  Not stated, so it is 1.4 x the hole diameter. Below that the material between the hole and the edge tears out under load.

## Departures from true scale

None - this part is at true scale throughout.

## Recommended slicer settings

- printer        Creality i7  (260 x 260 x 255 mm)
- layer height   0.20 mm
- nozzle         0.40 mm
- material       PLA
- orientation    as exported - do not rotate
- supports       required as oriented
- Orientation: standing on the back edge of the wall plate. DO NOT ROTATE - printed flat this is about a third as strong.
- No supports needed in that orientation.
- PETG or ABS. PLA creeps under a sustained load and the shelf droops.
- 4 walls and 40% infill. On a bracket the walls carry the load, so wall count matters far more than infill density.
- Layer 0.2 mm. Finer does not make it stronger.

## Provenance

Spec written by **qwen2.5-coder:7b** on machine **laptop**, 1 attempt(s), 4.3s.

The model filled in a validated specification. It did not write
CAD code - the geometry comes from a template in whittle, and every
number above was measured off the exported mesh.

## Build log

- outer edges              fillet 1.50 mm
- inside corner filleted 5.0 mm - a sharp internal corner is a stress raiser and where a printed bracket cracks
- prints standing on its back edge so the layers run ACROSS the bending load - printed flat this part is roughly a third as strong
