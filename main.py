from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
import httpx
import tempfile
from pathlib import Path
import subprocess
import os
import zipfile
import io

app = FastAPI(title="GLB Figurine Base Adder")

@app.get("/test-blender")
def test_blender():
    try:
        cmd = ["blender", "-b", "--python", "/app/blender_process.py", "--",
               "test_input.glb", "test_output.obj", "10", "true", "false"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return {
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "success": result.returncode == 0
        }
    except Exception as e:
        return {"error": str(e)}

class BaseRequest(BaseModel):
    model_url: str
    size_cm: float
    order_nr: str  # Toegevoegd voor de bestandsnaam
    add_base: bool = True
    add_keychain: bool = False


async def _process_model(request: BaseRequest, skip_repair: bool = False):
    """
    Shared logic for both /add-base and /add-base-raw endpoints.
    Downloads the GLB, runs Blender, and returns a ZIP response.
    """
    # Validatie van de input
    if request.size_cm <= 0:
        raise HTTPException(status_code=400, detail="size_cm moet een positief getal zijn")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        input_glb = tmp_path / "input.glb"
        output_obj = tmp_path / "model.obj"

        # 1. Download model
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                response = await client.get(request.model_url)
                response.raise_for_status()
                content = response.content
        except Exception as e:
            print(f"Error downloading model: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Fout bij downloaden model: {str(e)}")

        with open(input_glb, "wb") as f:
            f.write(content)

        print(f"Input file downloaded for order {request.order_nr}, size: {len(content)} bytes")
        
        # 2. Blender aanroepen met XVFB (headless display)
        cmd = [
            "xvfb-run", "--auto-servernum", "--server-args=-screen 0 1024x768x24",
            "blender", "-b", "--python", "/app/blender_process.py", "--",
            str(input_glb), str(output_obj), str(request.size_cm),
            str(request.add_base), str(request.add_keychain), str(skip_repair)
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            # Always flush Blender output to Railway logs so we can debug any run
            print("--- Blender stdout ---")
            print(result.stdout)
            print("--- Blender stderr ---")
            print(result.stderr)
            print(f"--- Blender return code: {result.returncode} ---")

            if result.returncode != 0 or not output_obj.exists():
                error_log = result.stdout[-1000:] if result.stdout else "No output"
                raise HTTPException(
                    status_code=500,
                    detail=f"Blender verwerking mislukt. Error log: {error_log}"
                )

            # 3. ZIP bestand genereren
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
                for file_path in tmp_path.iterdir():
                    # Pak alle relevante output bestanden (.obj, .mtl en textures)
                    if file_path.is_file() and file_path.suffix.lower() in ['.obj', '.mtl', '.png', '.jpg']:
                        clean_name = "model" + file_path.suffix.lower()
                        zipf.write(file_path, arcname=clean_name)

            zip_buffer.seek(0)
            zip_data = zip_buffer.read()

            # Dynamische bestandsnaam samenstellen
            export_filename = f"3DModel_{request.order_nr}.zip"

            # 4. ZIP terugsturen naar de gebruiker
            return Response(
                content=zip_data,
                media_type="application/zip",
                headers={
                    "Content-Disposition": f'attachment; filename="{export_filename}"'
                }
            )

        except subprocess.TimeoutExpired as e:
            # Dump whatever partial output Blender produced before the timeout
            partial_out = (e.output or b"").decode(errors="replace") if isinstance(e.output, bytes) else (e.output or "")
            partial_err = (e.stderr or b"").decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
            print("--- Blender TIMEOUT partial stdout ---")
            print(partial_out or "(geen output)")
            print("--- Blender TIMEOUT partial stderr ---")
            print(partial_err or "(geen output)")
            raise HTTPException(status_code=500, detail="Verwerking timeout (120s overschreden)")
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Onverwachte fout: {str(e)}")


@app.post("/add-base")
async def add_base(request: BaseRequest):
    """Process GLB model with full mesh repair pipeline."""
    return await _process_model(request, skip_repair=False)


@app.post("/add-base-raw")
async def add_base_raw(request: BaseRequest):
    """
    Process GLB model WITHOUT mesh repair.
    Only does: import, scale, base/text/keychain, texture export, OBJ export.
    Lets Marketiger handle all mesh fixing and hole repair.
    """
    return await _process_model(request, skip_repair=True)
