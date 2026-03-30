import bpy
import sys
import math
import os
from mathutils import Vector

def get_bounds(objs):
    bmin = Vector((float('inf'),) * 3)
    bmax = Vector((-float('inf'),) * 3)
    for obj in objs:
        for corner in obj.bound_box:
            v = obj.matrix_world @ Vector(corner)
            bmin = Vector(min(a, b) for a, b in zip(bmin, v))
            bmax = Vector(max(a, b) for a, b in zip(bmax, v))
    return bmin, bmax

def get_feet_bounds(obj, z_threshold_mm=6.0):
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
if current_height < 0.001:
    print("ERROR: Model height almost zero!")
    sys.exit(1)

scale_factor = desired_height_mm / current_height
model.scale *= scale_factor
bpy.ops.object.transform_apply(scale=True)
bpy.context.view_layer.update()
print(f"Model geschaald naar {desired_height_mm} mm hoogte")

# ====================== TEXTURE UITPAKKEN ======================
out_dir = os.path.dirname(output_path)
texture_path = os.path.join(out_dir, "model.png")
found_texture = False
print("Zoeken naar embedded textures...")
for mat in list(bpy.data.materials):
    if mat.use_nodes:
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                img = node.image
                print(f"Texture gevonden: {img.name} ({img.size[0]}x{img.size[1]})")
                try:
                    img.filepath_raw = texture_path
                    img.file_format = 'PNG'
                    img.save()
                    found_texture = True
                    print(f"✅ Texture opgeslagen als: {texture_path}")
                except Exception as e:
                    print(f"⚠️ Texture save mislukt: {e}")
                break
        if found_texture:
            break
if not found_texture:
    print("⚠️ Geen embedded texture gevonden.")

# ====================== BASE + TEKST ======================
bmin, bmax = get_bounds([model])  # opnieuw berekenen na scale
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
    print("Base toevoegen via Join + Voxel Remesh...")
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=64,
        radius=radius,
        depth=base_thickness_mm,
        location=(center_x, center_y, bmin.z - base_thickness_mm / 2 + 0.2)
    )
    base = bpy.context.active_object

    base_mat = bpy.data.materials.new("BaseMat")
    base_mat.use_nodes = True
    bsdf = base_mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs[0].default_value = (0.75, 0.75, 0.75, 1.0)
    base.data.materials.append(base_mat)

    # Join
    bpy.ops.object.select_all(action='DESELECT')
    model.select_set(True)
    base.select_set(True)
    bpy.context.view_layer.objects.active = model
    bpy.ops.object.join()
    bpy.context.view_layer.update()

    # Cleanup
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.remove_doubles(threshold=0.015)
    bpy.ops.object.mode_set(mode='OBJECT')

    # Voxel Remesh (stabieler voor Marketiger)
    remesh = model.modifiers.new(name="Remesh", type='VOXEL')
    remesh.voxel_size = 0.3
    bpy.ops.object.modifier_apply(modifier="Remesh")
    bpy.context.view_layer.update()

    # Base materiaal toewijzen
    bmin, bmax = get_bounds([model])  # opnieuw na remesh!
    mesh = model.data
    base_mat_index = model.data.materials.find("BaseMat")
    if base_mat_index == -1:
        model.data.materials.append(base_mat)
        base_mat_index = len(model.data.materials) - 1

    for face in mesh.polygons:
        face_z = sum((model.matrix_world @ mesh.vertices[i].co).z for i in face.vertices) / len(face.vertices)
        if face_z < bmin.z + 1.2:
            face.material_index = base_mat_index

    print("✅ Base succesvol gemerged")

    # Tekst (alleen als er tekst is)
    if text_str and text_str.strip():
        text_loc = (center_x, center_y - radius * 0.65, bmin.z)
        bpy.ops.object.text_add(location=text_loc)
        txt = bpy.context.active_object
        txt.data.body = text_str.upper()[:40]
        txt.data.size = radius * 0.25
        txt.data.extrude = 0.5
        txt.data.align_x = 'CENTER'
        txt.data.align_y = 'CENTER'
        bpy.context.view_layer.update()
        if txt.dimensions.x > radius * 1.4:
            txt.data.size *= (radius * 1.4 / txt.dimensions.x)
        bpy.ops.object.convert(target='MESH')
        txt_mesh = bpy.context.active_object

        tmat = bpy.data.materials.new("TextMat")
        tmat.use_nodes = True
        tmat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (0.05, 0.05, 0.05, 1.0)
        txt_mesh.data.materials.append(tmat)

        bpy.ops.object.select_all(action='DESELECT')
        model.select_set(True)
        txt_mesh.select_set(True)
        bpy.context.view_layer.objects.active = model
        bpy.ops.object.join()
        print("✅ Tekst toegevoegd")

# ====================== KEYCHAIN (alleen als nodig) ======================
if add_keychain:
    print("Keychain toevoegen... (wordt overgeslagen)")
    # je keychain code hier (niet gewijzigd, maar je kunt hem later toevoegen)

# ====================== FINAL EXPORT ======================
bpy.ops.object.select_all(action='DESELECT')
model.select_set(True)
bpy.context.view_layer.update()

print(f"Exporteren... Final vertices: {len(model.data.vertices)}")
try:
    bpy.ops.wm.obj_export(
        filepath=output_path,
        export_selected_objects=True,
        export_materials=True,
        path_mode='COPY',
        export_uv=True,
        export_normals=True
    )
    print(f"✅ Export succesvol: {output_path}")
except Exception as e:
    print(f"❌ Export error: {e}")
    raise

print(f"Texture aanwezig: {found_texture}")
