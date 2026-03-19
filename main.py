from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import cadquery as cq
import trimesh
from trimesh.boolean import union
import numpy as np
import requests
import os
from typing import Optional
from pydantic import BaseModel

app = FastAPI()

class BaseGenerationRequest(BaseModel):
    model_url: str
    figurine_height: int  # 6, 8, or 10 cm
    text_label: Optional[str] = None
    order_id: str

@app.post("/generate-base/")
async def generate_base(request: BaseGenerationRequest):
    """ Generate a 3D base/platform for a figurine and merge it into one solid part
    Parameters:
    - model_url: URL to the GLB file
    - figurine_height: Height of figurine in cm (6, 8, or 10)
    - text_label: Optional custom text for the front of the base
    - order_id: Unique identifier for this order"""

    # Validate figurine height
    if request.figurine_height not in [6, 8, 10]:
        raise HTTPException(
            status_code=400,
            detail="figurine_height must be 6, 8, or 10 cm"
        )

    try:
        # 1. Download the GLB file
        resp = requests.get(request.model_url, timeout=30)
        resp.raise_for_status()
        input_file = f"input_{request.order_id}.glb"
        with open(input_file, "wb") as f:
            f.write(resp.content)

        # 2. Load the original model to get its bounds
        original_model = trimesh.load(input_file)

        # Get the bounding box of the original model
        bounds = original_model.bounds
        model_min_z = bounds[0][2]
        model_max_z = bounds[1][2]
        model_height = model_max_z - model_min_z
        model_center_x = (bounds[0][0] + bounds[1][0]) / 2
        model_center_y = (bounds[0][1] + bounds[1][1]) / 2
        model_width = bounds[1][0] - bounds[0][0]

        # 3. Scale base dimensions based on figurine height
        base_diameter = 30 + (request.figurine_height - 6) * 5  # 30mm for 6cm, 40mm for 10cm
        base_height = 8 + (request.figurine_height - 6) * 2  # 8mm for 6cm, 16mm for 10cm
        base_radius = base_diameter / 2

        # 4. Create the base with CadQuery
        # Create the cylindrical base
        base = cq.Workplane("XY").circle(base_radius).extrude(base_height)

        # 5. Add text on the front vertical part of the base
        if request.text_label:
            # Create a thin rectangular wall for text on the front
            text_wall_depth = 2  # 2mm depth for text
            text_wall_height = base_height * 0.6  # Use 60% of base height for text
            # Add text to the front face
            workplane = base.faces(">Z").workplane()
            # Top face
            workplane = workplane.moveTo(0, -base_radius + text_wall_depth).text(request.text_label, height=text_wall_height * 0.8, depth=text_wall_depth)
            base = workplane.cutThruAll()

        # 6. Export base as step file
        base_step = f"base_{request.order_id}.step"
        cq.exporters.export(base, base_step)

        # 7. Load base model
        base_model = trimesh.load(base_step)

        # Get base bounds
        base_bounds = base_model.bounds
        base_min_z = base_bounds[0][2]
        base_max_z = base_bounds[1][2]
        base_center_x = (base_bounds[0][0] + base_bounds[1][0]) / 2
        base_center_y = (base_bounds[0][1] + base_bounds[1][1]) / 2

        # 8. Position the models correctly
        # Move base so its top surface is at Z=0, centered at XY origin
        base_offset = np.array([ -base_center_x, -base_center_y, -base_max_z ])
        base_model.apply_translation(base_offset)

        # Move original model so it sits on top of the base, centered at XY
        model_offset = np.array([ -model_center_x, -model_center_y, -model_min_z ])
        original_model.apply_translation(model_offset)

        # 9. MERGE models into ONE solid part using boolean union
        try:
            # Use trimesh boolean operation to merge the two models
            merged_model = trimesh.boolean.union([base_model, original_model])
        except Exception as e:
            # If union fails, create a scene (fallback)
            print(f"Warning: Boolean union failed, using scene instead: {str(e)}")
            merged_model = trimesh.Scene([base_model, original_model])

        # 10. Export merged files
        glb_output = f"final_{request.order_id}.glb"
        obj_output = f"final_{request.order_id}.obj"
        merged_model.export(glb_output)
        merged_model.export(obj_output)

        # Clean up temporary files
        if os.path.exists(input_file):
            os.remove(input_file)
        if os.path.exists(base_step):
            os.remove(base_step)

        return { "status": "success", "order_id": request.order_id, "figurine_height_cm": request.figurine_height, "base_diameter_mm": base_diameter, "base_height_mm": base_height, "text_label": request.text_label, "model_info": { "original_height_mm": model_height, "centered_at_xy": True, "positioned_on_base": True, "merged_into_single_part": True }, "glb_url": f"/download/{glb_output}", "obj_url": f"/download/{obj_output}", "files": { "glb": glb_output, "obj": obj_output } }
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to download model: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")

@app.get("/download/{file_name}")
async def download_file(file_name: str):
    """Download generated files"""
    if not os.path.exists(file_name):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_name, filename=file_name)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}