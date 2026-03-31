import logging
import sys
import os
import io
import zipfile
import subprocess
import tempfile
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

# ====================== LOGGING SETUP ======================
# Force unbuffered stdout so Railway sees every line immediately.
# Without this, Python buffers output and Railway may never receive it.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Also force Python's own stdout/stderr to be unbuffered
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

app = FastAPI(title="GLB Figurine Base Adder")


def stream_blender_logs(cmd: list, timeout: int = 120):
    """
    Run a subprocess and stream its stdout/stderr line-by-line to the
    Railway log in real time, instead of buffering everything in memory.
    Returns (returncode, full_stdout, full_stderr).
    """
    logger.info(f"Running command: {' '.join(cmd)}")
    stdout_lines = []
    stderr_lines = []

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,          # line-buffered
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    ) as proc:
        # Stream stdout
        for line in proc.stdout:
            line = line.rstrip()
            logger.info(f"[BLENDER] {line}")
            stdout_lines.append(line)

        # Capture stderr after stdout closes
        for line in proc.stderr:
            line = line.rstrip()
            logger.warning(f"[BLENDER STDERR] {line}")
            stderr_lines.append(line)

        proc.wait(timeout=timeout)

    return proc.returncode, "\n".join(stdout_lines), "\n".join(stderr_lines)


@app.get("/test-blender")
def test_blender():
    try:
        cmd = [
            "blender", "-b", "--python", "/app/blender_process.py", "--",
            "test_input.glb", "test_output.obj", "10", "test", "true", "false",
        ]
        returncode, stdout, stderr = stream_blender_logs(cmd, timeout=30)
        return {
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "success": returncode == 0,
        }
    except Exception as e:
        logger.exception("test-blender failed")
        return {"error": str(e)}


class BaseRequest(BaseModel):
    model_url: str
    size_cm: int
    order_nr: str
    text: str = ""
    add_base: bool = True
    add_keychain: bool = False


@app.post("/add-base")
async def add_base(request: BaseRequest):
    if request.size_cm not in [6, 8, 10]:
        raise HTTPException(status_code=400, detail="size_cm moet 6, 8 of 10 zijn")

    logger.info(f"Processing order {request.order_nr} — size={request.size_cm}cm, "
                f"add_base={request.add_base}, add_keychain={request.add_keychain}, "
                f"text='{request.text}'")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path  = Path(tmp)
        input_glb = tmp_path / "input.glb"
        output_obj = tmp_path / "output.obj"

        # 1. Download model
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                response = await client.get(request.model_url)
                response.raise_for_status()
                content = response.content
        except Exception as e:
            logger.error(f"Download failed: {e}")
            raise HTTPException(status_code=400, detail=f"Fout bij downloaden model: {str(e)}")

        with open(input_glb, "wb") as f:
            f.write(content)

        logger.info(f"Model downloaded: {len(content)} bytes → {input_glb}")

        text_arg = request.text if request.text.strip() else "--NO-TEXT--"

        # 2. Run Blender via xvfb — streaming logs to Railway in real time
        cmd = [
            "xvfb-run", "--auto-servernum", "--server-args=-screen 0 1024x768x24",
            "blender", "-b", "--python", "/app/blender_process.py", "--",
            str(input_glb), str(output_obj), str(request.size_cm), text_arg,
            str(request.add_base), str(request.add_keychain),
        ]

        try:
            returncode, stdout, stderr = stream_blender_logs(cmd, timeout=120)
        except subprocess.TimeoutExpired:
            logger.error("Blender timed out after 120s")
            raise HTTPException(status_code=500, detail="Verwerking timeout")
        except Exception as e:
            logger.exception("Unexpected error running Blender")
            raise HTTPException(status_code=500, detail=f"Onverwachte fout: {str(e)}")

        if returncode != 0 or not output_obj.exists():
            logger.error(f"Blender exited with code {returncode}")
            error_log = stdout[-2000:] if stdout else "No output"
            raise HTTPException(
                status_code=500,
                detail=f"Blender verwerking mislukt (code {returncode}). Log: {error_log}",
            )

        logger.info(f"Blender finished successfully for order {request.order_nr}")

        # 3. Build ZIP
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in tmp_path.iterdir():
                if file_path.is_file() and file_path.suffix.lower() in ['.obj', '.mtl', '.png', '.jpg']:
                    clean_name = "model" + file_path.suffix.lower()
                    zipf.write(file_path, arcname=clean_name)
                    logger.info(f"  Added to ZIP: {file_path.name} → {clean_name}")

        zip_buffer.seek(0)
        zip_data = zip_buffer.read()
        logger.info(f"ZIP created: {len(zip_data)} bytes")

        export_filename = f"3DModel_{request.order_nr}.zip"

        # 4. Return ZIP
        return Response(
            content=zip_data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{export_filename}"'},
        )
