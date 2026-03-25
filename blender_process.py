import bpy
import sys
import math
import os
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

# ====================== BASE + TEKST ======================
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

# ====================== KEYCHAIN (aangepaste afmetingen) ======================
if add_keychain:
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

    # === AANGEPASTE RING WAARDEN ===
    major_radius = 4.75   # grotere opening
    minor_radius = 1.15   # iets slanker
    sink_depth = 0.7      # minder diep in het hoofd (was 1.0)

    torus_color = (0.5, 0.5, 0.5, 1.0)
    found_uv = None

    if highest_v_idx is not None and model.data.uv_layers.active and len(model.data.materials) > 0:
        try:
            for loop in model.data.loops:
                if loop.vertex_index == highest_v_idx:
                    uv = model.data.uv_layers.active.data[loop.index].uv
                    found_uv = uv
                    break
            if found_uv:
                mat = model.data.materials[0]
                if mat and mat.use_nodes:
                    for node in mat.node_tree.nodes:
                        if node.type == 'TEX_IMAGE' and node.image:
                            img = node.image
                            w, h = img.size
                            x = max(0, min(w-1, int((uv.x % 1.0) * w)))
                            y = max(0, min(h-1, int((uv.y % 1.0) * h)))
                            idx = (y * w + x) * 4
                            if idx + 3 < len(img.pixels):
                                torus_color = tuple(img.pixels[idx:idx+4])
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

    if found_uv is not None and len(model.data.materials) > 0:
        torus.data.materials.append(model.data.materials[0])
        if torus.data.uv_layers.active:
            for loop in torus.data.loops:
                torus.data.uv_layers.active.data[loop.index].uv = found_uv
    else:
        tmat = bpy.data.materials.new("RingMat")
        tmat.use_nodes = True
        tmat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = torus_color
        torus.data.materials.append(tmat)

    bpy.ops.object.select_all(action='DESELECT')
    model.select_set(True)
    torus.select_set(True)
    bpy.context.view_layer.objects.active = model
    bpy.ops.object.join()

# ====================== EXPORT OBJ + MTL ======================
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

print(f"Export voltooid: {output_path}")
print(f"Texture aanwezig: {texture_path}")
