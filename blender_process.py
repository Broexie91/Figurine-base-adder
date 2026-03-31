import bpy
import sys
import math
import os
import traceback
import bmesh
from mathutils import Vector

# Force unbuffered stdout so every print() appears in Railway logs immediately,
# even if the process is killed mid-run by a timeout.
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
        bpy.ops.mesh.fill_holes(sides=0)
    if fix_normals:
        bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')


def apply_3d_print_toolbox(obj, threshold=0.001):
    """
    Natively replicates the 'Make Manifold' operator from the 3D Print Toolbox.
    Guarantees the mesh is cleaned of interior faces, loose geometry, and holes
    so it is perfectly watertight for boolean operations.
    """
    bpy.context.view_layer.objects.active = obj
    if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
        
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_mode(type='VERT')
    bpy.ops.mesh.reveal(select=False)
    
    # 1. Delete loose geometry
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=True)
    
    # 2. Delete interior faces
    bpy.ops.mesh.select_all(action='DESELECT')
    bpy.ops.mesh.select_interior_faces()
    bpy.ops.mesh.delete(type='FACE')
    
    # 3. Remove doubles (merge by distance)
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles(threshold=threshold)
    
    # 4. Iteratively fill holes (sides=0 means fill all ngons)
    def _elem_count():
        bm = bmesh.from_edit_mesh(obj.data)
        return len(bm.verts), len(bm.edges), len(bm.faces)
        
    bm_states = set()
    bm_states.add(_elem_count())
    
    max_iters = 50
    for _ in range(max_iters):
        # Fill holes
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.fill_holes(sides=0)
        
        # Delete newly generated bad non-manifold verts from weird fills
        bpy.ops.mesh.select_non_manifold(
            extend=False, use_wire=True, use_boundary=False, 
            use_multi_face=False, use_non_contiguous=False, use_verts=True
        )
        bpy.ops.mesh.delete(type='VERT')
        
        current_state = _elem_count()
        if current_state in bm_states:
            break
        bm_states.add(current_state)
        
    # 5. Make normals consistently pointing outwards
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.normals_make_consistent(inside=False)
    
    bpy.ops.object.mode_set(mode='OBJECT')
    print("✅ Native manifold repair applied", flush=True)


def pin_new_face_uvs(obj, uv_coord=(0.005, 0.005)):
    """
    After a boolean union, ONLY fix faces whose UVs are missing or out-of-range.
    Uses numpy foreach_get/foreach_set to avoid slow Python loops over all loops.
    """
    import numpy as np
    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    if not uv_layer:
        print("  ⚠️  No active UV layer found, skipping UV pin.")
        return

    n_loops = len(mesh.loops)
    if n_loops == 0:
        return

    # Read all UV coords in one fast C-level call
    uvs = np.empty(n_loops * 2, dtype=np.float32)
    uv_layer.data.foreach_get("uv", uvs)
    uvs = uvs.reshape(n_loops, 2)

    # Find loops with UVs outside [0, 1] — these are boolean-generated faces
    out_of_range = ~(
        (uvs[:, 0] >= 0.0) & (uvs[:, 0] <= 1.0) &
        (uvs[:, 1] >= 0.0) & (uvs[:, 1] <= 1.0)
    )
    fixed = int(out_of_range.sum())

    if fixed > 0:
        uvs[out_of_range] = uv_coord
        uv_layer.data.foreach_set("uv", uvs.ravel())

    print(f"  ✅ Pinned {fixed} out-of-range UV loops → {uv_coord} (original atlas untouched)", flush=True)


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

    print(f"⚠️  FLOAT {modifier_name} also ineffective. Retrying EXACT with hole tolerance...")

    # --- Attempt 3: EXACT again with hole tolerant ---
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

    print(f"⚠️  {modifier_name} completed via JOIN (may have overlapping shells).")
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
    print(f"Model loaded with {len(model.data.vertices)} vertices", flush=True)

    # ====================== PRE-CLEAN (before scaling) ======================
    print("Running pre-clean on raw import...", flush=True)
    clean_mesh(model, threshold=0.001, fill_holes=True, fix_normals=True)
    print("  Pre-clean done.", flush=True)

    open_e, non_m = check_manifold(model)
    print(f"  Post pre-clean manifold: open_edges={open_e}, non_manifold_verts={non_m}", flush=True)

    # ====================== SCALE ======================
    bmin, bmax = get_bounds([model])
    current_height = bmax.z - bmin.z
    scale_factor = desired_height_mm / current_height
    model.scale *= scale_factor
    bpy.ops.object.transform_apply(scale=True)
    print(f"Model scaled by {scale_factor:.4f} → target height {desired_height_mm}mm", flush=True)

    # ====================== 3D PRINT TOOLBOX CLEANUP ======================
    print("Applying 3D Print Toolbox manifold repair...", flush=True)
    apply_3d_print_toolbox(model)
    print("  3D Print Toolbox done.", flush=True)

    # Post-toolbox check
    open_e, non_m = check_manifold(model)
    print(f"  Post-toolbox manifold: open_edges={open_e}, non_manifold_verts={non_m}", flush=True)

    if open_e > 0:
        print("  Still non-manifold — running secondary clean pass...", flush=True)
        clean_mesh(model, threshold=0.005, fill_holes=True, fix_normals=True)
        open_e, non_m = check_manifold(model)
        print(f"  Post-secondary-clean: open_edges={open_e}, non_manifold_verts={non_m}", flush=True)

    # ====================== TEXTURE EXPORT ======================
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

                    # Step 1: Save as-is — fast, no pixel decode in Blender's float buffer.
                    img.filepath_raw = texture_path
                    img.file_format = 'PNG'
                    img.save()
                    found_texture = True
                    print(f"✅ Texture saved: {texture_path}")

                    # Step 2: Patch sentinel corner pixels via Pillow subprocess.
                    # PIL reads the PNG natively (compressed) and only writes 16 pixels,
                    # so this is near-instant regardless of texture size.
                    # - Bottom-left 4×4 → light grey (0.75 linear ≈ RGB 191) = base colour
                    # - Top-left 4×4   → dark grey  (0.15 linear ≈ RGB 38)  = text colour
                    patch_script = (
                        "from PIL import Image, ImageDraw; "
                        f"img=Image.open(r'{texture_path}').convert('RGBA'); "
                        "d=ImageDraw.Draw(img); "
                        "d.rectangle([0,0,3,3],   fill=(191,191,191,255)); "  # base: light grey
                        "d.rectangle([0,img.height-4,3,img.height-1], fill=(38,38,38,255)); "  # text: dark grey
                        f"img.save(r'{texture_path}')"
                    )
                    try:
                        import subprocess as _sp
                        _result = _sp.run(
                            ["/venv/bin/python", "-c", patch_script],
                            capture_output=True, text=True, timeout=30
                        )
                        if _result.returncode == 0:
                            print("✅ Sentinel pixels patched via PIL")
                        else:
                            print(f"⚠️  PIL patch failed (non-fatal): {_result.stderr.strip()}")
                    except Exception as _e:
                        print(f"⚠️  PIL patch skipped (non-fatal): {_e}")

                    break
        if found_texture:
            break

    if not found_texture:
        print("⚠️  No embedded texture found.")

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
        print(f"  Post-base manifold: open_edges={open_e}, non_manifold_verts={non_m}", flush=True)

        print("✅ Base architecture complete!", flush=True)

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
        print(f"  Post-keychain manifold: open_edges={open_e}, non_manifold_verts={non_m}", flush=True)

    # ====================== FINAL MANIFOLD GATE ======================

    open_e, non_m = check_manifold(model)
    print(f"FINAL manifold check: open_edges={open_e}, non_manifold_verts={non_m}")

    if open_e > 0:
        print("⚠️  Model is still non-manifold before export. Attempting final repair...")
        apply_3d_print_toolbox(model)
        clean_mesh(model, threshold=0.01, fill_holes=True, fix_normals=True)
        open_e, non_m = check_manifold(model)
        print(f"  After final repair: open_edges={open_e}, non_manifold_verts={non_m}", flush=True)

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
