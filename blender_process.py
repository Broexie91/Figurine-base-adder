import bpy
import sys
import math
import os
import traceback
import bmesh
from mathutils import Vector

# 3D Print Toolbox is a GUI addon and cannot be loaded in Blender headless/background mode.
# All manifold repair is handled by bmesh operations instead.
_print3d_available = False

print("=== BLENDER SCRIPT STARTED ===")
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


def get_feet_bounds(obj, z_threshold_mm=5.0):
    mesh = obj.data
    verts = [obj.matrix_world @ v.co for v in mesh.vertices]
    if not verts:
        return None, None
    bmin_z = min(v.z for v in verts)
    feet = [v for v in verts if v.z <= bmin_z + z_threshold_mm]
    if not feet:
        return None, None
    return (
        Vector((min(v.x for v in feet), min(v.y for v in feet), bmin_z)),
        Vector((max(v.x for v in feet), max(v.y for v in feet), bmin_z)),
    )


def check_manifold(obj):
    """
    Returns (open_edge_count, non_manifold_vert_count).
    Zero for both = watertight/manifold mesh.
    """
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    open_edges = [e for e in bm.edges if not e.is_manifold]
    non_manifold_verts = [v for v in bm.verts if not v.is_manifold]
    bm.free()
    return len(open_edges), len(non_manifold_verts)


def clean_mesh(obj, threshold=0.001, fill_holes=True, fix_normals=True):
    """
    Comprehensive mesh cleanup: remove doubles, fill holes, fix normals.
    Safe to call multiple times.
    """
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles(threshold=threshold)
    if fill_holes:
        bpy.ops.mesh.fill_holes(sides=4)
    if fix_normals:
        bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')


def apply_3d_print_toolbox(obj):
    """
    Attempt 3D Print Toolbox manifold ops — only runs if the addon loaded.
    If unavailable, logs clearly and returns so bmesh fallbacks take over.
    """
    if not _print3d_available:
        print("  ℹ️  3D Print Toolbox not available — skipping, bmesh fallbacks will handle this")
        return
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        if hasattr(bpy.ops.mesh, "print3d_clean_non_manifold"):
            bpy.ops.mesh.print3d_clean_non_manifold()
            print("✅ print3d_clean_non_manifold applied")
        bpy.ops.object.mode_set(mode='OBJECT')

        if hasattr(bpy.ops.object, "print3d_make_manifold"):
            bpy.ops.object.print3d_make_manifold()
            print("✅ print3d_make_manifold applied")
    except Exception as e:
        print(f"⚠️  3D Print Toolbox warning (non-fatal): {e}")
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass


def voxel_remesh_fallback(obj, voxel_size=0.4):
    """
    Voxel remesh — ONLY safe to call on tool objects (base cylinder, torus).
    NEVER call this on the main model: it destroys UV maps completely.
    """
    print(f"🔧 Applying voxel remesh fallback (voxel_size={voxel_size})...")
    if obj.data.uv_layers.active:
        print(f"  🚫 REFUSED: object '{obj.name}' has UV data — voxel remesh would destroy it. Skipping.")
        return
    bpy.context.view_layer.objects.active = obj
    remesh = obj.modifiers.new("Remesh_Fallback", 'REMESH')
    remesh.mode = 'VOXEL'
    remesh.voxel_size = voxel_size
    remesh.use_smooth_shade = True
    bpy.ops.object.modifier_apply(modifier=remesh.name)
    print("✅ Voxel remesh applied")


def bmesh_close_holes(obj, max_hole_verts=50):
    """
    Use bmesh directly to close open boundary loops on the model.
    This is UV-safe: it only adds new faces to fill holes, never
    rebuilds or resamples the mesh topology.
    Much safer than voxel remesh for UV-mapped models.
    """
    bpy.context.view_layer.objects.active = obj
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.edges.ensure_lookup_table()

    # Find all boundary (open) edges
    boundary_edges = [e for e in bm.edges if not e.is_manifold]
    print(f"  bmesh_close_holes: {len(boundary_edges)} boundary edges found")

    if boundary_edges:
        # Fill holes — only fills loops up to max_hole_verts in size
        # to avoid accidentally capping the entire model opening
        bmesh.ops.holes_fill(bm, edges=boundary_edges, sides=max_hole_verts)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    print(f"  ✅ bmesh_close_holes done")


def pin_new_face_uvs(obj, uv_coord=(0.005, 0.005)):
    """
    After a boolean union, ONLY fix faces whose UVs are missing or out-of-range.
    These are the boolean-generated intersection faces that have no valid atlas mapping.
    All original UV islands from the Meshy AI model are left completely untouched.

    Out-of-range UVs (outside 0.0–1.0) are the reliable signature of boolean-created
    faces — Blender interpolates UV coordinates across the cut which often land outside
    the valid texture space.
    """
    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    if not uv_layer:
        print("  ⚠️  No active UV layer found, skipping UV pin.")
        return
    fixed = 0
    for poly in mesh.polygons:
        for loop_idx in poly.loop_indices:
            uv = uv_layer.data[loop_idx].uv
            if not (0.0 <= uv.x <= 1.0 and 0.0 <= uv.y <= 1.0):
                uv_layer.data[loop_idx].uv = uv_coord
                fixed += 1
    print(f"  ✅ Pinned {fixed} out-of-range UV loops → {uv_coord} (original atlas untouched)")


def robust_boolean_union(target_obj, tool_obj, modifier_name="Union"):
    """
    Cascading Boolean fallback:
      1. EXACT solver  (best quality)
      2. FLOAT solver  (brute-force)
      3. Voxel remesh of tool + EXACT retry
      4. JOIN          (last resort — overlapping shells)

    Returns True if a real boolean succeeded, False if JOIN was used.
    """
    bpy.ops.object.select_all(action='DESELECT')
    target_obj.select_set(True)
    bpy.context.view_layer.objects.active = target_obj

    open_e, non_m = check_manifold(target_obj)
    print(f"  Target manifold check before boolean: open_edges={open_e}, non_manifold_verts={non_m}")

    # If the target is non-manifold, boolean solvers will silently fail.
    # Close holes with bmesh first — this is UV-safe unlike voxel remesh.
    if open_e > 0:
        print(f"  Target has {open_e} open edges — running bmesh_close_holes before boolean...")
        bmesh_close_holes(target_obj)
        open_e, non_m = check_manifold(target_obj)
        print(f"  After bmesh_close_holes: open_edges={open_e}, non_manifold_verts={non_m}")

    vert_before = len(target_obj.data.vertices)

    def _try_solver(solver_name, hole_tolerant=False):
        mod = target_obj.modifiers.new(name=f"{modifier_name}_{solver_name}", type='BOOLEAN')
        mod.operation = 'UNION'
        mod.object = tool_obj
        mod.solver = solver_name
        if hole_tolerant:
            try:
                mod.use_hole_tolerant = True
            except Exception:
                pass
        bpy.ops.object.modifier_apply(modifier=mod.name)
        new_verts = len(target_obj.data.vertices)
        success = new_verts > vert_before + 5
        print(f"  [{solver_name}] verts before={vert_before}, after={new_verts} → {'✅ success' if success else '❌ no change'}")
        return success

    # --- Attempt 1: EXACT ---
    if _try_solver('EXACT', hole_tolerant=True):
        bpy.data.objects.remove(tool_obj, do_unlink=True)
        return True

    print(f"⚠️  EXACT {modifier_name} ineffective. Trying FLOAT solver...")

    # --- Attempt 2: FLOAT ---
    if _try_solver('FLOAT'):
        bpy.data.objects.remove(tool_obj, do_unlink=True)
        return True

    print(f"⚠️  FLOAT {modifier_name} also ineffective. Remeshing tool and retrying EXACT...")

    # --- Attempt 3: Voxel-remesh tool, then EXACT again ---
    voxel_remesh_fallback(tool_obj, voxel_size=0.5)
    if _try_solver('EXACT', hole_tolerant=True):
        bpy.data.objects.remove(tool_obj, do_unlink=True)
        return True

    # --- Attempt 4: JOIN (last resort) ---
    print(f"🚨 All boolean attempts failed for {modifier_name}. Falling back to JOIN...")
    bpy.ops.object.select_all(action='DESELECT')
    target_obj.select_set(True)
    tool_obj.select_set(True)
    bpy.context.view_layer.objects.active = target_obj
    bpy.ops.object.join()

    # After JOIN, use UV-safe bmesh hole filler instead of voxel remesh.
    # Voxel remesh would destroy the UV map — never use it on the main model.
    open_e_after, _ = check_manifold(target_obj)
    if open_e_after > 0:
        print(f"  JOIN left {open_e_after} open edges — using bmesh_close_holes (UV-safe)...")
        bmesh_close_holes(target_obj)

    print(f"⚠️  {modifier_name} completed via JOIN.")
    return False


# ====================== MAIN ======================

try:
    # ---- Arguments ----
    argv = sys.argv[sys.argv.index("--") + 1:]
    input_path     = argv[0]
    output_path    = argv[1]
    size_cm        = float(argv[2])
    text_str       = argv[3] if len(argv) > 3 else ""
    if text_str == "--NO-TEXT--":
        text_str = ""
    add_base       = argv[4].lower() == 'true' if len(argv) > 4 else True
    add_keychain   = argv[5].lower() == 'true' if len(argv) > 5 else False

    desired_height_mm = size_cm * 10
    base_thickness_mm = 2.5

    print("Arguments parsed successfully")

    # ---- Scene setup ----
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.length_unit = 'MILLIMETERS'
    bpy.context.scene.unit_settings.scale_length = 0.001

    # ====================== IMPORT GLB ======================
    print("Importing GLB...")
    bpy.ops.import_scene.gltf(filepath=input_path)

    mesh_objs = [o for o in bpy.data.objects if o.type == 'MESH']
    for obj in mesh_objs:
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.shade_smooth()

    if len(mesh_objs) > 1:
        bpy.ops.object.join()

    model = bpy.context.active_object
    print(f"Model loaded with {len(model.data.vertices)} vertices")

    # ====================== PRE-CLEAN (before scaling) ======================
    # Meshy AI outputs often have duplicates, zero-area faces, and flipped normals.
    print("Running pre-clean on raw import...")
    clean_mesh(model, threshold=0.001, fill_holes=True, fix_normals=True)

    open_e, non_m = check_manifold(model)
    print(f"  Post pre-clean manifold: open_edges={open_e}, non_manifold_verts={non_m}")

    # ====================== SCALE ======================
    bmin, bmax = get_bounds([model])
    current_height = bmax.z - bmin.z
    scale_factor = desired_height_mm / current_height
    model.scale *= scale_factor
    bpy.ops.object.transform_apply(scale=True)
    print(f"Model scaled by {scale_factor:.4f} → target height {desired_height_mm}mm")

    # ====================== 3D PRINT TOOLBOX CLEANUP ======================
    print("Applying 3D Print Toolbox manifold repair...")
    apply_3d_print_toolbox(model)

    # Post-toolbox check
    open_e, non_m = check_manifold(model)
    print(f"  Post-toolbox manifold: open_edges={open_e}, non_manifold_verts={non_m}")

    # If still non-manifold after toolbox, run a second clean pass
    if open_e > 0:
        print("  Still non-manifold — running secondary clean pass...")
        clean_mesh(model, threshold=0.005, fill_holes=True, fix_normals=True)
        open_e, non_m = check_manifold(model)
        print(f"  Post-secondary-clean: open_edges={open_e}, non_manifold_verts={non_m}")

    # ====================== TEXTURE EXPORT ======================
    out_dir = os.path.dirname(output_path)
    texture_path = os.path.join(out_dir, "model.png")
    found_texture = False

    # --- Diagnostics: log everything about the imported materials ---
    print(f"=== MATERIAL DIAGNOSTICS ===")
    print(f"Total materials: {len(bpy.data.materials)}")
    print(f"Total images in blend data: {len(bpy.data.images)}")
    for i, mat in enumerate(bpy.data.materials):
        has_nodes = mat.node_tree is not None
        print(f"  Material[{i}]: name='{mat.name}', has_node_tree={has_nodes}")
        if has_nodes:
            for node in mat.node_tree.nodes:
                print(f"    Node: type={node.type}, name='{node.name}'")
                if node.type == 'TEX_IMAGE':
                    print(f"      → image={node.image}, "
                          f"size={node.image.size if node.image else 'N/A'}, "
                          f"source={node.image.source if node.image else 'N/A'}")
    for i, img in enumerate(bpy.data.images):
        print(f"  Image[{i}]: name='{img.name}', size={img.size}, "
              f"source='{img.source}', filepath='{img.filepath_raw}'")
    print(f"=== END MATERIAL DIAGNOSTICS ===")

    # --- Strategy 1: TEX_IMAGE node connected to Base Color (standard Meshy PBR) ---
    print("Searching for embedded textures — Strategy 1: Base Color TEX_IMAGE node...")
    for mat in bpy.data.materials:
        if mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image and node.image.size[0] > 0:
                img = node.image
                print(f"  Found via Strategy 1: '{img.name}' ({img.size[0]}x{img.size[1]})")
                found_texture = True
                break
        if found_texture:
            break

    # --- Strategy 2: Any image in bpy.data.images with pixel data ---
    if not found_texture:
        print("  Strategy 1 failed. Trying Strategy 2: bpy.data.images scan...")
        for img in bpy.data.images:
            if img.size[0] > 0 and img.size[1] > 0 and img.name != 'Render Result':
                print(f"  Found via Strategy 2: '{img.name}' ({img.size[0]}x{img.size[1]})")
                found_texture = True
                break

    if found_texture and img:
        print(f"Injecting sentinel pixels and saving texture ({img.size[0]}x{img.size[1]})...")

        # Use numpy for pixel manipulation — list(img.pixels) on a 2048x2048
        # image copies 16M floats into Python memory and can stall for minutes.
        import numpy as np
        w, h = img.size
        pixels = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(pixels)
        pixels = pixels.reshape((h, w, 4))

        # Bottom-left 4x4: light grey (base/platform colour)
        pixels[:min(4, h), :min(4, w), :] = [0.75, 0.75, 0.75, 1.0]
        # Top-left 4x4: dark grey (text colour)
        pixels[max(0, h - 4):h, :min(4, w), :] = [0.15, 0.15, 0.15, 1.0]

        img.pixels.foreach_set(pixels.ravel())
        img.update()
        img.filepath_raw = texture_path
        img.file_format = 'PNG'
        img.save()
        print(f"✅ Texture saved: {texture_path}")

        # Ensure ALL materials have a TEX_IMAGE node pointing to this image
        # and that it is connected to Base Color — fixes cases where Meshy's
        # node tree has the image loaded but not wired to the BSDF output.
        for mat in bpy.data.materials:
            # Ensure node tree exists (Blender 5.x: use_nodes is deprecated)
            if mat.node_tree is None:
                mat.node_tree = bpy.data.node_groups.new(mat.name, 'ShaderNodeTree')
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links

            bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
            tex_node = next((n for n in nodes if n.type == 'TEX_IMAGE'), None)

            if bsdf is None:
                bsdf = nodes.new('ShaderNodeBsdfPrincipled')

            if tex_node is None:
                tex_node = nodes.new('ShaderNodeTexImage')
                print(f"  Created new TEX_IMAGE node in material '{mat.name}'")

            # Always point to our saved texture
            tex_node.image = img

            # Wire to Base Color if not already connected
            base_color_input = bsdf.inputs.get('Base Color')
            already_linked = any(
                lnk.to_node == bsdf and lnk.to_socket.name == 'Base Color'
                for lnk in links
            )
            if base_color_input and not already_linked:
                links.new(tex_node.outputs['Color'], base_color_input)
                print(f"  Wired TEX_IMAGE → Base Color in material '{mat.name}'")

    else:
        print("⚠️  No texture found via any strategy. Model will export without texture.")

    # ====================== BASE + TEXT ======================
    bmin, bmax = get_bounds([model])
    fmin, fmax = get_feet_bounds(model)

    if fmin and fmax:
        center_x = (fmin.x + fmax.x) / 2
        center_y = (fmin.y + fmax.y) / 2
        radius   = max(fmax.x - fmin.x, fmax.y - fmin.y) / 2 * 1.35
    else:
        center_x = (bmin.x + bmax.x) / 2
        center_y = (bmin.y + bmax.y) / 2
        radius   = max(bmax.x - bmin.x, bmax.y - bmin.y) / 2 * 0.95

    if add_base:
        print("Adding base via boolean union pipeline...")

        adjusted_depth = base_thickness_mm + 0.5
        adj_z = bmin.z - adjusted_depth / 2 + 0.5

        bpy.ops.mesh.primitive_cylinder_add(
            vertices=64,
            radius=radius,
            depth=adjusted_depth,
            location=(center_x, center_y, adj_z),
            calc_uvs=True,
        )
        base = bpy.context.active_object

        if len(model.data.materials) > 0:
            base.data.materials.append(model.data.materials[0])
            if base.data.uv_layers.active and model.data.uv_layers.active:
                base.data.uv_layers.active.name = model.data.uv_layers.active.name
                for loop in base.data.loops:
                    base.data.uv_layers.active.data[loop.index].uv = (0.005, 0.005)

        # Text on base
        if text_str.strip():
            text_loc = (center_x, center_y - radius * 0.65, bmin.z + 0.4)
            bpy.ops.object.text_add(location=text_loc)
            txt = bpy.context.active_object
            txt.data.body     = text_str.upper()[:40]
            txt.data.size     = radius * 0.25
            txt.data.extrude  = 0.5
            txt.data.align_x  = 'CENTER'
            txt.data.align_y  = 'CENTER'
            txt.rotation_euler = (0, 0, 0)
            bpy.context.view_layer.update()

            if txt.dimensions.x > radius * 1.4:
                txt.data.size *= radius * 1.4 / txt.dimensions.x

            bpy.ops.object.convert(target='MESH')
            txt_mesh = bpy.context.active_object

            if len(model.data.materials) > 0:
                txt_mesh.data.materials.append(model.data.materials[0])
                if not txt_mesh.data.uv_layers and model.data.uv_layers.active:
                    txt_mesh.data.uv_layers.new(name=model.data.uv_layers.active.name)
                elif txt_mesh.data.uv_layers.active and model.data.uv_layers.active:
                    txt_mesh.data.uv_layers.active.name = model.data.uv_layers.active.name
                if txt_mesh.data.uv_layers.active:
                    for loop in txt_mesh.data.loops:
                        txt_mesh.data.uv_layers.active.data[loop.index].uv = (0.005, 0.995)

            # Union text into base first
            robust_boolean_union(base, txt_mesh, "Text_Union")

        # Union base into model
        robust_boolean_union(model, base, "Base_Union")

        # Repair UVs: pin only boolean-generated faces with out-of-range UVs.
        # Original Meshy AI atlas UVs are NOT touched.
        print("Pinning out-of-range UVs after base union...")
        pin_new_face_uvs(model, uv_coord=(0.005, 0.005))

        # Final cleanup on unified mesh
        print("Running final seam cleanup...")
        clean_mesh(model, threshold=0.005, fill_holes=True, fix_normals=True)

        open_e, non_m = check_manifold(model)
        print(f"  Post-base manifold: open_edges={open_e}, non_manifold_verts={non_m}")

        # If base union left non-manifold seams, use UV-safe hole filler
        if open_e > 50:
            print(f"  ⚠️  {open_e} open edges after base union — using bmesh_close_holes (UV-safe)...")
            bmesh_close_holes(model)
            open_e, non_m = check_manifold(model)
            print(f"  Post-hole-fill manifold: open_edges={open_e}, non_manifold_verts={non_m}")

        print("✅ Base architecture complete!")

    # ====================== KEYCHAIN ======================
    if add_keychain:
        print("Adding keychain ring...")
        mesh      = model.data
        verts_world = [model.matrix_world @ v.co for v in mesh.vertices]
        center_x  = (bmin.x + bmax.x) / 2
        center_y  = (bmin.y + bmax.y) / 2

        highest_v     = None
        highest_v_idx = None
        max_z         = -float('inf')

        for i, v in enumerate(verts_world):
            if math.hypot(v.x - center_x, v.y - center_y) < 15.0:
                if v.z > max_z:
                    max_z         = v.z
                    highest_v     = v
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

        bpy.ops.mesh.primitive_torus_add(
            major_radius=major_radius,
            minor_radius=minor_radius,
            location=(keychain_x, keychain_y, keychain_z - sink_depth),
            rotation=(math.radians(90), 0, 0),
            generate_uvs=True,
        )
        torus = bpy.context.active_object

        if len(model.data.materials) > 0:
            torus.data.materials.append(model.data.materials[0])
            if torus.data.uv_layers.active and model.data.uv_layers.active:
                torus.data.uv_layers.active.name = model.data.uv_layers.active.name
                fallback_uv = found_uv if found_uv is not None else (0.005, 0.995)
                for loop in torus.data.loops:
                    torus.data.uv_layers.active.data[loop.index].uv = fallback_uv

        robust_boolean_union(model, torus, "Keychain_Union")

        # Repair UVs: pin only boolean-generated faces with out-of-range UVs.
        # Original Meshy AI atlas UVs are NOT touched.
        print("Pinning out-of-range UVs after keychain union...")
        pin_new_face_uvs(model, uv_coord=(0.005, 0.005))

        # Final cleanup on keychain seam
        clean_mesh(model, threshold=0.005, fill_holes=True, fix_normals=True)

        open_e, non_m = check_manifold(model)
        print(f"  Post-keychain manifold: open_edges={open_e}, non_manifold_verts={non_m}")

        if open_e > 50:
            print(f"  ⚠️  {open_e} open edges after keychain union — using bmesh_close_holes (UV-safe)...")
            bmesh_close_holes(model)
            open_e, non_m = check_manifold(model)
            print(f"  Post-hole-fill manifold: open_edges={open_e}, non_manifold_verts={non_m}")

    # ====================== FINAL MANIFOLD GATE ======================
    open_e, non_m = check_manifold(model)
    print(f"FINAL manifold check: open_edges={open_e}, non_manifold_verts={non_m}")

    if open_e > 0:
        print("⚠️  Model is still non-manifold before export. Attempting final repair...")
        apply_3d_print_toolbox(model)
        clean_mesh(model, threshold=0.01, fill_holes=True, fix_normals=True)
        open_e, non_m = check_manifold(model)
        print(f"  After final repair: open_edges={open_e}, non_manifold_verts={non_m}")
        if open_e > 0:
            print("  Still non-manifold — applying UV-safe bmesh hole fill as last resort...")
            bmesh_close_holes(model)
            open_e, non_m = check_manifold(model)
            print(f"  After bmesh_close_holes: open_edges={open_e}, non_manifold_verts={non_m}")

    # ====================== EXPORT ======================
    bpy.ops.object.select_all(action='DESELECT')
    model.select_set(True)
    bpy.context.view_layer.objects.active = model

    # Verify output scale: log bounding-box dimensions in mm
    bmin_exp, bmax_exp = get_bounds([model])
    print(f"Export dimensions (mm): X={bmax_exp.x - bmin_exp.x:.2f}, Y={bmax_exp.y - bmin_exp.y:.2f}, Z={bmax_exp.z - bmin_exp.z:.2f}")

    print("Exporting to OBJ + MTL...")

    export_kwargs = {
        'filepath':                output_path,
        'export_selected_objects': True,
        'export_materials':        True,
        # export_colors omitted: Marketiger may reject vertex colour data
        'export_normals':          True,
        'export_uv':               True,
        'path_mode':               'STRIP',  # outputs "model.png" not an absolute path in MTL
        'global_scale':            1.0,      # model units are mm; keep 1:1
    }

    try:
        export_kwargs['export_triangulated_mesh'] = True
        bpy.ops.wm.obj_export(**export_kwargs)
    except TypeError:
        del export_kwargs['export_triangulated_mesh']
        bpy.ops.wm.obj_export(**export_kwargs)

    # Log MTL contents so texture reference can be verified in Railway logs
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
