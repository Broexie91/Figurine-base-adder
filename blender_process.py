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
    if not verts:
        return None, None
    bmin_z = min(v.z for v in verts)
    feet = [v for v in verts if v.z <= bmin_z + z_threshold_mm]
    if not feet:
        return None, None
    return Vector((min(v.x for v in feet), min(v.y for v in feet), bmin_z)), \
           Vector((max(v.x for v in feet), max(v.y for v in feet), bmin_z))

# ====================== ARGUMENTEN ======================
argv = sys.argv[sys.argv.index("--") + 1:]
input_path = argv[0]
output_path = argv[1]
size_cm = float(argv[2])
text_str = argv[3] if len(argv) > 3 else ""
if text_str == "--NO-TEXT--":
    text_str = ""
add_base = argv[4].lower() == 'true' if len(argv) > 4 else True
add_keychain = argv[5].lower() == 'true' if len(argv) > 5 else False

desired_height_mm = size_cm * 10
base_thickness_mm = 2.5

bpy.ops.wm.read_factory_settings(use_empty=True)

print("=== Blender processing started ===")

# ====================== IMPORT ======================
print("Importeer GLB...")
bpy.ops.import_scene.gltf(filepath=input_path)

objs = [o for o in bpy.data.objects if o.type == 'MESH']
for o in objs:
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.shade_smooth()

if len(objs) > 1:
    bpy.context.view_layer.objects.active = objs[0]
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
                    print(f"Texture save warning: {e}")
                break
        if found_texture:
            break

# ====================== BASE TOEVOEGEN (veilige methode) ======================
if add_base:
    print("Base toevoegen (veilige join + merge)...")
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

    # Cylinder maken met lichte overlap
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=64,
        radius=radius,
        depth=base_thickness_mm,
        location=(center_x, center_y, bmin.z - base_thickness_mm / 2 + 0.3)
    )
    base = bpy.context.active_object

    # Materiaal base
    base_mat = bpy.data.materials.new(name="BaseMat")
    base_mat.use_nodes = True
    base_mat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (0.75, 0.75, 0.75, 1.0)
    base.data.materials.append(base_mat)

    # Join (met context override om crashes te voorkomen)
    bpy.ops.object.select_all(action='DESELECT')
    model.select_set(True)
    base.select_set(True)
    bpy.context.view_layer.objects.active = model

    with bpy.context.temp_override(active_object=model, selected_objects=[model, base]):
        bpy.ops.object.join()

    print("Objects gejoind")

    # Dubbele vertices verwijderen
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.remove_doubles(threshold=0.02)
    bpy.ops.object.mode_set(mode='OBJECT')

    # Simpele Remesh (groter voxel_size om crash te voorkomen)
    remesh = model.modifiers.new(name="Remesh", type='VOXEL')
    remesh.voxel_size = 0.4          # Groter = veiliger voor kleine modellen
    bpy.ops.object.modifier_apply(modifier="Remesh")

    # Base kleur toewijzen aan onderste faces
    bmin, bmax = get_bounds(model)   # opnieuw na remesh
    mesh = model.data
    base_mat_index = model.data.materials.find("BaseMat")
    if base_mat_index == -1:
        model.data.materials.append(base_mat)
        base_mat_index = len(model.data.materials) - 1

    for face in mesh.polygons:
        face_z = sum((model.matrix_world @ mesh.vertices[i].co).z for i in face.vertices) / len(face.vertices)
        if face_z < bmin.z + 1.5:
            face.material_index = base_mat_index

    print("✅ Base succesvol toegevoegd")

# ====================== EXPORT ======================
bpy.ops.object.select_all(action='DESELECT')
model.select_set(True)
bpy.context.view_layer.objects.active = model

print(f"Exporteren naar {output_path} — vertices: {len(model.data.vertices)}")

try:
    bpy.ops.wm.obj_export(
        filepath=output_path,
        export_selected_objects=True,
        export_materials=True,
        path_mode='COPY',
        export_uv=True,
        export_normals=True
    )
    print("✅ Export succesvol voltooid")
except Exception as e:
    print(f"❌ Export error: {type(e).__name__}: {e}")
    raise

print(f"Proces klaar — texture: {'ja' if found_texture else 'nee'}")
