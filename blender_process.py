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
    if not verts:
        return None, None
    bmin_z = min(v.z for v in verts)
    feet = [v for v in verts if v.z <= bmin_z + z_threshold_mm]
    if not feet:
        return None, None
    min_x = min(v.x for v in feet)
    max_x = max(v.x for v in feet)
    min_y = min(v.y for v in feet)
    max_y = max(v.y for v in feet)
    return Vector((min_x, min_y, bmin_z)), Vector((max_x, max_y, bmin_z))

# ====================== ARGUMENTEN ======================
argv = sys.argv[sys.argv.index("--") + 1:]
input_path = argv[0]
output_path = argv[1]                    # bijv. /app/output/model.obj
size_cm = float(argv[2])
text_str = argv[3] if len(argv) > 3 else ""
if text_str == "--NO-TEXT--":
    text_str = ""
add_base = argv[4].lower() == 'true' if len(argv) > 4 else True
add_keychain = argv[5].lower() == 'true' if len(argv) > 5 else False

desired_height_mm = size_cm * 10
base_thickness_mm = 2.0

# ====================== SCENE OPSCHONEN ======================
bpy.ops.wm.read_factory_settings(use_empty=True)

# ====================== IMPORT GLB ======================
bpy.ops.import_scene.gltf(filepath=input_path)

mesh_objs = [o for o in bpy.data.objects if o.type == 'MESH']
for obj in mesh_objs:
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.shade_smooth()

bpy.ops.object.join()
model = bpy.context.active_object

# ====================== SCHALEN ======================
bmin, bmax = get_bounds([model])
current_height = bmax.z - bmin.z
scale_factor = desired_height_mm / current_height
model.scale *= scale_factor
bpy.ops.object.transform_apply(scale=True)

# ====================== TRIPO VERTEX COLOR DETECTIE ======================
mesh = model.data
is_tripo_voxel = False
vc_name = ""

if hasattr(mesh, 'color_attributes') and len(mesh.color_attributes) > 0:
    mesh.color_attributes.active_color_index = 0
    vc_name = mesh.color_attributes[0].name
    is_tripo_voxel = True
elif hasattr(mesh, 'vertex_colors') and len(mesh.vertex_colors) > 0:
    mesh.vertex_colors.active_index = 0
    vc_name = mesh.vertex_colors[0].name
    is_tripo_voxel = True

print(f"Tripo vertex color model gedetecteerd: {is_tripo_voxel} (attribute: {vc_name})")

# ====================== BAKING VERTEX COLORS (alleen bij Tripo) ======================
if is_tripo_voxel:
    print("Baking Tripo vertex colors naar 4096x4096 texture...")

    # UV unwrap
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode='OBJECT')

    # Bake material setup
    bake_mat = bpy.data.materials.new(name="Bake_Tripo")
    bake_mat.use_nodes = True
    nodes = bake_mat.node_tree.nodes
    links = bake_mat.node_tree.links
    for n in nodes:
        nodes.remove(n)

    attr = nodes.new('ShaderNodeAttribute')
    emit = nodes.new('ShaderNodeEmission')
    tex_node = nodes.new('ShaderNodeTexImage')
    output = nodes.new('ShaderNodeOutputMaterial')

    attr.attribute_name = vc_name
    links.new(attr.outputs["Color"], emit.inputs["Color"])
    links.new(emit.outputs["Emission"], output.inputs["Surface"])

    # Hoge resolutie texture
    img = bpy.data.images.new("BakedTripo", width=4096, height=4096, alpha=False)
    img.colorspace_settings.name = 'sRGB'
    tex_node.image = img
    nodes.active = tex_node

    model.data.materials.clear()
    model.data.materials.append(bake_mat)

    # Bake settings
    bpy.context.scene.render.engine = 'CYCLES'
    bpy.context.scene.cycles.samples = 1
    bpy.context.scene.render.bake.use_clear = True
    bpy.context.scene.render.bake.margin = 32

    bpy.ops.object.bake(type='EMIT', pass_filter={'COLOR'})

    # Final material met gebakken texture
    final_mat = bpy.data.materials.new(name="Final_Tripo")
    final_mat.use_nodes = True
    fnodes = final_mat.node_tree.nodes
    flinks = final_mat.node_tree.links
    for n in fnodes:
        fnodes.remove(n)

    ftex = fnodes.new('ShaderNodeTexImage')
    fbsdf = fnodes.new('ShaderNodeBsdfPrincipled')
    fout = fnodes.new('ShaderNodeOutputMaterial')

    ftex.image = img
    flinks.new(ftex.outputs["Color"], fbsdf.inputs["Base Color"])
    flinks.new(fbsdf.outputs["BSDF"], fout.inputs["Surface"])

    model.data.materials.clear()
    model.data.materials.append(final_mat)

    # Texture opslaan als model.png
    out_dir = os.path.dirname(output_path)
    texture_path = os.path.join(out_dir, "model.png")
    img.filepath_raw = texture_path
    img.file_format = 'PNG'
    img.save()
    print(f"Texture succesvol gebakken en opgeslagen: {texture_path}")

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
        text_loc = (center_x, center_y - radius * 0.65, bmin.z)
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

# ====================== KEYCHAIN ======================
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
                            x = max(0, min(w - 1, int((uv.x % 1.0) * w)))
                            y = max(0, min(h - 1, int((uv.y % 1.0) * h)))
                            idx = (y * w + x) * 4
                            if idx + 3 < len(img.pixels):
                                torus_color = tuple(img.pixels[idx:idx + 4])
                            break
        except Exception:
            pass

    bpy.ops.mesh.primitive_torus_add(
        major_radius=4.0,
        minor_radius=1.2,
        location=(keychain_x, keychain_y, keychain_z - 1.0),
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

# ====================== EXPORT + ZIP ======================
out_dir = os.path.dirname(output_path)
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

# ZIP maken met nette namen
zip_path = os.path.join(out_dir, f"{base_name}.zip")

with zipfile.ZipFile(zip_path, 'w') as z:
    # OBJ
    if os.path.exists(output_path):
        z.write(output_path, f"{base_name}.obj")
    # MTL
    mtl_path = output_path.replace('.obj', '.mtl')
    if os.path.exists(mtl_path):
        z.write(mtl_path, f"{base_name}.mtl")
    # PNG
    texture_path = os.path.join(out_dir, "model.png")
    if os.path.exists(texture_path):
        z.write(texture_path, f"{base_name}.png")
        print(f"Texture toegevoegd aan ZIP: {base_name}.png")
    else:
        print("WAARSCHUWING: model.png niet gevonden in output map!")

print(f"SUCCESS: ZIP aangemaakt → {zip_path}")
print(f"Inhoud: {base_name}.obj + {base_name}.mtl + {base_name}.png")
