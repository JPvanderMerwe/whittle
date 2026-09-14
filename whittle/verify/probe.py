"""
Ray-cast surface heights and the height map.

NO RTREE. trimesh.ray hard-depends on rtree, which is not installed and is not
worth a dependency here. A vectorised barycentric point-in-triangle test over
the projected triangles is exact, fast enough at these mesh sizes, and adds
nothing to the dependency list.

Two entry points, one meaning: "how high is the surface at this (u, v)?"

  surface_heights(mesh, points)  arbitrary points, exact, chunked
  height_map(mesh, nx, ny)       a regular grid, via the shared z-buffer

They must agree, and a test asserts that they do.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh

from whittle.render.raster import AXIS_COLUMNS, Bounds, project_axis, zbuffer

EDGE_EPS = 1e-7

# Keeps the peak of the chunked point test near 100 MB regardless of mesh size.
CHUNK_BYTES = 100_000_000

#: Below this many (point x triangle) pairs the straightforward
#: every-point-against-every-triangle pass is quicker than building a grid
#: to avoid it. Above it the quadratic term dominates everything.
DIRECT_PRODUCT = 20_000_000


def _tris(mesh: trimesh.Trimesh, axis: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if axis not in AXIS_COLUMNS:
        raise ValueError(
            "axis must be one of %s, got %r" % (", ".join(sorted(AXIS_COLUMNS)), axis)
        )
    return project_axis(np.asarray(mesh.vertices, dtype=float), np.asarray(mesh.faces), axis)


def surface_heights(
    mesh: trimesh.Trimesh,
    points,
    axis: str = "z",
) -> list[float]:
    """
    The HIGHEST surface along `axis` above each (u, v) point, or NaN where the
    ray misses the part entirely.

    `points` is a sequence of (u, v) pairs in the plane perpendicular to `axis`
    - for axis="z" that is (x, y) in mm.

    This is the numeric backbone of geometry verification. It is what proves a
    recess is the depth it is supposed to be, without anyone squinting at a
    render.
    """
    tri_u, tri_v, tri_w = _tris(mesh, axis)
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(pts) == 0:
        return []

    au, bu, cu = tri_u[:, 0], tri_u[:, 1], tri_u[:, 2]
    av, bv, cv = tri_v[:, 0], tri_v[:, 1], tri_v[:, 2]
    denom = (bv - cv) * (au - cu) + (cu - bu) * (av - cv)
    live = denom != 0.0          # a triangle projecting to a line covers nothing

    au, bu, cu = au[live], bu[live], cu[live]
    av, bv, cv = av[live], bv[live], cv[live]
    denom = denom[live]
    wa, wb, wc = tri_w[live, 0], tri_w[live, 1], tri_w[live, 2]

    m = len(denom)
    out = np.full(len(pts), np.nan)
    if m == 0:
        return [float(v) for v in out]

    chunk = max(1, min(len(pts), CHUNK_BYTES // (m * 8 * 4)))
    for start in range(0, len(pts), chunk):
        pu = pts[start : start + chunk, 0][:, None]
        pv = pts[start : start + chunk, 1][:, None]

        l1 = ((bv - cv) * (pu - cu) + (cu - bu) * (pv - cv)) / denom
        l2 = ((cv - av) * (pu - cu) + (au - cu) * (pv - cv)) / denom
        l3 = 1.0 - l1 - l2

        inside = (l1 >= -EDGE_EPS) & (l2 >= -EDGE_EPS) & (l3 >= -EDGE_EPS)
        w = l1 * wa + l2 * wb + l3 * wc
        w = np.where(inside, w, -np.inf)

        best = w.max(axis=1)
        out[start : start + chunk] = np.where(np.isfinite(best), best, np.nan)

    return [float(v) for v in out]


def surface_below(
    mesh: trimesh.Trimesh,
    points,
    above,
    axis: str = "z",
    eps: float = 1e-4,
) -> list[float]:
    """
    The highest surface strictly BELOW a given height at each (u, v), or NaN
    where there is nothing underneath.

    This is what turns an overhang from "there is an underside here" into "and
    it falls this far". A 0.30 mm print-in-place shoulder gap and a 26 mm drop
    into open air are both 90-degree undersides and a face normal cannot tell
    them apart.

    `eps` keeps the face doing the asking from finding itself.
    """
    tri_u, tri_v, tri_w = _tris(mesh, axis)
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    tops = np.asarray(above, dtype=float).reshape(-1)
    if len(pts) == 0:
        return []
    if len(tops) != len(pts):
        raise ValueError(
            "points and above must be the same length, got %d and %d"
            % (len(pts), len(tops))
        )

    au, bu, cu = tri_u[:, 0], tri_u[:, 1], tri_u[:, 2]
    av, bv, cv = tri_v[:, 0], tri_v[:, 1], tri_v[:, 2]
    denom = (bv - cv) * (au - cu) + (cu - bu) * (av - cv)
    live = denom != 0.0

    au, bu, cu = au[live], bu[live], cu[live]
    av, bv, cv = av[live], bv[live], cv[live]
    denom = denom[live]
    wa, wb, wc = tri_w[live, 0], tri_w[live, 1], tri_w[live, 2]

    m = len(denom)
    out = np.full(len(pts), np.nan)
    if m == 0:
        return [float(v) for v in out]

    def best_below(rows, cols):
        """
        The highest triangle strictly below each of `rows`, among `cols`.

        rows and cols are index arrays into pts and the live triangles, so the
        same arithmetic serves the whole-mesh path and the bucketed one.
        """
        pu = pts[rows, 0][:, None]
        pv = pts[rows, 1][:, None]
        ceiling = tops[rows][:, None] - eps

        l1 = ((bv[cols] - cv[cols]) * (pu - cu[cols])
              + (cu[cols] - bu[cols]) * (pv - cv[cols])) / denom[cols]
        l2 = ((cv[cols] - av[cols]) * (pu - cu[cols])
              + (au[cols] - cu[cols]) * (pv - cv[cols])) / denom[cols]
        l3 = 1.0 - l1 - l2

        w = l1 * wa[cols] + l2 * wb[cols] + l3 * wc[cols]
        keep = ((l1 >= -EDGE_EPS) & (l2 >= -EDGE_EPS) & (l3 >= -EDGE_EPS)
                & (w < ceiling))
        w = np.where(keep, w, -np.inf)
        return w.max(axis=1)

    # A SPATIAL GRID, BECAUSE THE HONEST VERSION IS QUADRATIC.
    #
    # Testing every point against every triangle is correct and was fine for
    # the meshes this project BUILDS - a few thousand to forty thousand
    # triangles. v8 points it at downloads instead, and a 327,680-triangle
    # model took 240.84 seconds in this one function: the whole printability
    # gate was 267 seconds and everything else in it added up to 0.3.
    #
    # A triangle can only be under a point if their footprints overlap, so
    # triangles go into grid cells by their (u, v) bounding box and each point
    # is tested against its own cell only. The arithmetic per candidate is
    # unchanged, so the answer is unchanged - there is a test that asserts the
    # two agree exactly.
    if len(pts) * m <= DIRECT_PRODUCT:
        chunk = max(1, min(len(pts), CHUNK_BYTES // (m * 8 * 4)))
        every = np.arange(m)
        for start in range(0, len(pts), chunk):
            rows = np.arange(start, min(start + chunk, len(pts)))
            best = best_below(rows, every)
            out[rows] = np.where(np.isfinite(best), best, np.nan)
        return [float(v) for v in out]

    lo_u = np.minimum(np.minimum(au, bu), cu)
    hi_u = np.maximum(np.maximum(au, bu), cu)
    lo_v = np.minimum(np.minimum(av, bv), cv)
    hi_v = np.maximum(np.maximum(av, bv), cv)

    origin_u, origin_v = float(lo_u.min()), float(lo_v.min())
    span_u = max(float(hi_u.max()) - origin_u, 1e-9)
    span_v = max(float(hi_v.max()) - origin_v, 1e-9)

    # Aimed at a handful of triangles per cell. Capped so a huge mesh does not
    # buy a grid bigger than the work it saves.
    side = int(min(max(int(np.sqrt(m / 4.0)), 1), 256))
    cell_u = span_u / side
    cell_v = span_v / side

    def cells_of(u_lo, u_hi, v_lo, v_hi):
        iu0 = np.clip(((u_lo - origin_u) / cell_u).astype(int), 0, side - 1)
        iu1 = np.clip(((u_hi - origin_u) / cell_u).astype(int), 0, side - 1)
        iv0 = np.clip(((v_lo - origin_v) / cell_v).astype(int), 0, side - 1)
        iv1 = np.clip(((v_hi - origin_v) / cell_v).astype(int), 0, side - 1)
        return iu0, iu1, iv0, iv1

    tu0, tu1, tv0, tv1 = cells_of(lo_u, hi_u, lo_v, hi_v)

    # One entry per (triangle, cell it touches). A triangle that straddles a
    # boundary is in both, which is what keeps the result exact.
    # MOST TRIANGLES LAND IN ONE CELL, so that case is done with array
    # arithmetic and only the few that straddle a boundary go round a Python
    # loop. Expanding all of them in Python would put back a per-triangle cost
    # of the kind this grid exists to remove.
    spans = (tu1 - tu0 + 1) * (tv1 - tv0 + 1)
    single = spans == 1
    tri_ids = [np.flatnonzero(single)]
    cell_ids = [tu0[single] * side + tv0[single]]

    for index in np.flatnonzero(~single):
        for iu in range(int(tu0[index]), int(tu1[index]) + 1):
            base = iu * side
            for iv in range(int(tv0[index]), int(tv1[index]) + 1):
                tri_ids.append(np.array([index], dtype=np.int64))
                cell_ids.append(np.array([base + iv], dtype=np.int64))

    tri_ids = np.concatenate(tri_ids).astype(np.int64)
    cell_ids = np.concatenate(cell_ids).astype(np.int64)

    order = np.argsort(cell_ids, kind="stable")
    tri_ids = tri_ids[order]
    cell_ids = cell_ids[order]
    starts = np.searchsorted(cell_ids, np.arange(side * side), side="left")
    stops = np.searchsorted(cell_ids, np.arange(side * side), side="right")

    pu_cell = np.clip(((pts[:, 0] - origin_u) / cell_u).astype(int), 0, side - 1)
    pv_cell = np.clip(((pts[:, 1] - origin_v) / cell_v).astype(int), 0, side - 1)
    point_cell = pu_cell * side + pv_cell

    point_order = np.argsort(point_cell, kind="stable")
    sorted_cells = point_cell[point_order]
    boundaries = np.flatnonzero(np.diff(sorted_cells)) + 1
    for group in np.split(point_order, boundaries):
        if len(group) == 0:
            continue
        cell = int(point_cell[group[0]])
        candidates = tri_ids[starts[cell]:stops[cell]]
        if len(candidates) == 0:
            continue
        best = best_below(group, candidates)
        out[group] = np.where(np.isfinite(best), best, np.nan)

    return [float(v) for v in out]


def height_map(
    mesh: trimesh.Trimesh,
    nx: int = 400,
    ny: int = 400,
    axis: str = "z",
    bounds: Bounds | None = None,
) -> np.ndarray:
    """
    Surface height on a regular grid, as a (ny, nx) array with NaN off the part.

    Row 0 is the LOW end of v. Use numpy.flipud when writing an image, which is
    what render.views does.

    This is the primary geometry-verification visual. A flat-shaded render
    cannot show a recess whose floor shares a normal with the surrounding face -
    the height map can, because it colours by height rather than by lighting.
    """
    tri_u, tri_v, tri_w = _tris(mesh, axis)
    if bounds is None:
        bounds = Bounds(
            float(tri_u.min()), float(tri_u.max()), float(tri_v.min()), float(tri_v.max())
        )
    depth, _ = zbuffer(tri_u, tri_v, tri_w, nx, ny, bounds)
    return np.where(np.isfinite(depth), depth, np.nan)


def grid_coords(bounds: Bounds, nx: int, ny: int) -> tuple[np.ndarray, np.ndarray]:
    """Pixel-centre coordinates of a height map, matching zbuffer exactly."""
    us = bounds.u0 + (np.arange(nx) + 0.5) * (bounds.width / nx)
    vs = bounds.v0 + (np.arange(ny) + 0.5) * (bounds.height / ny)
    return us, vs


@dataclass
class SurfaceLevel:
    """One flat surface facing along the print axis."""

    height_mm: float
    area_mm2: float


def surface_levels(
    mesh: trimesh.Trimesh,
    axis: str = "z",
    angle_tol_deg: float = 1.0,
    min_area_mm2: float = 0.05,
) -> list[SurfaceLevel]:
    """
    The distinct flat surfaces facing along `axis`, highest first.

    "The height map shows six distinct surface levels" should be a number, not
    an impression. This measures it off the mesh rather than by clustering
    height-map pixels, for two reasons:

      * it is exact and independent of the height map's resolution. A pixel
        cluster misses any surface smaller than a few pixels - the camera dot
        on the keyring is 0.43 mm2 and vanishes at 500x500.
      * a chamfer is a RAMP, not a level. Clustering pixels by value cannot
        tell a 0.4 mm chamfer band from a real step and will happily merge two
        genuine levels through it. A normal test excludes ramps outright.

    Only surfaces facing along +axis are counted, which is exactly what a
    height map down that axis can see.
    """
    col = AXIS_COLUMNS[axis][2]
    normals = np.asarray(mesh.face_normals, dtype=float)
    areas = np.asarray(mesh.area_faces, dtype=float)
    heights = np.asarray(mesh.triangles_center, dtype=float)[:, col]

    flat = normals[:, col] >= np.cos(np.radians(angle_tol_deg))
    if not flat.any():
        return []

    h = heights[flat]
    a = areas[flat]

    order = np.argsort(h)
    h, a = h[order], a[order]

    # A step of more than the flatness tolerance starts a new surface. Faces on
    # one plane agree to floating-point noise, so this is not a judgement call.
    breaks = np.nonzero(np.diff(h) > 1e-4)[0]
    levels = []
    for grp_h, grp_a in zip(np.split(h, breaks + 1), np.split(a, breaks + 1)):
        area = float(grp_a.sum())
        if area >= min_area_mm2:
            levels.append(SurfaceLevel(height_mm=float(np.average(grp_h, weights=grp_a)),
                                       area_mm2=area))
    return sorted(levels, key=lambda l: l.height_mm, reverse=True)


def levels_present_in(hmap: np.ndarray, levels: list[SurfaceLevel], tol_mm: float = 0.02) -> list[bool]:
    """
    Whether each measured level actually shows up in the height map.

    This is what ties the number to the picture: the levels are measured off
    the mesh, and this confirms the map you are about to look at really does
    contain all of them.
    """
    vals = hmap[np.isfinite(hmap)]
    return [bool(np.any(np.abs(vals - lv.height_mm) <= tol_mm)) for lv in levels]
