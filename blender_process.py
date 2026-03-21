import bpy
import sys
import math
from mathutils import Vector

def get_bounds(objs):
    bmin = Vector((float('inf'),)*3)
    bmax = Vector((-float('inf'),)*3)
    for obj in objs:
        for corner in obj.bound_box:
            v = obj.matrix_world @ Vector(corner)
            bmin = Vector(min(a,b) for a,b in zip(bmin,v))
            bmax = Vector(max(a,b) for a,b in zip(bmax,v))
    return bmin, bmax

def get_feet_bounds(obj, z_threshold_mm=5.0):
    mesh = obj.data
    verts = [obj.matrix_world @ v.co for v in mesh.vertices]
    if not verts: return None, None
    bmin_z = min(v.z for v in verts)
    feet = [v for v in verts if v.z <= bmin_z + z_threshold_mm]
    if not feet: return None, None
    min_x = min(v.x for v in feet)
    max_x = max(v.x for v in feet)
    min_y = min(v.y for v in feet)
    max_y = max(v.y for v in feet)
    return Vector((min_x, min_y, bmin_z)), Vector((max_x, max_y, bmin_z))

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
base_thickness_mm = 2.0

bpy.ops.wm.read_factory_settings(use_empty=True)

# Import Meshy GLB (behoudt kleuren + textures)
bpy.ops.import_scene.gltf(filepath=input_path)

mesh_objs = [o for o in bpy.data.objects if o.type == 'MESH']
for obj in mesh_objs:
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.shade_smooth()  # mooier resultaat van Meshy

bpy.ops.object.join()
model = bpy.context.active_object

# Scale naar exacte hoogte
bmin = Vector((float('inf'),)*3)
bmax = Vector((-float('inf'),)*3)
for corner in model.bound_box:
    v = model.matrix_world @ Vector(corner)
    bmin = Vector(min(a,b) for a,b in zip(bmin,v))
    bmax = Vector(max(a,b) for a,b in zip(bmax,v))

current_height = bmax.z - bmin.z
scale_factor = desired_height_mm / current_height
model.scale *= scale_factor
bpy.ops.object.transform_apply(scale=True)

# Herbereken bounds
bmin, bmax = get_bounds([model])

fmin, fmax = get_feet_bounds(model, z_threshold_mm=5.0)

# Calculate centers regardless, so keychain can use them
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

    # Base kleur (grijs)
    mat = bpy.data.materials.new("BaseMat")
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (0.3, 0.3, 0.3, 1.0)
    base.data.materials.append(mat)

    # Join base to model (prevents material bleeding on bad AI topology)
    bpy.ops.object.select_all(action='DESELECT')
    model.select_set(True)
    base.select_set(True)
    bpy.context.view_layer.objects.active = model
    bpy.ops.object.join()

    # Optionele tekst
    if text_str.strip():
        # Place text horizontally (flat) on top of the base
        text_loc = (center_x, center_y - radius*0.65, bmin.z)
        bpy.ops.object.text_add(location=text_loc)
        txt = bpy.context.active_object
        txt.data.body = text_str.upper()[:40]
        txt.data.size = radius * 0.25 # Lower default size
        txt.data.extrude = 0.5 # Subtly embossed/embedded in the base
        txt.data.align_x = 'CENTER'
        txt.data.align_y = 'CENTER'
        # Text lies flat facing Z-up
        txt.rotation_euler = (0, 0, 0)

        # Automatically shrink font size if text is wider than safe margins!
        bpy.context.view_layer.update()
        max_text_width = radius * 1.4
        if txt.dimensions.x > max_text_width:
            txt.data.size *= (max_text_width / txt.dimensions.x)

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
    highest_v = None
    max_z = -float('inf')
    mesh = model.data
    verts_world = [model.matrix_world @ v.co for v in mesh.vertices]
    for v in verts_world:
        if math.hypot(v.x - center_x, v.y - center_y) < 15.0:
            if v.z > max_z:
                max_z = v.z
                highest_v = v
                
    if highest_v is None:
        keychain_z = bmax.z
        keychain_x = center_x
        keychain_y = center_y
    else:
        keychain_z = highest_v.z
        keychain_x = highest_v.x
        keychain_y = highest_v.y

    # Vergroot de torus zodat de binnendiameter ruim groot genoeg is voor een standaard sleutelhanger
    bpy.ops.mesh.primitive_torus_add(
        major_radius=4.0,   # Grotere ring, diameter is nu een stuk groter
        minor_radius=1.2,   # Stevige dikte voor robuustheid (binnenradius = 2.8mm, dus 5.6mm diameter gat)
        location=(keychain_x, keychain_y, keychain_z - 1.0), # Laat iets verder de head in zakken (1.0mm)
        rotation=(math.radians(90), 0, 0)
    )
    torus = bpy.context.active_object
    
    tmat = bpy.data.materials.new("RingMat")
    tmat.use_nodes = True
    tmat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (0.5, 0.5, 0.5, 1.0)
    torus.data.materials.append(tmat)

    bpy.ops.object.select_all(action='DESELECT')
    model.select_set(True)
    torus.select_set(True)
    bpy.context.view_layer.objects.active = model
    bpy.ops.object.join()

# Extract extremely robustly by saving temporary blend file and unpacking
import os
out_dir = os.path.dirname(output_path)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "temp.blend"))
bpy.ops.file.unpack_all(method='USE_LOCAL')

# Export gekleurd OBJ archief (klaar voor print via Shapeways)
bpy.ops.object.select_all(action='DESELECT')
model.select_set(True)

# using path_mode COPY takes the unpacked textures and perfectly flattens them next to the OBJ
bpy.ops.wm.obj_export(
    filepath=output_path,
    export_selected_objects=True,
    export_materials=True,
    path_mode='COPY'
)

print("SUCCESS: Exported", output_path)
