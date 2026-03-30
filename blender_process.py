import bpy
import sys
import math
import os
import traceback
from mathutils import Vector
import addon_utils

addon_utils.enable("object_print3d_utils")

print("=== BLENDER SCRIPT STARTED ===")
print(f"Python version: {sys.version}")
print(f"Blender version: {bpy.app.version_string}")
print(f"Arguments received: {sys.argv}")

def get_bounds(objs):
    bmin = Vector((float('inf'),)*3)
    bmax = Vector((-float('inf'),)*3)
    for obj in objs:
        for corner in obj.bound_box:
            v = obj.matrix_world @ Vector(corner)
            bmin = Vector(min(a, b) for a, b in zip(bmin, v))
            bmax = Vector(max(a, b) for a, b in zip(bmax, v))
    return bmin, bmax

def get_feet_bounds(obj, z_threshold_mm=5.0):
    mesh = obj.data
    verts = [obj.matrix_world @ v.co for v in mesh.vertices]
    if not verts: return None, None
    bmin_z = min(v.z for v in verts)
    feet = [v for v in verts if v.z <= bmin_z + z_threshold_mm]
    if not feet: return None, None
    return (Vector((min(v.x for v in feet), min(v.y for v in feet), bmin_z)), 
            Vector((max(v.x for v in feet), max(v.y for v in feet), bmin_z)))

def robust_boolean_union(target_obj, tool_obj, modifier_name="Union"):
    """
    Cascading Boolean fallback algorithm to guarantee geometry unification 
    for Marketiger/Magics compatibility.
    """
    bpy.ops.object.select_all(action='DESELECT')
    target_obj.select_set(True)
    bpy.context.view_layer.objects.active = target_obj
    
    vert_before = len(target_obj.data.vertices)
    
    # 1. Poging: EXACT solver
    bool_exact = target_obj.modifiers.new(name=f"{modifier_name}_EXACT", type='BOOLEAN')
    bool_exact.operation = 'UNION'
    bool_exact.object = tool_obj
    bool_exact.solver = 'EXACT'
    try: bool_exact.use_hole_tolerant = True
    except: pass
    
    bpy.ops.object.modifier_apply(modifier=bool_exact.name)
    
    if len(target_obj.data.vertices) > vert_before + 5:
        print(f"✅ {modifier_name} gelukt met EXACT solver!")
        bpy.data.objects.remove(tool_obj, do_unlink=True)
        return True

    print(f"⚠️ EXACT {modifier_name} gefaald op vuile mesh. Bezig met FLOAT solver...")
    
    # 2. Poging: FLOAT solver (Brute force intersection)
    bool_float = target_obj.modifiers.new(name=f"{modifier_name}_FLOAT", type='BOOLEAN')
    bool_float.operation = 'UNION'
    bool_float.object = tool_obj
    bool_float.solver = 'FLOAT'
    
    bpy.ops.object.modifier_apply(modifier=bool_float.name)
    
    if len(target_obj.data.vertices) > vert_before + 5:
        print(f"✅ {modifier_name} gelukt met FLOAT solver!")
        bpy.data.objects.remove(tool_obj, do_unlink=True)
        return True
        
    print(f"🚨 BEIDE BOOLEANS GEFAALD voor {modifier_name}! Fallback naar geometrische JOIN()...")
    # 3. Poging: JOIN (Overlap behouden in de hoop dat Magics/slicer het overleeft)
    bpy.ops.object.select_all(action='DESELECT')
    target_obj.select_set(True)
    tool_obj.select_set(True)
    bpy.context.view_layer.objects.active = target_obj
    bpy.ops.object.join()
    print(f"✅ {modifier_name} geforceerd via basis JOIN()")
    return False

try:
    # ====================== ARGUMENTEN ======================
    argv = sys.argv[sys.argv.index("--") + 1:]
    input_path = argv[0]
    output_path = argv[1]
    size_cm = float(argv[2])
    text_str = argv[3] if len(argv) > 3 else ""
    if text_str == "--NO-TEXT--": text_str = ""
    add_base = argv[4].lower() == 'true' if len(argv) > 4 else True
    add_keychain = argv[5].lower() == 'true' if len(argv) > 5 else False

    desired_height_mm = size_cm * 10
    base_thickness_mm = 2.5

    print("Arguments parsed successfully")

    bpy.ops.wm.read_factory_settings(use_empty=True)

    # ====================== IMPORT GLB ======================
    print("Importeer GLB...")
    bpy.ops.import_scene.gltf(filepath=input_path)

    mesh_objs = [o for o in bpy.data.objects if o.type == 'MESH']
    for obj in mesh_objs:
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.shade_smooth()

    if len(mesh_objs) > 1:
        bpy.ops.object.join()

    model = bpy.context.active_object
    print(f"Model geladen met {len(model.data.vertices)} vertices")

    # ====================== SCHALEN ======================
    bmin, bmax = get_bounds([model])
    current_height = bmax.z - bmin.z
    scale_factor = desired_height_mm / current_height
    model.scale *= scale_factor
    bpy.ops.object.transform_apply(scale=True)

    # ====================== TEXTURE UITPAKKEN ======================
    out_dir = os.path.dirname(output_path)
    texture_path = os.path.join(out_dir, "model.png")
    found_texture = False
    print("Zoeken naar embedded textures...")

    for mat in bpy.data.materials:
        if mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    img = node.image
                    print(f"Texture gevonden: {img.name} ({img.size[0]}x{img.size[1]})")
                    
                    # --- INJECT GREY PIXELS VOOR BASE (Light Grijs) en TEXT (Donker Grijs) ---
                    w, h = img.size
                    
                    # Bottom-Left hoek: Licht Grijs
                    for y in range(min(4, h)):
                        for x in range(min(4, w)):
                            idx = (y * w + x) * 4
                            if idx + 3 < len(img.pixels):
                                img.pixels[idx] = 0.75
                                img.pixels[idx+1] = 0.75
                                img.pixels[idx+2] = 0.75
                                img.pixels[idx+3] = 1.0
                                
                    # Top-Left hoek: Donker Grijs
                    for y in range(max(0, h-4), h):
                        for x in range(min(4, w)):
                            idx = (y * w + x) * 4
                            if idx + 3 < len(img.pixels):
                                img.pixels[idx] = 0.15
                                img.pixels[idx+1] = 0.15
                                img.pixels[idx+2] = 0.15
                                img.pixels[idx+3] = 1.0
                                
                    img.update()
                    
                    img.filepath_raw = texture_path
                    img.file_format = 'PNG'
                    img.save()
                    found_texture = True
                    print(f"✅ Texture opgeslagen als: {texture_path}")
                    break
            if found_texture:
                break

    if not found_texture:
        print("⚠️ Geen embedded texture gevonden.")

    # ====================== BASE + TEKST (1 Material Strategy) ======================
    bmin, bmax = get_bounds([model]) # De échte bmin is nu bekend dankzij artifact cleanup!
    fmin, fmax = get_feet_bounds(model)

    if fmin and fmax:
        center_x = (fmin.x + fmax.x) / 2
        center_y = (fmin.y + fmax.y) / 2
        radius = max(fmax.x - fmin.x, fmax.y - fmin.y) / 2 * 1.35
    else:
        center_x = (bmin.x + bmax.x) / 2
        center_y = (bmin.y + bmax.y) / 2
        radius = max(bmax.x - bmin.x, bmax.y - bmin.y) / 2 * 0.95

    if add_base:
        print("Base toevoegen via fall-back union pipeline...")
        
        adjusted_depth = base_thickness_mm + 0.5
        adj_z = bmin.z - adjusted_depth/2 + 0.5

        bpy.ops.mesh.primitive_cylinder_add(
            vertices=64, 
            radius=radius, 
            depth=adjusted_depth,
            location=(center_x, center_y, adj_z),
            calc_uvs=True
        )
        base = bpy.context.active_object

        if len(model.data.materials) > 0:
            base.data.materials.append(model.data.materials[0])
            if base.data.uv_layers.active and model.data.uv_layers.active:
                base.data.uv_layers.active.name = model.data.uv_layers.active.name
                for loop in base.data.loops:
                    base.data.uv_layers.active.data[loop.index].uv = (0.005, 0.005)

        # Tekst op de base
        if text_str.strip():
            text_loc = (center_x, center_y - radius*0.65, bmin.z + 0.4)
            bpy.ops.object.text_add(location=text_loc)
            txt = bpy.context.active_object
            txt.data.body = text_str.upper()[:40]
            txt.data.size = radius * 0.25
            txt.data.extrude = 0.5
            txt.data.align_x = 'CENTER'
            txt.data.align_y = 'CENTER'
            txt.rotation_euler = (0, 0, 0)
            bpy.context.view_layer.update()

            if txt.dimensions.x > radius * 1.4:
                txt.data.size *= (radius * 1.4 / txt.dimensions.x)

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

            # Eerst text union met base
            robust_boolean_union(base, txt_mesh, "Text_Union")

        # Dan base union met model
        robust_boolean_union(model, base, "Base_Union")
        
        # Cleanup naden
        bpy.context.view_layer.objects.active = model
        model.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=0.005)
        bpy.ops.object.mode_set(mode='OBJECT')
        
        print("✅ Base architecture deployed!")

    # ====================== KEYCHAIN ======================
    if add_keychain:
        print("Keychain toevoegen...")
        highest_v = None
        highest_v_idx = None
        max_z = -float('inf')
        mesh = model.data
        verts_world = [model.matrix_world @ v.co for v in mesh.vertices]
        center_x = (bmin.x + bmax.x) / 2
        center_y = (bmin.y + bmax.y) / 2

        for i, v in enumerate(verts_world):
            if math.hypot(v.x - center_x, v.y - center_y) < 15.0:
                if v.z > max_z:
                    max_z = v.z
                    highest_v = v
                    highest_v_idx = i

        if highest_v is None:
            keychain_z = bmax.z
            keychain_x = center_x
            keychain_y = center_y
        else:
            keychain_z = highest_v.z
            keychain_x = highest_v.x
            keychain_y = highest_v.y

        major_radius = 4.75
        minor_radius = 1.15
        sink_depth = 0.7
        found_uv = None

        if highest_v_idx is not None and model.data.uv_layers.active and len(model.data.materials) > 0:
            try:
                for loop in model.data.loops:
                    if loop.vertex_index == highest_v_idx:
                        found_uv = model.data.uv_layers.active.data[loop.index].uv
                        break
            except Exception: pass

        bpy.ops.mesh.primitive_torus_add(
            major_radius=major_radius,
            minor_radius=minor_radius,
            location=(keychain_x, keychain_y, keychain_z - sink_depth),
            rotation=(math.radians(90), 0, 0),
            generate_uvs=True
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
        
        # Cleanup naden keychain
        bpy.context.view_layer.objects.active = model
        model.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=0.005)
        bpy.ops.object.mode_set(mode='OBJECT')

    # ====================== EXPORT ======================
    bpy.ops.object.select_all(action='DESELECT')
    model.select_set(True)
    bpy.context.view_layer.objects.active = model
    
    # Triangulatie om Marketiger crash te voorkomen op Base caps
    tri_mod = model.modifiers.new(name="Triangulate", type='TRIANGULATE')
    bpy.ops.object.modifier_apply(modifier=tri_mod.name)

    print("Exporteren naar OBJ + MTL...")
    bpy.ops.wm.obj_export(
        filepath=output_path,
        export_selected_objects=True,
        export_materials=True,
        path_mode='COPY',
        export_uv=True
    )
    print(f"Export voltooid: {output_path}")

    print("=== Blender processing finished successfully ===")

except Exception as e:
    print(f"CRITICAL ERROR: {type(e).__name__}: {e}")
    traceback.print_exc()
    sys.exit(1)
