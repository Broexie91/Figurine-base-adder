from fastapi import FastAPI, BackgroundTasks
import cadquery as cq
import trimesh
import requests
import os

app = FastAPI()

@app.post("/generate-base/")
async def generate_base(model_url: str, text_label: str, order_id: str):
    # 1. Download het GLB bestand van Meshy
    resp = requests.get(model_url)
    input_file = f"input_{order_id}.glb"
    with open(input_file, "wb") as f:
        f.write(resp.content)

    # 2. Maak de base in CadQuery
    # We maken een simpele cilinder met tekst
    base = cq.Workplane("XY").circle(25).extrude(5)
    base = base.faces(">Z").workplane().text(text_label, 5, 1)
    
    base_step = f"base_{order_id}.step"
    cq.exporters.export(base, base_step)

    # 3. Samenvoegen met Trimesh
    original_model = trimesh.load(input_file)
    base_model = trimesh.load(base_step)
    
    # Scene maken (combineert beide)
    scene = trimesh.Scene([original_model, base_model])

    # 4. Exports opslaan
    glb_output = f"final_{order_id}.glb"
    obj_output = f"final_{order_id}.obj"
    
    scene.export(glb_output)
    scene.export(obj_output)

    return {
        "status": "success",
        "glb_url": f"https://jouw-railway-url.app/download/{glb_output}",
        "obj_url": f"https://jouw-railway-url.app/download/{obj_output}"
    }

# Toevoegen van een download endpoint zodat je de bestanden kunt ophalen
from fastapi.responses import FileResponse
@app.get("/download/{file_name}")
async def download_file(file_name: str):
    return FileResponse(path=file_name, filename=file_name)
