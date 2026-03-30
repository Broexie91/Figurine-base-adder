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
                    
                    # Bottom-Left hoek (4x4 pixels): Licht Grijs
                    for y in range(min(4, h)):
                        for x in range(min(4, w)):
                            idx = (y * w + x) * 4
                            if idx + 3 < len(img.pixels):
                                img.pixels[idx] = 0.75
                                img.pixels[idx+1] = 0.75
                                img.pixels[idx+2] = 0.75
                                img.pixels[idx+3] = 1.0
                                
                    # Top-Left hoek (4x4 pixels): Donker Grijs
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
    bmin, bmax = get_bounds([model])
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
        print("Base toevoegen via overlapping JOIN (no-boolean)...")
        
        # Duw de cylinder +0.5 mm in de voeten van het model (overlap voor slice-verbinding)
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

        # Koppel EXACT hetzelfde materiaal en UV coordinaat (licht grijs dot op 0.005, 0.005)
        if len(model.data.materials) > 0:
            base.data.materials.append(model.data.materials[0])
            if base.data.uv_layers.active:
                for loop in base.data.loops:
                    base.data.uv_layers.active.data[loop.index].uv = (0.005, 0.005)

        # Tekst op de base (optioneel)
        if text_str.strip():
            text_loc = (center_x, center_y - radius*0.65, bmin.z + 0.2)
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

            # Tekst ook hetzelfde materiaal, maar dan naar de donker grijze dot gewijzen (0.005, 0.995)
            if len(model.data.materials) > 0:
                txt_mesh.data.materials.append(model.data.materials[0])
                if txt_mesh.data.uv_layers.active:
                    for loop in txt_mesh.data.loops:
                        txt_mesh.data.uv_layers.active.data[loop.index].uv = (0.005, 0.995)

            # Voeg Tekst eerst bij Base
            bool_mod_txt = base.modifiers.new(name="Text_Union", type='BOOLEAN')
            bool_mod_txt.operation = 'UNION'
            bool_mod_txt.object = txt_mesh
            bpy.ops.object.modifier_apply(modifier=bool_mod_txt.name)
            bpy.data.objects.remove(txt_mesh, do_unlink=True)

        # Voeg Base bij het hoofdmodel met behulp van BOOLEAN UNION (belangrijk voor Marketiger shell fusion)
        bool_mod = model.modifiers.new(name="Base_Union", type='BOOLEAN')
        bool_mod.operation = 'UNION'
        bool_mod.object = base
        bpy.ops.object.modifier_apply(modifier=bool_mod.name)
        bpy.data.objects.remove(base, do_unlink=True)
        
        print("✅ Base geometry verenigd via BOOLEAN UNION, 1-Texture constraint enforced")

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
            except Exception:
                pass

        bpy.ops.mesh.primitive_torus_add(
            major_radius=major_radius,
            minor_radius=minor_radius,
            location=(keychain_x, keychain_y, keychain_z - sink_depth),
            rotation=(math.radians(90), 0, 0),
            generate_uvs=True
        )
        torus = bpy.context.active_object

        # Fix voor Keychain: Altijd hetzelfde materiaal forceren.
        # Fallback naar dark grijs pixel (0.005, 0.995) als UV niet geresolved is.
        if len(model.data.materials) > 0:
            torus.data.materials.append(model.data.materials[0])
            if torus.data.uv_layers.active:
                fallback_uv = found_uv if found_uv is not None else (0.005, 0.995)
                for loop in torus.data.loops:
                    torus.data.uv_layers.active.data[loop.index].uv = fallback_uv

        bool_mod_key = model.modifiers.new(name="Key_Union", type='BOOLEAN')
        bool_mod_key.operation = 'UNION'
        bool_mod_key.object = torus
        bpy.ops.object.modifier_apply(modifier=bool_mod_key.name)
        bpy.data.objects.remove(torus, do_unlink=True)

    # ====================== EXPORT ======================
    bpy.ops.object.select_all(action='DESELECT')
    model.select_set(True)

    print("Exporteren naar OBJ + MTL...")
    bpy.ops.wm.obj_export(
        filepath=output_path,
        export_selected_objects=True,
        export_materials=True,
        path_mode='COPY',
        export_uv=True,
        export_triangulated=True
    )
    print(f"Export voltooid: {output_path}")
    if found_texture:
        print(f"Texture aanwezig: {texture_path}")

    print("=== Blender processing finished successfully ===")

except Exception as e:
    print(f"CRITICAL ERROR: {type(e).__name__}: {e}")
    traceback.print_exc()
    sys.exit(1)
