from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import httpx
import tempfile
from pathlib import Path
import subprocess
import os

app = FastAPI(title="GLB Figurine Base Adder")

@app.get("/test-blender")
def test_blender():
    """
    Test of Blender correct aangeroepen kan worden (handig voor debug).
    """
    try:
        cmd = [
            "blender", "-b", "--python", "/app/blender_process.py", "--",
            "test_input.glb", "test_output.glb", "10", "test"
        ]
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
    size_cm: int
    text: str = ""

@app.post("/add-base")
async def add_base(request: BaseRequest):
    if request.size_cm not in [6, 8, 10]:
        raise HTTPException(status_code=400, detail="size_cm moet 6, 8 of 10 zijn")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        input_glb = tmp_path / "input.glb"
        output_glb = tmp_path / "output.glb"

        # Download model file from URL
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                response = await client.get(request.model_url)
                response.raise_for_status()
                content = response.content
        except Exception as e:
            print(f"Error downloading model from {request.model_url}: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Fout bij downloaden model: {str(e)}")

        with open(input_glb, "wb") as f:
            f.write(content)

        print(f"Input file downloaded, size: {len(content)} bytes")
        print(f"Parameters: size_cm={request.size_cm}, text='{request.text}'")

        # Blender aanroepen met Xvfb (virtueel display)
        cmd = [
            "xvfb-run", "--auto-servernum", "--server-args=-screen 0 1024x768x24",
            "blender", "-b", "--python", "/app/blender_process.py", "--",
            str(input_glb), str(output_glb), str(request.size_cm), request.text
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minuten max
                env=os.environ.copy()  # behoud env vars
            )

            # Log de output van Blender (heel belangrijk voor debug!)
            print("Blender stdout:")
            print(result.stdout)
            print("Blender stderr:")
            print(result.stderr)
            print(f"Return code: {result.returncode}")

            if result.returncode != 0 or not output_glb.exists():
                error_msg = result.stderr.strip() or "Geen output bestand aangemaakt"
                print(f"Blender processing failed: {error_msg}")
                raise HTTPException(status_code=500, detail=f"Verwerking mislukt: {error_msg}")

            print("SUCCESS: output.glb created")

            return FileResponse(
                path=output_glb,
                media_type="model/gltf-binary",
                filename="figurine_with_base.glb"
            )

        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=500, detail="Verwerking timeout (te lang bezig)")
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Onverwachte fout: {str(e)}")
