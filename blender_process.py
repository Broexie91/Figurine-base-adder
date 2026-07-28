import bpy
import sys
import math
import os
import traceback
import bmesh
from mathutils import Vector

# Force unbuffered stdout so every print() appears in Railway logs immediately.
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    import functools
    print = functools.partial(print, flush=True)

print("=== BLENDER SCRIPT STARTED ===", flush=True)
print(f"Python version: {sys.version}")
print(f"Blender version: {bpy.app.version_string}")
print(f"Arguments received: {sys.argv}")


# ====================== HELPERS ======================

def get_bounds(objs):
    bmin = Vector((float('inf'),) * 3)
    bmax = Vector((-float('inf'),) * 3)
    for obj in objs:
        for corner in obj.bound_box:
            v = obj.matrix_world @ Vector(corner)
            bmin = Vector(min(a, b) for a, b in zip(bmin, v))
            bmax = Vector(max(a, b) for a, b in zip(bmax, v))
    return bmin, bmax


def get_feet_verts(obj, height_mm):
    z_threshold_mm = max(5.0, height_mm * 0.04)
    mesh = obj.data
    verts = [obj.matrix_world @ v.co for v in mesh.vertices]
    if not verts:
        return [], float('inf')
    bmin_z = min(v.z for v in verts)
    feet = [v for v in verts if v.z <= bmin_z + z_threshold_mm]
    print(f"  Foot vertices: {len(feet)} (Z-threshold={z_threshold_mm:.1f}mm)", flush=True)
    return feet, bmin_z


def compute_com(obj):
    mesh = obj.data
    mw   = obj.matrix_world
    total_area = 0.0
    weighted   = Vector((0.0, 0.0, 0.0))
    for poly in mesh.polygons:
        verts_world = [mw @ mesh.vertices[vi].co for vi in poly.vertices]
        v0 = verts_world[0]
        for i in range(1, len(verts_world) - 1):
            v1 = verts_world[i]
            v2 = verts_world[i + 1]
            area       = ((v1 - v0).cross(v2 - v0)).length / 2.0
            centroid   = (v0 + v1 + v2) / 3.0
            weighted  += centroid * area
            total_area += area
    if total_area < 1e-12:
        all_v = [mw @ v.co for v in mesh.vertices]
        return sum(all_v, Vector()) / len(all_v)
    return weighted / total_area


def point_in_polygon_2d(point, polygon):
    x, y   = point.x, point.y
    n      = len(polygon)
    inside = False
    px, py = polygon[-1].x, polygon[-1].y
    for i in range(n):
        qx, qy = polygon[i].x, polygon[i].y
        if ((py > y) != (qy > y)) and (x < (qx - px) * (y - py) / (qy - py + 1e-12) + px):
            inside = not inside
        px, py = qx, qy
    return inside


def build_convex_base(foot_verts, bmin_z, thickness_mm, margin_mm=3.0,
                      min_radius_mm=15.0, com_xy=None):
    from mathutils.geometry import convex_hull_2d
    xy_vecs = [Vector((v.x, v.y)) for v in foot_verts]
    if com_xy is not None:
        initial_indices = convex_hull_2d(xy_vecs)
        if len(initial_indices) >= 3:
            initial_poly = [Vector((xy_vecs[i].x, xy_vecs[i].y)) for i in initial_indices]
            if not point_in_polygon_2d(com_xy, initial_poly):
                print(f"  ⚠️  CoM ({com_xy.x:.1f}, {com_xy.y:.1f}mm) is outside foot hull — expanding to include it.", flush=True)
                xy_vecs.append(Vector((com_xy.x, com_xy.y)))
            else:
                print(f"  ✅ CoM ({com_xy.x:.1f}, {com_xy.y:.1f}mm) is inside foot hull.", flush=True)
    hull_indices = convex_hull_2d(xy_vecs)
    if len(hull_indices) < 3:
        print("  ⚠️  Convex hull degenerate (<3 pts), using min_radius circle.", flush=True)
        hull_pts = []
        steps = 32
        cx = sum(v.x for v in foot_verts) / len(foot_verts)
        cy = sum(v.y for v in foot_verts) / len(foot_verts)
        for i in range(steps):
            a = 2 * math.pi * i / steps
            hull_pts.append(Vector((cx + min_radius_mm * math.cos(a),
                                     cy + min_radius_mm * math.sin(a))))
    else:
        hull_pts = [Vector((xy_vecs[i].x, xy_vecs[i].y)) for i in hull_indices]
    cx = sum(p.x for p in hull_pts) / len(hull_pts)
    cy = sum(p.y for p in hull_pts) / len(hull_pts)
    expanded = []
    for p in hull_pts:
        dx, dy = p.x - cx, p.y - cy
        dist = math.sqrt(dx*dx + dy*dy)
        if dist < 1e-6:
            expanded.append(Vector((p.x, p.y)))
        else:
            scale = (dist + margin_mm) / dist
            expanded.append(Vector((cx + dx * scale, cy + dy * scale)))
    max_dist = max(math.sqrt((p.x - cx)**2 + (p.y - cy)**2) for p in expanded)
    if max_dist < min_radius_mm:
        print(f"  ⚠️  Hull radius {max_dist:.1f}mm < min {min_radius_mm}mm, scaling up.", flush=True)
        scale = min_radius_mm / max_dist
        expanded = [Vector((cx + (p.x - cx) * scale, cy + (p.y - cy) * scale)) for p in expanded]
        max_dist = min_radius_mm
    print(f"  Convex hull base: {len(expanded)} vertices, max_radius={max_dist:.1f}mm, margin={margin_mm}mm", flush=True)
    top_z    = bmin_z + 0.5
    bottom_z = bmin_z - thickness_mm
    bm = bmesh.new()
    top_verts = [bm.verts.new(Vector((p.x, p.y, top_z))) for p in expanded]
    bot_verts = [bm.verts.new(Vector((p.x, p.y, bottom_z))) for p in expanded]
    n = len(expanded)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new([top_verts[i], top_verts[j], bot_verts[j], bot_verts[i]])
    bm.faces.new(top_verts)
    bm.faces.new(list(reversed(bot_verts)))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    base_mesh = bpy.data.meshes.new("ConvexBase")
    bm.to_mesh(base_mesh)
    bm.free()
    base_obj = bpy.data.objects.new("ConvexBase", base_mesh)
    bpy.context.collection.objects.link(base_obj)
    bpy.context.view_layer.objects.active = base_obj
    base_obj.select_set(True)
    return base_obj


def check_manifold(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    open_edges = [e for e in bm.edges if not e.is_manifold]
    non_manifold_verts = [v for v in bm.verts if not v.is_manifold]
    bm.free()
    return len(open_edges), len(non_manifold_verts)


def safety_snapshot(obj):
    bmin, bmax = get_bounds([obj])
    return len(obj.data.vertices), (bmax.z - bmin.z)


def check_safety(obj, verts_before, height_before, label="step"):
    verts_after, height_after = safety_snapshot(obj)
    vert_ratio = verts_after / max(verts_before, 1)
    height_ratio = height_after / max(height_before, 1e-6)
    if vert_ratio < 0.92 or height_ratio < 0.97:
        print(f"  🚨 SAFETY ABORT after {label}: verts {verts_before}→{verts_after} ({vert_ratio:.1%}), height {height_before:.1f}→{height_after:.1f}mm ({height_ratio:.1%})", flush=True)
        return False
    print(f"  ✅ Safety OK after {label}: verts={verts_after}, height={height_after:.1f}mm", flush=True)
    return True


def repair_mesh(obj, merge_threshold=0.01, interpolate_uvs=True):
    """
    Robust mesh repair using bmesh.ops.

    interpolate_uvs=True  → average UVs from all neighboring faces (normal path)
    interpolate_uvs=False → copy UV from the spatially closest neighboring face
                            (safe for early cleanup — follows geometry, not UV islands)
    """
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    stats = {}
    before_edges = len(bm.edges)
    before_faces = len(bm.faces)
    bmesh.ops.dissolve_degenerate(bm, dist=merge_threshold, edges=bm.edges[:])
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    stats['degenerate_edges_removed'] = before_edges - len(bm.edges)
    stats['degenerate_faces_removed'] = before_faces - len(bm.faces)
    before_verts = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=merge_threshold)
    bm.verts.ensure_lookup_table()
    stats['doubles_removed'] = before_verts - len(bm.verts)
    bm.edges.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active
    try:
        result = bmesh.ops.holes_fill(bm, edges=bm.edges[:], sides=0)
        new_faces = result.get('faces', [])
        stats['holes_filled'] = len(new_faces)

        if uv_layer and new_faces:
            new_face_set = set(new_faces)
            fixed_loops = 0

            if interpolate_uvs:
                # Average of all neighbor UVs (normal path)
                for face in new_faces:
                    for loop in face.loops:
                        vert = loop.vert
                        neighbor_uvs = []
                        for other_loop in vert.link_loops:
                            if other_loop.face not in new_face_set:
                                neighbor_uvs.append(other_loop[uv_layer].uv.copy())
                        if neighbor_uvs:
                            avg_u = sum(uv.x for uv in neighbor_uvs) / len(neighbor_uvs)
                            avg_v = sum(uv.y for uv in neighbor_uvs) / len(neighbor_uvs)
                            loop[uv_layer].uv = (avg_u, avg_v)
                            fixed_loops += 1
                print(f"  🎨 Interpolated UVs for {fixed_loops} loops on {len(new_faces)} hole-filled faces", flush=True)
            else:
                # Safe path: for each new face, find the existing neighboring face
                # whose center is closest in 3D space, then copy UVs from that face.
                # This follows the geometric surface (hairline, skin, etc.) instead of
                # a random UV-island order.
                for face in new_faces:
                    face_center = face.calc_center_median()
                    best_dist = float('inf')
                    best_uvs = None  # list of (vert, uv) from the closest face

                    # Collect candidate neighbor faces via the vertices of this new face
                    candidates = {}
                    for loop in face.loops:
                        for other_loop in loop.vert.link_loops:
                            other_face = other_loop.face
                            if other_face in new_face_set:
                                continue
                            if other_face.index not in candidates:
                                candidates[other_face.index] = other_face

                    for of in candidates.values():
                        d = (of.calc_center_median() - face_center).length_squared
                        if d < best_dist:
                            best_dist = d
                            # Build a vert→uv map from this closest face
                            best_uvs = {}
                            for ol in of.loops:
                                best_uvs[ol.vert.index] = ol[uv_layer].uv.copy()

                    if best_uvs is not None:
                        for loop in face.loops:
                            vi = loop.vert.index
                            if vi in best_uvs:
                                loop[uv_layer].uv = best_uvs[vi]
                            else:
                                # Fallback: any UV from the closest face
                                loop[uv_layer].uv = next(iter(best_uvs.values()))
                            fixed_loops += 1
                print(f"  🎨 Closest-face UV assigned to {fixed_loops} loops on {len(new_faces)} hole-filled faces", flush=True)
    except (TypeError, AttributeError):
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.fill_holes(sides=0)
        bpy.ops.object.mode_set(mode='OBJECT')
        stats['holes_filled'] = -1
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    print(f"  🔧 repair_mesh: degenerate_edges={stats.get('degenerate_edges_removed', 0)}, degenerate_faces={stats.get('degenerate_faces_removed', 0)}, doubles={stats['doubles_removed']}, holes={stats['holes_filled']}", flush=True)
    return stats


def deep_repair(obj, max_iterations=3):
    print("  Running deep_repair...", flush=True)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    wire_edges = [e for e in bm.edges if e.is_wire]
    if wire_edges:
        bmesh.ops.delete(bm, geom=wire_edges, context='EDGES')
        print(f"    Deleted {len(wire_edges)} wire edges", flush=True)
    bm.verts.ensure_lookup_table()
    loose_verts = [v for v in bm.verts if not v.link_edges]
    if loose_verts:
        bmesh.ops.delete(bm, geom=loose_verts, context='VERTS')
        print(f"    Deleted {len(loose_verts)} loose vertices", flush=True)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    interior_faces = []
    for f in bm.faces:
        if all(len(e.link_faces) > 2 for e in f.edges):
            interior_faces.append(f)
    if interior_faces:
        bmesh.ops.delete(bm, geom=interior_faces, context='FACES')
        print(f"    Deleted {len(interior_faces)} interior faces", flush=True)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for iteration in range(max_iterations):
        open_e, _ = check_manifold(obj)
        if open_e == 0:
            print(f"    ✅ Mesh is manifold after iteration {iteration}", flush=True)
            break
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.mesh.select_non_manifold(extend=False, use_wire=True, use_boundary=True, use_multi_face=True, use_non_contiguous=True, use_verts=True)
        try:
            bpy.ops.mesh.fill()
        except RuntimeError:
            pass
        bpy.ops.mesh.remove_doubles(threshold=0.03)
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.mesh.fill_holes(sides=0)
        bpy.ops.object.mode_set(mode='OBJECT')
        open_e_after, _ = check_manifold(obj)
        print(f"    Iteration {iteration + 1}: open_edges {open_e} → {open_e_after}", flush=True)
        if open_e_after >= open_e:
            break
        open_e = open_e_after


def remove_interior_faces_safe(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    interior_faces = []
    for f in bm.faces:
        if all(len(e.link_faces) > 2 for e in f.edges):
            interior_faces.append(f)
    count = len(interior_faces)
    if count > 0:
        bmesh.ops.delete(bm, geom=interior_faces, context='FACES')
        bm.to_mesh(obj.data)
        obj.data.update()
        print(f"  🗑️ remove_interior_faces_safe: deleted {count} interior faces", flush=True)
    else:
        print("  ✅ remove_interior_faces_safe: no interior faces found", flush=True)
    bm.free()
    return count


def fix_normals_per_shell(obj):
    from mathutils.bvhtree import BVHTree
    print("Running per-shell normals fix...", flush=True)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    visited = set()
    shells = []
    for face in bm.faces:
        if face.index in visited:
            continue
        shell = []
        queue = [face]
        while queue:
            f = queue.pop()
            if f.index in visited:
                continue
            visited.add(f.index)
            shell.append(f)
            for edge in f.edges:
                for linked_face in edge.link_faces:
                    if linked_face.index not in visited:
                        queue.append(linked_face)
        shells.append(shell)
    print(f"  Found {len(shells)} shell(s)", flush=True)
    bm.faces.ensure_lookup_table()
    bvh = BVHTree.FromBMesh(bm)
    total_flipped = 0
    shells_flipped = 0
    volume_threshold = 0.01
    for i, shell in enumerate(shells):
        signed_vol = 0.0
        for face in shell:
            verts = face.verts
            if len(verts) < 3:
                continue
            v0 = verts[0].co
            for j in range(1, len(verts) - 1):
                v1 = verts[j].co
                v2 = verts[j + 1].co
                signed_vol += v0.dot(v1.cross(v2)) / 6.0
        needs_flip = False
        if abs(signed_vol) > volume_threshold:
            if signed_vol < 0:
                needs_flip = True
        else:
            inward_votes = 0
            outward_votes = 0
            sample_faces = shell[:50] if len(shell) > 50 else shell
            for face in sample_faces:
                centroid = face.calc_center_median()
                normal = face.normal
                if normal.length < 1e-6:
                    continue
                ray_origin = centroid + normal * 0.02
                hit_loc, hit_normal, hit_index, hit_dist = bvh.ray_cast(ray_origin, normal)
                if hit_loc is not None and hit_dist < 50.0:
                    inward_votes += 1
                else:
                    outward_votes += 1
            if inward_votes > outward_votes:
                needs_flip = True
        if needs_flip:
            for face in shell:
                face.normal_flip()
            total_flipped += len(shell)
            shells_flipped += 1
    if total_flipped > 0:
        print(f"  🔄 Flipped {total_flipped} faces across {shells_flipped} shell(s)", flush=True)
    else:
        print(f"  ✅ All {len(shells)} shell normals already point outward", flush=True)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return total_flipped


def remove_ghost_shells(obj, min_faces=50):
    print(f"Removing ghost shells (threshold: {min_faces} faces)...", flush=True)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    visited = set()
    shells = []
    for face in bm.faces:
        if face.index in visited:
            continue
        shell = []
        queue = [face]
        while queue:
            f = queue.pop()
            if f.index in visited:
                continue
            visited.add(f.index)
            shell.append(f)
            for edge in f.edges:
                for linked_face in edge.link_faces:
                    if linked_face.index not in visited:
                        queue.append(linked_face)
        shells.append(shell)
    print(f"  Found {len(shells)} shell(s)", flush=True)
    if len(shells) <= 1:
        bm.free()
        print("  ✅ Single shell — nothing to remove.", flush=True)
        return 0
    shells.sort(key=lambda s: len(s), reverse=True)
    faces_to_delete = []
    removed_count = 0
    removed_faces_total = 0
    kept_count = 0
    kept_faces_total = 0
    for i, shell in enumerate(shells):
        n_faces = len(shell)
        if i == 0:
            kept_count += 1
            kept_faces_total += n_faces
        elif n_faces < min_faces:
            faces_to_delete.extend(shell)
            removed_count += 1
            removed_faces_total += n_faces
        else:
            kept_count += 1
            kept_faces_total += n_faces
    if faces_to_delete:
        bmesh.ops.delete(bm, geom=faces_to_delete, context='FACES')
        bm.to_mesh(obj.data)
        obj.data.update()
        print(f"  🗑️ Removed {removed_count} ghost shell(s) ({removed_faces_total} faces total), kept {kept_count} shell(s) ({kept_faces_total} faces)", flush=True)
    else:
        print(f"  ✅ No ghost shells found (all {len(shells)} shells ≥ {min_faces} faces).", flush=True)
    bm.free()
    return removed_count


def remove_ghost_shells_safe(obj, min_faces=12, bottom_protect_ratio=0.18):
    print(f"Removing ghost shells SAFE (min_faces={min_faces}, bottom_protect={bottom_protect_ratio:.0%})...", flush=True)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    bmin, bmax = get_bounds([obj])
    protect_z = bmin.z + (bmax.z - bmin.z) * bottom_protect_ratio
    visited = set()
    shells = []
    for face in bm.faces:
        if face.index in visited:
            continue
        shell = []
        queue = [face]
        while queue:
            f = queue.pop()
            if f.index in visited:
                continue
            visited.add(f.index)
            shell.append(f)
            for edge in f.edges:
                for linked_face in edge.link_faces:
                    if linked_face.index not in visited:
                        queue.append(linked_face)
        shells.append(shell)
    print(f"  Found {len(shells)} shell(s)", flush=True)
    if len(shells) <= 1:
        bm.free()
        print("  ✅ Single shell — nothing to remove.", flush=True)
        return 0
    shells.sort(key=lambda s: len(s), reverse=True)
    faces_to_delete = []
    removed_count = 0
    removed_faces_total = 0
    kept_count = 0
    kept_faces_total = 0
    for i, shell in enumerate(shells):
        n_faces = len(shell)
        shell_min_z = min(f.calc_center_median().z for f in shell)
        protect = False
        if i == 0:
            protect = True
        elif shell_min_z <= protect_z:
            protect = True
            print(f"  🛡️ Protecting shell with {n_faces} faces (min_z={shell_min_z:.1f} ≤ {protect_z:.1f})", flush=True)
        elif n_faces >= min_faces:
            protect = True
        if protect:
            kept_count += 1
            kept_faces_total += n_faces
        else:
            faces_to_delete.extend(shell)
            removed_count += 1
            removed_faces_total += n_faces
    if faces_to_delete:
        bmesh.ops.delete(bm, geom=faces_to_delete, context='FACES')
        bm.to_mesh(obj.data)
        obj.data.update()
        print(f"  🗑️ Removed {removed_count} ghost shell(s) ({removed_faces_total} faces), kept {kept_count} shell(s) ({kept_faces_total} faces)", flush=True)
    else:
        print(f"  ✅ No removable ghost shells (all protected or large enough).", flush=True)
    bm.free()
    return removed_count


def pin_new_face_uvs(obj, uv_coord=(0.008, 0.008)):
    import numpy as np
    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    if not uv_layer:
        print("  ⚠️  No active UV layer found, skipping UV pin.")
        return
    n_loops = len(mesh.loops)
    if n_loops == 0:
        return
    uvs = np.empty(n_loops * 2, dtype=np.float32)
    uv_layer.data.foreach_get("uv", uvs)
    uvs = uvs.reshape(n_loops, 2)
    out_of_range = ~((uvs[:, 0] >= 0.0) & (uvs[:, 0] <= 1.0) & (uvs[:, 1] >= 0.0) & (uvs[:, 1] <= 1.0))
    fixed = int(out_of_range.sum())
    if fixed > 0:
        uvs[out_of_range] = uv_coord
        uv_layer.data.foreach_set("uv", uvs.ravel())
    print(f"  ✅ Pinned {fixed} out-of-range UV loops → {uv_coord} (original atlas untouched)", flush=True)


def pin_base_face_uvs(obj, base_top_z, uv_coord=(0.008, 0.008)):
    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    if not uv_layer:
        print("  ⚠️  No active UV layer found, skipping base UV pin.")
        return
    pinned_loops = 0
    total_base_faces = 0
    for poly in mesh.polygons:
        if poly.center.z <= base_top_z:
            total_base_faces += 1
            for loop_idx in poly.loop_indices:
                current_uv = uv_layer.data[loop_idx].uv
                if abs(current_uv[0] - uv_coord[0]) > 0.001 or abs(current_uv[1] - uv_coord[1]) > 0.001:
                    uv_layer.data[loop_idx].uv = uv_coord
                    pinned_loops += 1
    print(f"  ✅ Base UV fix: pinned {pinned_loops} loops on {total_base_faces} base faces (Z ≤ {base_top_z:.2f}mm)", flush=True)


def fix_uv_outliers(obj, uv_dist_threshold=0.15):
    import numpy as np
    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    if not uv_layer:
        print("  ⚠️  No UV layer, skipping UV outlier fix.", flush=True)
        return 0
    n_polys = len(mesh.polygons)
    n_loops = len(mesh.loops)
    n_verts = len(mesh.vertices)
    if n_polys == 0:
        return 0
    print(f"  Scanning {n_polys} faces for UV outliers (threshold={uv_dist_threshold})...", flush=True)
    uv_data = np.empty(n_loops * 2, dtype=np.float64)
    uv_layer.data.foreach_get("uv", uv_data)
    uv_data = uv_data.reshape(n_loops, 2)
    loop_starts = np.empty(n_polys, dtype=np.int32)
    loop_totals = np.empty(n_polys, dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", loop_starts)
    mesh.polygons.foreach_get("loop_total", loop_totals)
    vert_indices = np.empty(n_loops, dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", vert_indices)
    uv_centroids = np.zeros((n_polys, 2), dtype=np.float64)
    if np.all(loop_totals == 3):
        uv_centroids = uv_data.reshape(n_polys, 3, 2).mean(axis=1)
    elif np.all(loop_totals == loop_totals[0]):
        k = int(loop_totals[0])
        uv_centroids = uv_data.reshape(n_polys, k, 2).mean(axis=1)
    else:
        for i in range(n_polys):
            s = int(loop_starts[i])
            t = int(loop_totals[i])
            uv_centroids[i] = uv_data[s:s+t].mean(axis=0)
    vert_to_faces = [[] for _ in range(n_verts)]
    for i in range(n_polys):
        s = int(loop_starts[i])
        t = int(loop_totals[i])
        for j in range(s, s + t):
            vert_to_faces[vert_indices[j]].append(i)
    threshold_sq = uv_dist_threshold * uv_dist_threshold
    outliers = []
    for i in range(n_polys):
        cx, cy = uv_centroids[i]
        s = int(loop_starts[i])
        t = int(loop_totals[i])
        has_close = False
        best_fi = -1
        best_dsq = float('inf')
        for j in range(s, s + t):
            for ni in vert_to_faces[vert_indices[j]]:
                if ni == i:
                    continue
                dx = cx - uv_centroids[ni, 0]
                dy = cy - uv_centroids[ni, 1]
                dsq = dx * dx + dy * dy
                if dsq < threshold_sq:
                    has_close = True
                    break
                if dsq < best_dsq:
                    best_dsq = dsq
                    best_fi = ni
            if has_close:
                break
        if not has_close and best_fi >= 0:
            outliers.append((i, best_fi))
    if not outliers:
        print(f"  ✅ No UV outlier faces detected (checked {n_polys} faces).", flush=True)
        return 0
    for face_idx, neighbor_idx in outliers:
        s  = int(loop_starts[face_idx])
        t  = int(loop_totals[face_idx])
        ns = int(loop_starts[neighbor_idx])
        nt = int(loop_totals[neighbor_idx])
        n_vert_uvs = {}
        for j in range(ns, ns + nt):
            n_vert_uvs[int(vert_indices[j])] = uv_data[j].copy()
        n_centroid = uv_centroids[neighbor_idx]
        for j in range(s, s + t):
            vi = int(vert_indices[j])
            if vi in n_vert_uvs:
                uv_data[j] = n_vert_uvs[vi]
            else:
                uv_data[j] = n_centroid
    uv_layer.data.foreach_set("uv", uv_data.ravel())
    print(f"  🎨 Fixed {len(outliers)} UV outlier faces out of {n_polys} (threshold={uv_dist_threshold}).", flush=True)
    return len(outliers)


def robust_boolean_union(target_obj, tool_obj, modifier_name="Union", fix_normals=True):
    bpy.ops.object.select_all(action='DESELECT')
    target_obj.select_set(True)
    bpy.context.view_layer.objects.active = target_obj
    open_e, non_m = check_manifold(target_obj)
    print(f"  Target manifold check before boolean: open_edges={open_e}, non_manifold_verts={non_m}")
    vert_before = len(target_obj.data.vertices)
    def _try_solver(solver_name):
        mod = target_obj.modifiers.new(name=f"{modifier_name}_{solver_name}", type='BOOLEAN')
        mod.operation = 'UNION'
        mod.object = tool_obj
        mod.solver = solver_name
        try:
            bpy.ops.object.modifier_apply(modifier=mod.name)
            new_verts = len(target_obj.data.vertices)
            success = new_verts != vert_before
            print(f"  [{solver_name}] verts before={vert_before}, after={new_verts} → {'✅ success' if success else '❌ silent failure'}")
            if success and fix_normals:
                bm = bmesh.new()
                bm.from_mesh(target_obj.data)
                bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
                bm.to_mesh(target_obj.data)
                bm.free()
                target_obj.data.update()
            elif success and not fix_normals:
                print(f"  ⚡ Skipping post-boolean normals recalc (raw mode — original faces untouched)", flush=True)
            return success
        except Exception as e:
            print(f"  [{solver_name}] threw error: {e}")
            mod_check = target_obj.modifiers.get(f"{modifier_name}_{solver_name}")
            if mod_check:
                target_obj.modifiers.remove(mod_check)
            return False
    if _try_solver('FLOAT'):
        bpy.data.objects.remove(tool_obj, do_unlink=True)
        return True
    print(f"  ⚠️ FLOAT failed, trying EXACT for {modifier_name}...")
    if _try_solver('EXACT'):
        bpy.data.objects.remove(tool_obj, do_unlink=True)
        return True
    print(f"🚨 All boolean solvers failed for {modifier_name}. Falling back to JOIN + weld...")
    bpy.ops.object.select_all(action='DESELECT')
    target_obj.select_set(True)
    tool_obj.select_set(True)
    bpy.context.view_layer.objects.active = target_obj
    bpy.ops.object.join()
    bm = bmesh.new()
    bm.from_mesh(target_obj.data)
    bm.verts.ensure_lookup_table()
    before_verts = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.05)
    bm.verts.ensure_lookup_table()
    welded = before_verts - len(bm.verts)
    if fix_normals:
        bm.faces.ensure_lookup_table()
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    else:
        print(f"  ⚡ Skipping post-JOIN normals recalc (raw mode — original faces untouched)", flush=True)
    bm.to_mesh(target_obj.data)
    bm.free()
    target_obj.data.update()
    print(f"  ⚠️ {modifier_name} completed via JOIN (welded {welded} seam vertices).")
    return False


# ====================== MAIN ======================

try:
    argv = sys.argv[sys.argv.index("--") + 1:]
    input_path     = argv[0]
    output_path    = argv[1]
    size_cm        = float(argv[2])
    add_base       = argv[3].lower() == 'true' if len(argv) > 3 else True
    add_keychain   = argv[4].lower() == 'true' if len(argv) > 4 else False
    skip_repair    = argv[5].lower() == 'true' if len(argv) > 5 else False
    aggressive     = argv[6].lower() == 'true' if len(argv) > 6 else False

    desired_height_mm = size_cm * 10

    if skip_repair:
        print("⚡ SKIP_REPAIR mode: all mesh repair/fixing will be skipped", flush=True)
    if aggressive:
        print("🔥 AGGRESSIVE / TRIPO mode enabled (UV-safe settings)", flush=True)

    base_thickness_mm = 2.5
    print("Arguments parsed successfully")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.length_unit = 'MILLIMETERS'
    bpy.context.scene.unit_settings.scale_length = 0.001

    print("Importing GLB...")
    bpy.ops.import_scene.gltf(filepath=input_path)

    mesh_objs = [o for o in bpy.data.objects if o.type == 'MESH']
    for obj in mesh_objs:
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.shade_smooth()

    print("Applying transforms on imported objects...")
    for obj in mesh_objs:
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    if len(mesh_objs) > 1:
        bpy.ops.object.join()

    model = bpy.context.active_object
    print(f"Model loaded with {len(model.data.vertices)} vertices", flush=True)

    # SCALE
    bmin, bmax = get_bounds([model])
    current_height = bmax.z - bmin.z
    scale_factor = desired_height_mm / current_height
    model.scale *= scale_factor
    bpy.ops.object.transform_apply(scale=True)
    print(f"Model scaled by {scale_factor:.4f} → target height {desired_height_mm}mm", flush=True)

    # EARLY CLEANUP — only when the mesh is extremely broken.
    # Uses closest-face UV assignment (follows geometry, not UV-island order).
    if aggressive and not skip_repair:
        open_e_early, _ = check_manifold(model)
        print(f"  Open edges after scale: {open_e_early}", flush=True)
        if open_e_early > 5000:
            print("🔥 Early mild cleanup (open edges > 5000, closest-face UVs)...", flush=True)
            verts_b, height_b = safety_snapshot(model)
            repair_mesh(model, merge_threshold=0.015, interpolate_uvs=False)
            open_e, _ = check_manifold(model)
            if open_e > 10000:
                print("  Still extremely many open edges → second pass at 0.03 mm", flush=True)
                repair_mesh(model, merge_threshold=0.03, interpolate_uvs=False)
            check_safety(model, verts_b, height_b, "early_cleanup")
        else:
            print(f"  Skipping early cleanup (only {open_e_early} open edges — preserving UVs)", flush=True)

    # DECIMATION
    if not skip_repair:
        MAX_VERTS = 350_000 if aggressive else 500_000
        TARGET_VERTS = 280_000 if aggressive else 400_000
        vert_count = len(model.data.vertices)
        if vert_count > MAX_VERTS:
            ratio = TARGET_VERTS / vert_count
            print(f"⚠️  Model has {vert_count} vertices (>{MAX_VERTS}). Decimating to ~{TARGET_VERTS} (ratio={ratio:.3f})...", flush=True)
            mod = model.modifiers.new("Decimate_Guard", 'DECIMATE')
            mod.decimate_type = 'COLLAPSE'
            mod.ratio = ratio
            bpy.ops.object.modifier_apply(modifier=mod.name)
            print(f"  ✅ Decimated: {vert_count} → {len(model.data.vertices)} vertices", flush=True)
        else:
            print(f"Vertex count OK: {vert_count} (≤{MAX_VERTS})", flush=True)
    else:
        print("⚡ Skipping decimation in SKIP_REPAIR mode", flush=True)

    # MESH REPAIR
    if not skip_repair:
        print("Running mesh repair (bmesh.ops)...", flush=True)
        open_e_pre, non_m_pre = check_manifold(model)
        print(f"  Pre-repair manifold: open_edges={open_e_pre}, non_manifold_verts={non_m_pre}", flush=True)

        if aggressive:
            verts_b, height_b = safety_snapshot(model)
            remove_ghost_shells_safe(model, min_faces=12, bottom_protect_ratio=0.18)
            if not check_safety(model, verts_b, height_b, "ghost_shells_early"):
                print("  ⚠️ Ghost shell removal was too aggressive — continuing with remaining geometry", flush=True)

        repair_mesh(model, merge_threshold=0.01)

        open_e, non_m = check_manifold(model)
        print(f"  Post-repair manifold: open_edges={open_e}, non_manifold_verts={non_m}", flush=True)

        if open_e > 300:
            print("  ⚠️ Still many open edges, trying mild merge at 0.03mm...", flush=True)
            repair_mesh(model, merge_threshold=0.03)
            open_e, non_m = check_manifold(model)
            print(f"  Post-mild-repair manifold: open_edges={open_e}, non_manifold_verts={non_m}", flush=True)

        if aggressive and open_e > 80:
            print("🔥 Running deep_repair...", flush=True)
            verts_b, height_b = safety_snapshot(model)
            deep_repair(model, max_iterations=6)
            check_safety(model, verts_b, height_b, "deep_repair")
    else:
        print("⚡ Skipping mesh repair (skip_repair=true)", flush=True)

    # BASE
    bmin, bmax = get_bounds([model])

    if add_base:
        print("Adding convex hull base...", flush=True)
        foot_verts, foot_bmin_z = get_feet_verts(model, desired_height_mm)
        if not foot_verts:
            foot_verts = [model.matrix_world @ v.co for v in model.data.vertices]
            foot_bmin_z = bmin.z
            print("  ⚠️  No foot vertices found, using all vertices as fallback.", flush=True)
        com_world = compute_com(model)
        com_xy    = Vector((com_world.x, com_world.y))
        print(f"  Centre of mass (XY): ({com_xy.x:.1f}, {com_xy.y:.1f})mm", flush=True)
        base = build_convex_base(foot_verts, bmin_z=foot_bmin_z, thickness_mm=base_thickness_mm, margin_mm=2.5, min_radius_mm=8.0, com_xy=com_xy)
        gray_mat = bpy.data.materials.new(name="Base_Grey")
        gray_mat.use_nodes = False
        gray_mat.diffuse_color = (0.627, 0.627, 0.627, 1.0)
        model.data.materials.append(gray_mat)
        gray_mat_index = len(model.data.materials) - 1
        base.data.materials.append(gray_mat)
        if model.data.uv_layers.active:
            base.data.uv_layers.new(name=model.data.uv_layers.active.name)
        robust_boolean_union(model, base, "Base_Union", fix_normals=not skip_repair)
        base_top_z = foot_bmin_z + 0.5
        base_faces_fixed = 0
        for poly in model.data.polygons:
            if poly.center.z <= base_top_z:
                if poly.material_index != gray_mat_index:
                    poly.material_index = gray_mat_index
                    base_faces_fixed += 1
        print(f"  🎨 Assigned Base_Grey material to {base_faces_fixed} base faces (Z ≤ {base_top_z:.2f}mm, material_index={gray_mat_index})", flush=True)
        print("Pinning out-of-range UVs after base union...")
        pin_new_face_uvs(model, uv_coord=(0.008, 0.008))
        print("Pinning base region UVs to grey sentinel...")
        pin_base_face_uvs(model, base_top_z=base_top_z, uv_coord=(0.008, 0.008))
        if not skip_repair:
            print("Running post-boolean repair...")
            repair_mesh(model, merge_threshold=0.01)
            if aggressive:
                print("🔥 Extra interior-face cleanup after boolean...", flush=True)
                verts_b, height_b = safety_snapshot(model)
                remove_interior_faces_safe(model)
                check_safety(model, verts_b, height_b, "post_boolean_interior")
            open_e, non_m = check_manifold(model)
            print(f"  Post-base manifold: open_edges={open_e}, non_manifold_verts={non_m}", flush=True)
        print("✅ Base architecture complete!", flush=True)

    # KEYCHAIN
    if add_keychain:
        print("Adding keychain ring...")
        mesh = model.data
        verts_world = [model.matrix_world @ v.co for v in mesh.vertices]
        center_x  = (bmin.x + bmax.x) / 2
        center_y  = (bmin.y + bmax.y) / 2
        highest_v = None
        highest_v_idx = None
        max_z = -float('inf')
        for i, v in enumerate(verts_world):
            if math.hypot(v.x - center_x, v.y - center_y) < 15.0:
                if v.z > max_z:
                    max_z = v.z
                    highest_v = v
                    highest_v_idx = i
        if highest_v is None:
            keychain_x = center_x
            keychain_y = center_y
            keychain_z = bmax.z
        else:
            keychain_x = highest_v.x
            keychain_y = highest_v.y
            keychain_z = highest_v.z
        major_radius = 4.75
        minor_radius = 1.15
        sink_depth   = 0.7
        found_uv     = None
        if highest_v_idx is not None and model.data.uv_layers.active and len(model.data.materials) > 0:
            try:
                for loop in model.data.loops:
                    if loop.vertex_index == highest_v_idx:
                        found_uv = model.data.uv_layers.active.data[loop.index].uv
                        break
            except Exception:
                pass
        bpy.ops.mesh.primitive_torus_add(major_radius=major_radius, minor_radius=minor_radius, location=(keychain_x, keychain_y, keychain_z - sink_depth), rotation=(math.radians(90), 0, 0), generate_uvs=True)
        torus = bpy.context.active_object
        if len(model.data.materials) > 0:
            torus.data.materials.append(model.data.materials[0])
            if torus.data.uv_layers.active and model.data.uv_layers.active:
                torus.data.uv_layers.active.name = model.data.uv_layers.active.name
                fallback_uv = found_uv if found_uv is not None else (0.008, 0.008)
                for loop in torus.data.loops:
                    torus.data.uv_layers.active.data[loop.index].uv = fallback_uv
        robust_boolean_union(model, torus, "Keychain_Union", fix_normals=not skip_repair)
        print("Pinning out-of-range UVs after keychain union...")
        pin_new_face_uvs(model, uv_coord=(0.008, 0.008))
        if not skip_repair:
            repair_mesh(model, merge_threshold=0.01)
            open_e, non_m = check_manifold(model)
            print(f"  Post-keychain manifold: open_edges={open_e}, non_manifold_verts={non_m}", flush=True)

    # TEXTURE EXPORT
    out_dir = os.path.dirname(output_path)
    texture_path = os.path.join(out_dir, "model.png")
    found_texture = False
    print("Searching for embedded textures...", flush=True)
    for mat in bpy.data.materials:
        if mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    img = node.image
                    print(f"Texture found: {img.name} ({img.size[0]}x{img.size[1]})")
                    img.filepath_raw = texture_path
                    img.file_format = 'PNG'
                    img.save()
                    found_texture = True
                    print(f"✅ Texture saved: {texture_path}")
                    break
        if found_texture:
            break
    if not found_texture:
        print("⚠️  No embedded texture found.")

    # FINAL MANIFOLD GATE
    if not skip_repair:
        open_e, non_m = check_manifold(model)
        print(f"FINAL manifold check: open_edges={open_e}, non_manifold_verts={non_m}")
        threshold = 80 if aggressive else 200
        if open_e > threshold:
            print(f"⚠️  {open_e} open edges exceeds threshold ({threshold}). Escalating repair...", flush=True)
            repair_mesh(model, merge_threshold=0.03)
            open_e, non_m = check_manifold(model)
            print(f"  After mild repair: open_edges={open_e}, non_manifold_verts={non_m}", flush=True)
            if open_e > threshold:
                print("  ⚠️ Still non-manifold. Running deep_repair...", flush=True)
                verts_b, height_b = safety_snapshot(model)
                deep_repair(model, max_iterations=6 if aggressive else 5)
                check_safety(model, verts_b, height_b, "final_deep_repair")
                open_e, non_m = check_manifold(model)
                print(f"  After deep_repair: open_edges={open_e}, non_manifold_verts={non_m}", flush=True)
                if aggressive:
                    remove_interior_faces_safe(model)
        if open_e > threshold:
            print(f"  🚨 WARNING: Exporting with {open_e} open edges. Model may have visible holes.", flush=True)
        elif open_e > 0:
            print(f"  ℹ️  {open_e} open edges remain (structural AI mesh overlap — Marketiger will heal).", flush=True)
    else:
        print("⚡ Skipping manifold gate (skip_repair=true)", flush=True)

    # FINAL GHOST SHELLS
    if not skip_repair:
        if aggressive:
            remove_ghost_shells_safe(model, min_faces=15, bottom_protect_ratio=0.18)
        else:
            remove_ghost_shells(model, min_faces=50)
    else:
        print("⚡ Skipping ghost shell removal in SKIP_REPAIR mode", flush=True)

    # UV OUTLIER + TRIANGULATE + NORMALS
    if not skip_repair:
        uv_threshold = 0.10 if aggressive else 0.15

        print("Running UV outlier detection...")
        fixed_count = fix_uv_outliers(model, uv_dist_threshold=uv_threshold)

        print("Triangulating mesh...")
        bpy.ops.object.select_all(action='DESELECT')
        model.select_set(True)
        bpy.context.view_layer.objects.active = model
        mod = model.modifiers.new("Triangulate", 'TRIANGULATE')
        mod.quad_method = 'BEAUTY'
        mod.ngon_method = 'BEAUTY'
        bpy.ops.object.modifier_apply(modifier=mod.name)
        print(f"  ✅ Triangulated: {len(model.data.polygons)} triangles", flush=True)

        if aggressive:
            print(f"🔥 Second UV outlier pass after triangulation (threshold={uv_threshold})...", flush=True)
            fix_uv_outliers(model, uv_dist_threshold=uv_threshold)

        print("Running final per-shell normals fix...")
        flipped = fix_normals_per_shell(model)
        if flipped > 0:
            print(f"  ✅ Fixed {flipped} inward-facing faces before export", flush=True)
    else:
        print("⚡ SKIP_REPAIR mode: skipping UV outlier fix, triangulation and normals fix", flush=True)

    # EXPORT
    bpy.ops.object.select_all(action='DESELECT')
    model.select_set(True)
    bpy.context.view_layer.objects.active = model
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    bmin_exp, bmax_exp = get_bounds([model])
    print(f"Export dimensions (mm): X={bmax_exp.x - bmin_exp.x:.2f}, Y={bmax_exp.y - bmin_exp.y:.2f}, Z={bmax_exp.z - bmin_exp.z:.2f}")

    print("Exporting to OBJ + MTL...")
    export_kwargs = {
        'filepath': output_path,
        'export_selected_objects': True,
        'export_materials': True,
        'export_normals': True,
        'export_uv': True,
        'path_mode': 'STRIP',
        'global_scale': 1.0,
    }
    try:
        export_kwargs['export_triangulated_mesh'] = True
        bpy.ops.wm.obj_export(**export_kwargs)
    except TypeError:
        del export_kwargs['export_triangulated_mesh']
        bpy.ops.wm.obj_export(**export_kwargs)

    mtl_path = output_path.replace('.obj', '.mtl')
    if os.path.exists(mtl_path):
        with open(mtl_path, 'r') as f:
            mtl_contents = f.read()
        print(f"MTL contents:\n{mtl_contents}")
    else:
        print("⚠️  MTL file not found after export!")

    print(f"✅ Export complete: {output_path}")
    print("=== Blender processing finished successfully ===")

except Exception as e:
    print(f"CRITICAL ERROR: {type(e).__name__}: {e}")
    traceback.print_exc()
    sys.exit(1)
