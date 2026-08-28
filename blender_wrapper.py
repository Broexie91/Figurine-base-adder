"""
Runtime patcher for blender_process.py.

Keeps the large original script untouched on GitHub while enabling:
- preserve_uv / Meshy profile (argv[7])
- skip UV-outlier / deep_repair / ghost-shell wipes on clean Meshy meshes
"""
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(SCRIPT_DIR, "blender_process.py")

src = open(TARGET, "r", encoding="utf-8").read()
applied = []


def patch(old, new, label):
    global src
    if old not in src:
        print(f"wrapper patch skipped (pattern not found): {label}", flush=True)
        return False
    src = src.replace(old, new, 1)
    applied.append(label)
    return True


patch(
    "    aggressive     = argv[6].lower() == 'true' if len(argv) > 6 else False\n",
    "    aggressive     = argv[6].lower() == 'true' if len(argv) > 6 else False\n"
    "    preserve_uv    = argv[7].lower() == 'true' if len(argv) > 7 else False\n",
    "parse preserve_uv",
)

patch(
    "    if aggressive:\n"
    "        print(\"\U0001f525 AGGRESSIVE / TRIPO mode enabled (UV-safe settings)\", flush=True)\n",
    "    if aggressive:\n"
    "        print(\"\U0001f525 AGGRESSIVE / TRIPO mode enabled (UV-safe settings)\", flush=True)\n"
    "    if preserve_uv:\n"
    "        print(\"PRESERVE_UV / MESHY mode: keep original UVs, pick albedo only\", flush=True)\n",
    "log preserve_uv",
)

patch(
    "        MAX_VERTS = 350_000 if aggressive else 500_000\n"
    "        TARGET_VERTS = 280_000 if aggressive else 400_000\n",
    "        if aggressive:\n"
    "            MAX_VERTS, TARGET_VERTS = 350_000, 280_000\n"
    "        elif preserve_uv:\n"
    "            MAX_VERTS, TARGET_VERTS = 800_000, 600_000\n"
    "        else:\n"
    "            MAX_VERTS, TARGET_VERTS = 500_000, 400_000\n",
    "meshy decimate limits",
)

patch(
    "        print(\"Pinning out-of-range UVs after base union...\")\n"
    "        pin_new_face_uvs(model, uv_coord=(0.008, 0.008))\n",
    "        if preserve_uv:\n"
    "            print(\"PRESERVE_UV: skip global out-of-range UV pin\", flush=True)\n"
    "        else:\n"
    "            print(\"Pinning out-of-range UVs after base union...\")\n"
    "            pin_new_face_uvs(model, uv_coord=(0.008, 0.008))\n",
    "skip global UV pin",
)

patch(
    "            if open_e > threshold:\n"
    "                print(\"  \u26a0\ufe0f Still non-manifold. Running deep_repair...\", flush=True)\n",
    "            if open_e > threshold and not preserve_uv:\n"
    "                print(\"  \u26a0\ufe0f Still non-manifold. Running deep_repair...\", flush=True)\n",
    "skip meshy deep_repair",
)

patch(
    "    # FINAL GHOST SHELLS\n"
    "    if not skip_repair:\n"
    "        if aggressive:\n"
    "            remove_ghost_shells_safe(model, min_faces=15, bottom_protect_ratio=0.18)\n"
    "        else:\n"
    "            remove_ghost_shells(model, min_faces=50)\n"
    "    else:\n"
    "        print(\"\u26a1 Skipping ghost shell removal in SKIP_REPAIR mode\", flush=True)\n",
    "    # FINAL GHOST SHELLS\n"
    "    if skip_repair:\n"
    "        print(\"\u26a1 Skipping ghost shell removal in SKIP_REPAIR mode\", flush=True)\n"
    "    elif preserve_uv:\n"
    "        print(\"PRESERVE_UV: skipping ghost-shell removal\", flush=True)\n"
    "    elif aggressive:\n"
    "        remove_ghost_shells_safe(model, min_faces=15, bottom_protect_ratio=0.18)\n"
    "    else:\n"
    "        remove_ghost_shells(model, min_faces=50)\n",
    "skip meshy ghost shells",
)

patch(
    "        print(\"Running UV outlier detection...\")\n"
    "        fixed_count = fix_uv_outliers(model, uv_dist_threshold=uv_threshold)\n",
    "        if preserve_uv:\n"
    "            print(\"PRESERVE_UV: skipping UV outlier detection\", flush=True)\n"
    "            fixed_count = 0\n"
    "        else:\n"
    "            print(\"Running UV outlier detection...\")\n"
    "            fixed_count = fix_uv_outliers(model, uv_dist_threshold=uv_threshold)\n",
    "skip meshy UV outliers",
)

patch(
    "        if aggressive:\n"
    "            print(f\"\U0001f525 Second UV outlier pass after triangulation (threshold={uv_threshold})...\", flush=True)\n"
    "            fix_uv_outliers(model, uv_dist_threshold=uv_threshold)\n",
    "        if aggressive and not preserve_uv:\n"
    "            print(f\"\U0001f525 Second UV outlier pass after triangulation (threshold={uv_threshold})...\", flush=True)\n"
    "            fix_uv_outliers(model, uv_dist_threshold=uv_threshold)\n",
    "skip second UV pass",
)

print(f"blender_wrapper applied {len(applied)} patch(es): {', '.join(applied)}", flush=True)
exec(compile(src, TARGET, "exec"), {"__name__": "__main__", "__file__": TARGET})
