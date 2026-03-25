import bpy
import sys
import math
import os
import zipfile
from mathutils import Vector
import addon_utils

addon_utils.enable("object_print3d_utils")

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
base_thickness_mm = 2.0

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

# ====================== TEXTURE UITPAKKEN (voor nieuwe Tripo GLB's) ======================
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
                # Sla op als model.png
                img.filepath_raw = texture_path
                img.file_format = 'PNG'
                img.save()
                found_texture = True
                print(f"✅ Texture opgeslagen als: {texture_path}")
                break
        if found_texture:
            break

if not found_texture:
    print("⚠️ Geen embedded texture gevonden in het materiaal.")

# ====================== BASE + TEKST + KEYCHAIN ======================
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
    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=radius, depth=base_thickness_mm,
                                        location=(center_x, center_y, bmin.z - base_thickness_mm/2))
    base = bpy.context.active_object
    mat = bpy.data.materials.new("BaseMat")
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (0.3, 0.3, 0.3, 1.0)
    base.data.materials.append(mat)

    bpy.ops.object.select_all(action='DESELECT')
    model.select_set(True)
    base.select_set(True)
    bpy.context.view_layer.objects.active = model
    bpy.ops.object.join()

    if text_str.strip():
        text_loc = (center_x, center_y - radius*0.65, bmin.z)
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
        tmat = bpy.data.materials.new("TextMat")
        tmat.use_nodes = True
        tmat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (0.05, 0.05, 0.05, 1.0)
        txt_mesh.data.materials.append(tmat)
        bpy.ops.object.select_all(action='DESELECT')
        model.select_set(True)
        txt_mesh.select_set(True)
        bpy.context.view_layer.objects.active = model
        bpy.ops.object.join()

if add_keychain:
    # (je keychain code hier - laat staan zoals hij was)
    pass   # vervang door je volledige keychain blok als je hem wilt

# ====================== EXPORT + ZIP ======================
base_name = os.path.splitext(os.path.basename(output_path))[0]

bpy.ops.object.select_all(action='DESELECT')
model.select_set(True)

print("Exporteren naar OBJ + MTL...")
bpy.ops.wm.obj_export(
    filepath=output_path,
    export_selected_objects=True,
    export_materials=True,
    path_mode='COPY',
    export_uv=True
)

zip_path = os.path.join(out_dir, f"{base_name}.zip")
with zipfile.ZipFile(zip_path, 'w') as z:
    if os.path.exists(output_path):
        z.write(output_path, f"{base_name}.obj")
    mtl_path = output_path.replace('.obj', '.mtl')
    if os.path.exists(mtl_path):
        z.write(mtl_path, f"{base_name}.mtl")
    if os.path.exists(texture_path):
        z.write(texture_path, f"{base_name}.png")
        print(f"✅ PNG toegevoegd aan ZIP: {base_name}.png")
    else:
        print("⚠️ Geen model.png gevonden!")

print(f"SUCCESS: ZIP aangemaakt → {zip_path}")
