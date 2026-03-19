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
bmin, bmax = get_bounds([model])  # helper functie onderaan

# Maak base
center_x = (bmin.x + bmax.x) / 2
center_y = (bmin.y + bmax.y) / 2
radius = max(bmax.x - bmin.x, bmax.y - bmin.y) / 2 * 1.15

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
    text_loc = (center_x, center_y - radius*0.85, bmin.z + 1.5)
    bpy.ops.object.text_add(location=text_loc)
    txt = bpy.context.active_object
    txt.data.body = text_str.upper()[:40]
    txt.data.size = radius * 0.25
    txt.data.extrude = 2.0
    txt.data.align_x = 'CENTER'
    txt.rotation_euler = (math.radians(90), 0, math.radians(180))

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
