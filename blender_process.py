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

# Maak base (berekend op basis van alleen de voeten!)
if fmin and fmax:
    center_x = (fmin.x + fmax.x) / 2
    center_y = (fmin.y + fmax.y) / 2
    # Hug the footprint perfectly with a 1.35x padding multiplier
    radius = max(fmax.x - fmin.x, fmax.y - fmin.y) / 2 * 1.35
else:
    center_x = (bmin.x + bmax.x) / 2
    center_y = (bmin.y + bmax.y) / 2
    radius = max(bmax.x - bmin.x, bmax.y - bmin.y) / 2 * 0.95

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
    text_loc = (center_x, center_y - radius*0.80, bmin.z)
    bpy.ops.object.text_add(location=text_loc)
    txt = bpy.context.active_object
    txt.data.body = text_str.upper()[:40]
    txt.data.size = radius * 0.35
    txt.data.extrude = 0.5 # Subtly embossed/embedded in the base
    txt.data.align_x = 'CENTER'
    txt.data.align_y = 'CENTER'
    # Text lies flat facing Z-up
    txt.rotation_euler = (0, 0, 0)

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

# Export gekleurd GLB (klaar voor print)
bpy.ops.object.select_all(action='DESELECT')
model.select_set(True)

bpy.ops.export_scene.gltf(
    filepath=output_path,
    export_format='GLB',
    export_materials='EXPORT',
    use_selection=True
)

print("SUCCESS: Exported", output_path)
