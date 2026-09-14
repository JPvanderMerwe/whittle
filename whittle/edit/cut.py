"""
Cutting a mesh with a plane, and closing the face it leaves.

WHY THIS IS WRITTEN OUT RATHER THAN CALLED
--------------------------------------------
trimesh has `slice_plane`, and it needs `shapely` - for the cap and, in this
version, even for an uncapped cut. Booleans would do it too and need
`manifold3d` or a Blender on the PATH. None of those are installed here, and
the operations that depend on cutting are the ones M2 is judged on:
`flatten_base` and `cut_plane` are two of the five.

Clipping a triangle against a plane is a well-understood piece of arithmetic
and the capping is a planar triangulation. Both are written here with numpy,
scipy and matplotlib, all of which this project already depends on. That is a
few hundred lines against a dependency that would have to be installed on
every machine that ever runs whittle, including the server.

THE CAP IS THE HARD HALF, AND HOLES ARE WHY. Cut a hollowed model and the
face is an annulus - an outer loop and an inner one - and a triangulation that
fans from the centre fills the hole in. So the boundary is walked into loops,
triangulated as one set, and every triangle is kept or dropped on the even-odd
rule: inside an odd number of loops is material, inside an even number is the
hole.
"""

from __future__ import annotations

from typing import Any

#: Distance below which a vertex counts as lying ON the plane. Scaled to the
#: model rather than fixed: 1e-6 is a different proposition on a 5 mm charm
#: and a 300 mm vase.
ON_PLANE_FRACTION = 1e-7


def cut_with_plane(mesh: Any, origin, normal, *, cap: bool = True) -> Any:
    """
    Keep the half of the mesh the normal points AWAY from.

    So a normal of +Z at z=10 keeps everything BELOW z=10, which is the
    convention a cut-off-the-top reads as. `flatten_base` passes -Z to keep
    the top and lose the bottom.

    Returns a new mesh. The original is untouched.
    """
    import numpy as np
    import trimesh

    origin = np.asarray(origin, dtype=float)
    normal = np.asarray(normal, dtype=float)
    length = float(np.linalg.norm(normal))
    if length < 1e-12:
        raise ValueError("the cutting plane has no direction")
    normal = normal / length

    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=np.int64)

    scale = float(max(mesh.bounds[1] - mesh.bounds[0])) or 1.0
    eps = scale * ON_PLANE_FRACTION

    # Signed distance from the plane. Negative is the side we keep.
    distance = (vertices - origin) @ normal
    distance[np.abs(distance) < eps] = 0.0

    kept_vertices: list = [vertices]
    kept_faces: list = []
    extra_vertices: list = []
    next_index = len(vertices)
    boundary: list = []          # pairs of new points along the cut

    # CROSSING POINTS ARE SHARED BETWEEN THE TRIANGLES THAT MEET AT AN EDGE.
    #
    # Minting a fresh point per triangle looks harmless - they land in the
    # same place - but the boundary is then a bag of disconnected segments
    # with no two ends in common, and the loop walk that the cap depends on
    # finds nothing. The cut came out open every time, with the volume right
    # and no cap at all.
    #
    # Keyed on the edge, so the two triangles sharing it get the same index.
    crossings: dict[tuple[int, int], int] = {}

    def add_point(a: int, b: int, point) -> int:
        nonlocal next_index
        key = (a, b) if a < b else (b, a)
        found = crossings.get(key)
        if found is not None:
            return found
        extra_vertices.append(point)
        crossings[key] = next_index
        next_index += 1
        return next_index - 1

    for face in faces:
        d = distance[face]
        inside = d <= 0.0
        count = int(inside.sum())

        if count == 3:
            kept_faces.append(face)
            continue
        if count == 0:
            continue

        # One or two corners survive; the triangle is clipped.
        idx_in = [face[i] for i in range(3) if inside[i]]
        idx_out = [face[i] for i in range(3) if not inside[i]]

        def crossing(a: int, b: int):
            """Where the edge a-b meets the plane."""
            da, db = distance[a], distance[b]
            span = da - db
            if abs(span) < 1e-18:
                return vertices[a]
            t = da / span
            return vertices[a] + t * (vertices[b] - vertices[a])

        if count == 1:
            a = idx_in[0]
            p = add_point(a, idx_out[0], crossing(a, idx_out[0]))
            q = add_point(a, idx_out[1], crossing(a, idx_out[1]))
            kept_faces.append([a, p, q])
            boundary.append((p, q))
        else:
            a, b = idx_in
            c = idx_out[0]
            p = add_point(a, c, crossing(a, c))
            q = add_point(b, c, crossing(b, c))
            # Two triangles, wound to match the original.
            kept_faces.append([a, b, q])
            kept_faces.append([a, q, p])
            boundary.append((p, q))

    if not kept_faces:
        raise ValueError("the cut removed the whole model")

    if extra_vertices:
        kept_vertices.append(np.asarray(extra_vertices, dtype=float))
    all_vertices = np.vstack(kept_vertices)
    all_faces = np.asarray(kept_faces, dtype=np.int64)

    if cap and boundary:
        cap_faces = _cap(all_vertices, boundary, normal, eps)
        if len(cap_faces):
            all_faces = np.vstack([all_faces, cap_faces])

    out = trimesh.Trimesh(vertices=all_vertices, faces=all_faces,
                          process=False)
    out.merge_vertices()

    # TIDY UP AFTER THE WELD, or the mesh is sealed and still not a solid.
    #
    # A triangle that lies almost flat against the cutting plane produces two
    # crossing points a hair apart, and merge_vertices joins them - correctly.
    # What is left behind is a triangle with two identical corners, which has
    # no area, plus whatever duplicate of a real face it collapsed onto. Those
    # leave edges shared by three or four faces: the sphere came out with zero
    # open edges and eighty over-shared ones, which is not watertight for a
    # reason that has nothing to do with holes.
    try:
        area = trimesh.triangles.area(out.triangles)
        out.update_faces(area > 1e-12)
        out.update_faces(out.unique_faces())
        out.remove_unreferenced_vertices()
    except Exception:
        pass
    out.remove_unreferenced_vertices()
    try:
        import trimesh.repair

        trimesh.repair.fix_normals(out)
    except Exception:
        pass
    return out


def _cap(vertices, boundary, normal, eps: float):
    """
    Close the flat face the cut left.

    The boundary is a bag of segments. They are triangulated as one planar
    point set and filtered on the even-odd rule, which is what makes a
    hollowed model's annulus come out as a ring rather than a disc.
    """
    import numpy as np

    if not boundary:
        return np.zeros((0, 3), dtype=np.int64)

    used = sorted({i for pair in boundary for i in pair})
    if len(used) < 3:
        return np.zeros((0, 3), dtype=np.int64)

    points = vertices[used]

    # A 2D frame in the plane, so the triangulation is a plain 2D problem.
    axis = np.eye(3)[int(np.argmin(np.abs(normal)))]
    u = np.cross(normal, axis)
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    flat = np.column_stack([points @ u, points @ v])

    try:
        from scipy.spatial import Delaunay

        tri = Delaunay(flat)
    except Exception:
        return np.zeros((0, 3), dtype=np.int64)

    loops = _loops(boundary)
    if not loops:
        return np.zeros((0, 3), dtype=np.int64)

    index_of = {original: position for position, original in enumerate(used)}
    polygons = []
    for loop in loops:
        ring = np.array([flat[index_of[i]] for i in loop if i in index_of])
        if len(ring) >= 3:
            polygons.append(ring)
    if not polygons:
        return np.zeros((0, 3), dtype=np.int64)

    centres = flat[tri.simplices].mean(axis=1)
    winding = np.zeros(len(centres), dtype=int)
    try:
        from matplotlib.path import Path

        for ring in polygons:
            winding += Path(ring).contains_points(centres).astype(int)
    except Exception:
        return np.zeros((0, 3), dtype=np.int64)

    # EVEN-ODD. Inside one loop is material; inside two - an outer ring and
    # the hole in it - is not.
    keep = (winding % 2) == 1
    if not keep.any():
        return np.zeros((0, 3), dtype=np.int64)

    simplices = tri.simplices[keep]
    faces = np.array([[used[a], used[b], used[c]] for a, b, c in simplices],
                     dtype=np.int64)

    # THE CAP FACES OUTWARD, which is the direction the cut removed material
    # in. Wound the wrong way it is a hole rather than a face, and the mesh
    # reads as inside out where it matters most.
    corner = vertices[faces[:, 0]]
    edge1 = vertices[faces[:, 1]] - corner
    edge2 = vertices[faces[:, 2]] - corner
    facing = np.cross(edge1, edge2) @ normal
    flip = facing < 0
    faces[flip] = faces[flip][:, [0, 2, 1]]
    return faces


def _loops(boundary) -> list[list[int]]:
    """Walk the cut's segments into closed rings."""
    from collections import defaultdict

    neighbours = defaultdict(list)
    for a, b in boundary:
        neighbours[a].append(b)
        neighbours[b].append(a)

    seen: set = set()
    loops: list[list[int]] = []
    for start in list(neighbours):
        if start in seen:
            continue
        loop = [start]
        seen.add(start)
        current, previous = start, None
        while True:
            options = [n for n in neighbours[current]
                       if n != previous and n not in seen]
            if not options:
                break
            nxt = options[0]
            loop.append(nxt)
            seen.add(nxt)
            current, previous = nxt, current
        if len(loop) >= 3:
            loops.append(loop)
    return loops
