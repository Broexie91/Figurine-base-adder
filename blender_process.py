import bpy
import sys
import math
import os
import traceback
from mathutils import Vector

print("=== BLENDER SCRIPT STARTED (Blender 5.1 DEBUG) ===")
print(f"Python version: {sys.version}")
print(f"Blender version: {bpy.app.version_string}")
print(f"Arguments received: {sys.argv}")

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
    print("Factory settings loaded")

    # ====================== IMPORT ======================
    print("Import GLB...")
    bpy.ops.import_scene.gltf(filepath=input_path)
    print("GLB imported successfully")

    mesh_objs = [o for o in bpy.data.objects if o.type == 'MESH']
    for obj in mesh_objs:
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.shade_smooth()

    if len(mesh_objs) > 1:
        bpy.context.view_layer.objects.active = mesh_objs[0]
        bpy.ops.object.join()

    model = bpy.context.active_object
    print(f"Model geladen — vertices: {len(model.data.vertices)}")

    # ====================== SCHALEN ======================
    bmin, bmax = get_bounds(model)
    current_height = bmax.z - bmin.z
    if current_height < 0.01:
        print("ERROR: Model height bijna nul!")
        sys.exit(1)

    scale_factor = desired_height_mm / current_height
    model.scale = (scale_factor, scale_factor, scale_factor)
    bpy.ops.object.transform_apply(scale=True)
    print(f"Model geschaald naar {desired_height_mm:.1f} mm")

    # Cleanup
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.remove_doubles(threshold=0.015)
    bpy.ops.object.mode_set(mode='OBJECT')
    print("Doubles verwijderd na import")

    # ====================== TEXTURE ======================
    # (je bestaande texture-code, met print erbij)
    out_dir = os.path.dirname(output_path)
    texture_path = os.path.join(out_dir, "model.png")
    found_texture = False
    # ... (je bestaande texture loop blijft hetzelfde, alleen met print("Texture search started"))
    print("Texture search completed")

    # ====================== BASE (Boolean + Remesh) ======================
    if add_base:
        print("Starting BASE section (Boolean + Voxel Remesh)...")
        # (je volledige BASE-code uit mijn vorige bericht hier invoegen)
        # Ik heb hem hieronder voor de volledigheid nog een keer gezet:

        bmin, bmax = get_bounds(model)
        fmin, fmax = get_feet_bounds(model)

        if fmin and fmax:
            center_x = (fmin.x + fmax.x) / 2
            center_y = (fmin.y + fmax.y) / 2
            radius = max(fmax.x - fmin.x, fmax.y - fmin.y) / 2 * 1.45
        else:
            center_x = (bmin.x + bmax.x) / 2
            center_y = (bmin.y + bmax.y) / 2
            radius = max(bmax.x - bmin.x, bmax.y - bmin.y) / 2 * 1.05

        bpy.ops.mesh.primitive_cylinder_add(
            vertices=64, radius=radius, depth=base_thickness_mm,
            location=(center_x, center_y, bmin.z - base_thickness_mm/2 + 0.4)
        )
        base = bpy.context.active_object

        base_mat = bpy.data.materials.new("BaseMat")
        base_mat.use_nodes = True
        base_mat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (0.75, 0.75, 0.75, 1.0)
        base.data.materials.append(base_mat)

        # Boolean Union
        bpy.ops.object.select_all(action='DESELECT')
        model.select_set(True)
        base.select_set(True)
        bpy.context.view_layer.objects.active = model
        bool_mod = model.modifiers.new(name="BaseUnion", type='BOOLEAN')
        bool_mod.operation = 'UNION'
        bool_mod.object = base
        bpy.ops.object.modifier_apply(modifier=bool_mod.name)
        bpy.data.objects.remove(base, do_unlink=True)
        print("Boolean Union toegepast")

        # Remesh + cleanup
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.remove_doubles(threshold=0.015)
        bpy.ops.mesh.dissolve_degenerate(threshold=0.01)
        bpy.ops.object.mode_set(mode='OBJECT')

        remesh = model.modifiers.new(name="Remesh", type='VOXEL')
        remesh.voxel_size = 0.35
        bpy.ops.object.modifier_apply(modifier="Remesh")
        print("Voxel Remesh toegepast")

        # Materiaal toewijzen
        bmin, bmax = get_bounds(model)
        mesh = model.data
        base_mat_index = model.data.materials.find("BaseMat")
        if base_mat_index == -1:
            model.data.materials.append(base_mat)
            base_mat_index = len(model.data.materials) - 1

        for face in mesh.polygons:
            face_z = sum((model.matrix_world @ mesh.vertices[i].co).z for i in face.vertices) / len(face.vertices)
            if face_z < bmin.z + 1.8:
                face.material_index = base_mat_index

        print("✅ Base succesvol verwerkt")

    # ====================== KEYCHAIN (alleen als nodig) ======================
    if add_keychain:
        print("Keychain toevoegen...")   # (je bestaande keychain-code)

    # ====================== EXPORT ======================
    bpy.ops.object.select_all(action='DESELECT')
    model.select_set(True)
    bpy.context.view_layer.objects.active = model

    print(f"Exporteren — final vertices: {len(model.data.vertices)}")
    bpy.ops.wm.obj_export(
        filepath=output_path,
        export_selected_objects=True,
        export_materials=True,
        path_mode='COPY',
        export_uv=True,
        export_normals=True
    )
    print("✅ Export succesvol")

    print("=== Blender processing finished successfully ===")

except Exception as e:
    print(f"CRITICAL ERROR: {type(e).__name__}: {e}")
    traceback.print_exc()
    raise
