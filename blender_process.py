import bpy
import sys
import math
import os
from mathutils import Vector

def get_bounds(obj):
    bmin = Vector((float('inf'),) * 3)
    bmax = Vector((-float('inf'),) * 3)
    for corner in obj.bound_box:
        v = obj.matrix_world @ Vector(corner)
        bmin = Vector(min(a, b) for a, b in zip(bmin, v))
        bmax = Vector(max(a, b) for a, b in zip(bmax, v))
    return bmin, bmax

def get_feet_bounds(obj, z_threshold_mm=8.0):
    mesh = obj.data
    verts = [obj.matrix_world @ v.co for v in mesh.vertices]
    if not verts: return None, None
    bmin_z = min(v.z for v in verts)
    feet = [v for v in verts if v.z <= bmin_z + z_threshold_mm]
    if not feet: return None, None
    return Vector((min(v.x for v in feet), min(v.y for v in feet), bmin_z)), \
           Vector((max(v.x for v in feet), max(v.y for v in feet), bmin_z))

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

bpy.ops.wm.read_factory_settings(use_empty=True)
print("=== Blender processing started ===")

# ====================== IMPORT ======================
print("Import GLB...")
bpy.ops.import_scene.gltf(filepath=input_path)

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

# Cleanup na import
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.remove_doubles(threshold=0.02)
bpy.ops.object.mode_set(mode='OBJECT')
print("Doubles verwijderd na import")

# ====================== TEXTURE ======================
out_dir = os.path.dirname(output_path)
texture_path = os.path.join(out_dir, "model.png")
found_texture = False
for mat in bpy.data.materials:
    if mat.use_nodes:
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                try:
                    img = node.image
                    img.filepath_raw = texture_path
                    img.file_format = 'PNG'
                    img.save()
                    found_texture = True
                    print(f"✅ Texture opgeslagen: {texture_path}")
                except Exception as e:
                    print(f"Texture warning: {e}")
                break
        if found_texture: break

# ====================== BASE ======================
if add_base:
    print("Base toevoegen...")
    bmin, bmax = get_bounds(model)
    fmin, fmax = get_feet_bounds(model)

    if fmin and fmax:
        center_x = (fmin.x + fmax.x) / 2
        center_y = (fmin.y + fmax.y) / 2
        radius = max(fmax.x - fmin.x, fmax.y - fmin.y) / 2 * 1.4
    else:
        center_x = (bmin.x + bmax.x) / 2
        center_y = (bmin.y + bmax.y) / 2
        radius = max(bmax.x - bmin.x, bmax.y - bmin.y) / 2 * 1.0

    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=radius, depth=base_thickness_mm,
                                        location=(center_x, center_y, bmin.z - base_thickness_mm/2 + 0.3))
    base = bpy.context.active_object

    base_mat = bpy.data.materials.new("BaseMat")
    base_mat.use_nodes = True
    base_mat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (0.75, 0.75, 0.75, 1.0)
    base.data.materials.append(base_mat)

    # Veilige join
    bpy.ops.object.select_all(action='DESELECT')
    model.select_set(True)
    base.select_set(True)
    bpy.context.view_layer.objects.active = model
    with bpy.context.temp_override(active_object=model, selected_objects=[model, base]):
        bpy.ops.object.join()
    print("Base gejoind")

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.remove_doubles(threshold=0.02)
    bpy.ops.object.mode_set(mode='OBJECT')

# ====================== KEYCHAIN (terug!) ======================
if add_keychain:
    print("Keychain toevoegen...")
    bmin, bmax = get_bounds(model)  # update bounds
    highest_v = None
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

    keychain_z = highest_v.z if highest_v else bmax.z
    keychain_x = highest_v.x if highest_v else center_x
    keychain_y = highest_v.y if highest_v else center_y

    major_radius = 4.75
    minor_radius = 1.15
    sink_depth = 0.7

    bpy.ops.mesh.primitive_torus_add(
        major_radius=major_radius,
        minor_radius=minor_radius,
        location=(keychain_x, keychain_y, keychain_z - sink_depth),
        rotation=(math.radians(90), 0, 0),
        generate_uvs=True
    )
    torus = bpy.context.active_object

    # Simpele grijze ring als fallback
    tmat = bpy.data.materials.new("RingMat")
    tmat.use_nodes = True
    tmat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (0.5, 0.5, 0.5, 1.0)
    torus.data.materials.append(tmat)

    # Veilige join
    bpy.ops.object.select_all(action='DESELECT')
    model.select_set(True)
    torus.select_set(True)
    bpy.context.view_layer.objects.active = model
    with bpy.context.temp_override(active_object=model, selected_objects=[model, torus]):
        bpy.ops.object.join()
    print("Keychain gejoind")

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.remove_doubles(threshold=0.02)
    bpy.ops.object.mode_set(mode='OBJECT')

# ====================== EXPORT ======================
bpy.ops.object.select_all(action='DESELECT')
model.select_set(True)
bpy.context.view_layer.objects.active = model

print(f"Exporteren — vertices: {len(model.data.vertices)}")

try:
    bpy.ops.wm.obj_export(
        filepath=output_path,
        export_selected_objects=True,
        export_materials=True,
        path_mode='COPY',
        export_uv=True,
        export_normals=True
    )
    print("✅ Export succesvol")
except Exception as e:
    print(f"❌ Export error: {e}")
    raise

print("Proces klaar")
