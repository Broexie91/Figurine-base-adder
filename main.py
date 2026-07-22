from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import tempfile
from pathlib import Path
import subprocess
import os
import zipfile
import io
import time
import threading
from typing import Generator

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


def _stream_process(request: BaseRequest, skip_repair: bool = False) -> Generator[bytes, None, None]:
    """
    Generator that streams progress (to keep Railway connection alive)
    and ends with a pure ZIP after a clear marker.
    """
    if request.size_cm <= 0:
        yield b"# ERROR: size_cm moet een positief getal zijn\n"
        return

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        input_glb = tmp_path / "input.glb"
        output_obj = tmp_path / "model.obj"

        # 1. Download model
        yield f"# status: downloading model for order {request.order_nr}\n".encode()
        try:
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                response = client.get(request.model_url)
                response.raise_for_status()
                content = response.content
        except Exception as e:
            yield f"# ERROR: Fout bij downloaden model: {str(e)}\n".encode()
            return

        with open(input_glb, "wb") as f:
            f.write(content)

        yield f"# status: downloaded {len(content)} bytes\n".encode()
        print(f"Input file downloaded for order {request.order_nr}, size: {len(content)} bytes")

        # 2. Start Blender with Popen so we can stream stdout live
        cmd = [
            "xvfb-run", "--auto-servernum", "--server-args=-screen 0 1024x768x24",
            "blender", "-b", "--python", "/app/blender_process.py", "--",
            str(input_glb), str(output_obj), str(request.size_cm),
            str(request.add_base), str(request.add_keychain), str(skip_repair)
        ]

        yield b"# status: starting Blender\n"
        print("--- Blender starting (streaming mode) ---")

        start_time = time.time()
        TIMEOUT = 900  # 15 minutes

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # line buffered
            )

            # Read lines and also send keep-alives if quiet for too long
            last_yield = time.time()
            while True:
                # Check timeout
                if time.time() - start_time > TIMEOUT:
                    process.kill()
                    yield b"# ERROR: Verwerking timeout (900s overschreden)\n"
                    print("--- Blender TIMEOUT ---")
                    return

                # Non-blocking read with short timeout via select or just poll
                line = process.stdout.readline()
                if line:
                    # Real progress from Blender → keeps connection very alive
                    yield line.encode() if isinstance(line, str) else line
                    print(line, end="")  # also to Railway logs
                    last_yield = time.time()
                else:
                    # No new line — check if process finished
                    if process.poll() is not None:
                        break
                    # Quiet for > 20 seconds → send keep-alive heartbeat
                    if time.time() - last_yield > 20:
                        yield f"# keepalive {int(time.time() - start_time)}s\n".encode()
                        last_yield = time.time()
                    time.sleep(0.3)

            # Process finished
            returncode = process.wait()
            print(f"--- Blender return code: {returncode} ---")

            if returncode != 0 or not output_obj.exists():
                yield f"# ERROR: Blender verwerking mislukt (returncode={returncode})\n".encode()
                return

            yield b"# status: Blender finished successfully, creating ZIP...\n"

            # 3. ZIP bestand genereren
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
                for file_path in tmp_path.iterdir():
                    if file_path.is_file() and file_path.suffix.lower() in ['.obj', '.mtl', '.png', '.jpg']:
                        clean_name = "model" + file_path.suffix.lower()
                        zipf.write(file_path, arcname=clean_name)

            zip_buffer.seek(0)
            zip_data = zip_buffer.read()

            # 4. Clear marker + pure ZIP (client moet alles vóór deze marker negeren)
            yield b"\n---ZIP---\n"
            yield zip_data

            print(f"✅ Streaming complete for order {request.order_nr}, ZIP size: {len(zip_data)} bytes")

        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            yield f"# ERROR: Onverwachte fout: {str(e)}\n".encode()


@app.post("/add-base")
async def add_base(request: BaseRequest):
    """Process GLB model with full mesh repair pipeline. Streams progress + ZIP."""
    export_filename = f"3DModel_{request.order_nr}.zip"
    return StreamingResponse(
        _stream_process(request, skip_repair=False),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{export_filename}"',
            "X-Stream-Format": "progress-then-zip",
            "X-Zip-Marker": "---ZIP---",
        }
    )


@app.post("/add-base-raw")
async def add_base_raw(request: BaseRequest):
    """
    Process GLB model WITHOUT mesh repair.
    Streams live progress (keeps Railway connection alive) and ends with pure ZIP after marker.
    """
    export_filename = f"3DModel_{request.order_nr}.zip"
    return StreamingResponse(
        _stream_process(request, skip_repair=True),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{export_filename}"',
            "X-Stream-Format": "progress-then-zip",
            "X-Zip-Marker": "---ZIP---",
        }
    )
