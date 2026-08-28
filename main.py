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
import json
import struct
import base64
from PIL import Image

app = FastAPI(title="GLB Figurine Base Adder")

@app.get("/test-blender")
def test_blender():
    try:
        cmd = ["blender", "-b", "--python", "/app/blender_process.py", "--",
               "test_input.glb", "test_output.obj", "10", "true", "false", "false"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return {
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "success": result.returncode == 0
        }
    except Exception as e:
        return {"error": str(e)}

_PBR_NON_ALBEDO_HINTS = (
    "normal", "norm", "nor_", "_nor", "rough", "metal", "metallic",
    "ao", "orm", "arm", "specular", "spec", "emiss", "emit",
    "height", "disp", "bump", "gloss", "occlusion", "cavity",
)


def _looks_like_non_albedo(name: str) -> bool:
    n = (name or "").lower()
    return any(hint in n for hint in _PBR_NON_ALBEDO_HINTS)


def _parse_glb_chunks(glb_bytes: bytes):
    if len(glb_bytes) < 12 or glb_bytes[:4] != b"glTF":
        return None, None
    offset = 12
    json_chunk = None
    bin_chunk = None
    while offset + 8 <= len(glb_bytes):
        chunk_len, chunk_type = struct.unpack_from("<I4s", glb_bytes, offset)
        offset += 8
        chunk = glb_bytes[offset:offset + chunk_len]
        offset += chunk_len
        if chunk_type == b"JSON":
            json_chunk = json.loads(chunk.decode("utf-8"))
        elif chunk_type == b"BIN\x00":
            bin_chunk = chunk
    return json_chunk, bin_chunk


def _glb_image_bytes(gltf: dict, bin_chunk: bytes, image_index: int):
    images = gltf.get("images") or []
    if image_index is None or image_index < 0 or image_index >= len(images):
        return None, None
    image = images[image_index]
    mime = image.get("mimeType") or ""
    name = image.get("name") or ""
    uri = image.get("uri")
    if uri:
        if uri.startswith("data:") and "," in uri:
            header, b64 = uri.split(",", 1)
            mime = mime or header.split(";")[0].replace("data:", "")
            return base64.b64decode(b64), (name, mime)
        return None, None
    if bin_chunk is None:
        return None, None
    views = gltf.get("bufferViews") or []
    view_index = image.get("bufferView")
    if view_index is None or view_index >= len(views):
        return None, None
    view = views[view_index]
    start = int(view.get("byteOffset") or 0)
    length = int(view["byteLength"])
    return bin_chunk[start:start + length], (name, mime)


def extract_glb_albedo_png(glb_path: Path, out_png: Path) -> bool:
    """
    Pull the Base Color / albedo map out of a GLB and write model.png.

    This bypasses Blender node order, so Meshy PBR extras (normal/rough/metal)
    cannot overwrite the print texture.
    """
    gltf, bin_chunk = _parse_glb_chunks(glb_path.read_bytes())
    if not gltf:
        print("GLB albedo extract: not a GLB / missing JSON chunk")
        return False

    textures = gltf.get("textures") or []
    materials = gltf.get("materials") or []
    images = gltf.get("images") or []
    candidates = []

    for mat in materials:
        pbr = mat.get("pbrMetallicRoughness") or {}
        tex_info = pbr.get("baseColorTexture") or {}
        tex_index = tex_info.get("index")
        if tex_index is None or tex_index >= len(textures):
            continue
        image_index = textures[tex_index].get("source")
        blob, meta = _glb_image_bytes(gltf, bin_chunk, image_index)
        if not blob:
            continue
        name, mime = meta
        score = 20 if _looks_like_non_albedo(name) else 100
        candidates.append((score, len(blob), blob, name or mime or "baseColor", mime))

    for i, image in enumerate(images):
        blob, meta = _glb_image_bytes(gltf, bin_chunk, i)
        if not blob:
            continue
        name, mime = meta
        label = name or mime or f"image[{i}]"
        score = 8 if _looks_like_non_albedo(label) else 40
        candidates.append((score, len(blob), blob, label, mime))

    if not candidates:
        print("GLB albedo extract: no embedded images found")
        return False

    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    score, size, blob, label, mime = candidates[0]
    print(f"GLB albedo extract: picked '{label}' ({size} bytes, mime={mime}, score={score})")
    try:
        img = Image.open(io.BytesIO(blob))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA") if "A" in img.getbands() else img.convert("RGB")
        img.save(out_png, format="PNG")
        print(f"GLB albedo extract: wrote {out_png} ({out_png.stat().st_size} bytes)")
        return True
    except Exception as e:
        print(f"GLB albedo extract: Pillow decode failed ({e})")
        if blob[:8] == b"\x89PNG\r\n\x1a\n":
            out_png.write_bytes(blob)
            print(f"GLB albedo extract: wrote raw PNG {out_png}")
            return True
        return False


def rewrite_mtl_map_kd(mtl_path: Path, texture_filename: str = "model.png") -> None:
    if not mtl_path.exists():
        print("MTL rewrite: file not found")
        return
    lines = mtl_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    new_lines = []
    rewrote = 0
    for line in lines:
        if line.lstrip().lower().startswith("map_kd"):
            new_lines.append(f"map_Kd {texture_filename}\n")
            rewrote += 1
        else:
            new_lines.append(line)
    if rewrote == 0:
        injected = False
        with_inject = []
        for line in new_lines:
            with_inject.append(line)
            if (not injected) and line.lstrip().lower().startswith("newmtl"):
                with_inject.append(f"map_Kd {texture_filename}\n")
                injected = True
        if not injected:
            with_inject.append(f"map_Kd {texture_filename}\n")
        new_lines = with_inject
        print(f"MTL rewrite: injected map_Kd {texture_filename}")
    else:
        print(f"MTL rewrite: rewrote {rewrote} map_Kd line(s) -> {texture_filename}")
    mtl_path.write_text("".join(new_lines), encoding="utf-8")


class BaseRequest(BaseModel):
    model_url: str = "https://drive.google.com/uc?export=download&id="
    size_cm: float = 10
    order_nr: str = "1000" # Toegevoegd voor de bestandsnaam
    add_base: bool = True
    add_keychain: bool = False


async def _process_model(request: BaseRequest, skip_repair: bool = False, aggressive: bool = False, preserve_uv: bool = False):
    """
    Shared logic for /add-base, /add-base-raw, /add-base-tripo and /add-base-meshy.
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
        print(f"Flags → skip_repair={skip_repair}, aggressive={aggressive}, preserve_uv={preserve_uv}")

        # 2. Blender aanroepen met XVFB (headless display)
        # Arguments: input, output, size_cm, add_base, add_keychain, skip_repair, aggressive, preserve_uv
        cmd = [
            "xvfb-run", "--auto-servernum", "--server-args=-screen 0 1024x768x24",
            "blender", "-b", "--python", "/app/blender_process.py", "--",
            str(input_glb), str(output_obj), str(request.size_cm),
            str(request.add_base), str(request.add_keychain),
            str(skip_repair), str(aggressive), str(preserve_uv)
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

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

            # 3. Force albedo from the source GLB + consistent MTL link
            albedo_png = tmp_path / "model.png"
            extracted = extract_glb_albedo_png(input_glb, albedo_png)
            if extracted:
                print("Using albedo extracted from source GLB (overrides Blender image pick)")
            elif albedo_png.exists():
                print("GLB extract failed; keeping Blender-exported model.png")
            else:
                print("WARNING: no model.png after Blender or GLB extract")
            rewrite_mtl_map_kd(tmp_path / "model.mtl", "model.png")

            # 4. ZIP bestand genereren
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
                for file_path in tmp_path.iterdir():
                    if file_path.name in ("model.obj", "model.mtl", "model.png", "model.jpg"):
                        zipf.write(file_path, arcname=file_path.name)

            zip_buffer.seek(0)
            zip_data = zip_buffer.read()

            export_filename = f"3DModel_{request.order_nr}.zip"

            return Response(
                content=zip_data,
                media_type="application/zip",
                headers={
                    "Content-Disposition": f'attachment; filename="{export_filename}"'
                }
            )

        except subprocess.TimeoutExpired as e:
            partial_out = (e.output or b"").decode(errors="replace") if isinstance(e.output, bytes) else (e.output or "")
            partial_err = (e.stderr or b"").decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
            print("--- Blender TIMEOUT partial stdout ---")
            print(partial_out or "(geen output)")
            print("--- Blender TIMEOUT partial stderr ---")
            print(partial_err or "(geen output)")
            raise HTTPException(status_code=500, detail="Verwerking timeout (300s overschreden)")
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Onverwachte fout: {str(e)}")


@app.post("/add-base")
async def add_base(request: BaseRequest):
    """Process GLB model with full mesh repair pipeline."""
    return await _process_model(request, skip_repair=False, aggressive=False)


@app.post("/add-base-raw")
async def add_base_raw(request: BaseRequest):
    """
    Process GLB model WITHOUT mesh repair.
    Only does: import, scale, base/text/keychain, texture export, OBJ export.
    Lets Marketiger handle all mesh fixing and hole repair.
    """
    return await _process_model(request, skip_repair=True, aggressive=False)


@app.post("/add-base-tripo")
async def add_base_tripo(request: BaseRequest):
    """
    Aggressive repair pipeline optimized for Tripo AI models.

    - Stronger non-manifold / zero-face / interior-face / shell cleanup
    - Better UV protection (stricter outlier detection) to prevent vlekken/strepen
    - Safety guards: never deletes feet or large geometry drops
    - Same base generation + texture preservation as /add-base

    Use this when the standard /add-base leaves too many non-manifold edges,
    interior faces or texture artefacts on Tripo-generated models.
    """
    return await _process_model(request, skip_repair=False, aggressive=True, preserve_uv=False)


@app.post("/add-base-meshy")
async def add_base_meshy(request: BaseRequest):
    """
    Conservative pipeline for Meshy AI models.

    Meshy GLBs usually have clean UVs and a full PBR stack (albedo +
    normal/rough/metal). Aggressive Tripo repair would remap UV islands
    and the old texture exporter could pick a non-albedo map.

    This endpoint:
    - Adds the same convex base as the other routes
    - Runs only mild mesh repair (no deep_repair / ghost-shell wipe / UV outlier)
    - Exports the Principled Base Color map as model.png
    - Rewrites the MTL so map_Kd always points at model.png
    """
    return await _process_model(request, skip_repair=False, aggressive=False, preserve_uv=True)
