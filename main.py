from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
import tempfile
from pathlib import Path
import subprocess

app = FastAPI(title="GLB Figurine Base Adder")

@app.post("/add-base")
async def add_base(
    file: UploadFile = File(...),
    size_cm: int = Form(..., description="Figurine hoogte ZONDER base: 6, 8 of 10 cm"),
    text: str = Form("", description="Optionele tekst op de base")
):
    if size_cm not in [6, 8, 10]:
        raise HTTPException(status_code=400, detail="size_cm moet 6, 8 of 10 zijn")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        input_glb = tmp_path / "input.glb"
        output_glb = tmp_path / "output.glb"

        content = await file.read()
        with open(input_glb, "wb") as f:
            f.write(content)

        cmd = [
            "blender", "-b", "--python", "/app/blender_process.py", "--",
            str(input_glb), str(output_glb), str(size_cm), text
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0 or not output_glb.exists():
            print("Blender error:", result.stderr)
            raise HTTPException(status_code=500, detail="Verwerking mislukt")

        return FileResponse(
            path=output_glb,
            media_type="model/gltf-binary",
            filename="figurine_with_base.glb"
        )
