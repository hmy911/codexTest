"""
STEP 2 - open Arena → import cam abc → apply settings → save auto
Usage (commandline): mayapy step2_build_arena.py --shotcodes 101_0280_0060 101_0280_0080
Usage (Maya Script Editor): 設定 SHOTCODES 後直接執行
"""

import os, sys, json
from pathlib import Path

# ══════════════════════════════════════════════
SHOTCODES    = ["101_0320_0020"]
PROJECT_ROOT = Path("X:/projects/2508_MASHLE")
ARENA_SCENE  = (PROJECT_ROOT
    / "assets/environment/Arena/work/scenes/vincentyang"
    / "batch_Arena/Arena_Light_setC_v001.ma")
# ══════════════════════════════════════════════

def _is_commandline():
    try:
        import maya.standalone as _sa
        _sa.initialize(name='python')
        return True
    except Exception:
        return False

_IS_CMD = _is_commandline()

def _parse_args():
    global SHOTCODES, PROJECT_ROOT, ARENA_SCENE
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--shotcodes", nargs="+", required=True)
    parser.add_argument("--project",   default=str(PROJECT_ROOT))
    parser.add_argument("--arena",     default=str(ARENA_SCENE))
    args, _ = parser.parse_known_args()
    SHOTCODES    = args.shotcodes
    PROJECT_ROOT = Path(args.project)
    ARENA_SCENE  = Path(args.arena)

if _IS_CMD:
    _parse_args()

import maya.cmds as cmds

# ── Load plugins ──
for plugin in ["AbcExport", "AbcImport"]:
    if not cmds.pluginInfo(plugin, query=True, loaded=True):
        try:
            cmds.loadPlugin(plugin)
            print(f"[OK] Loaded: {plugin}")
        except Exception as e:
            print(f"[WARN] {plugin}: {e}")

# ────────────────────────────────────────────────────────
def load_json(shotcode):
    seq       = shotcode.split("_")[1]
    json_path = (PROJECT_ROOT
        / f"shots/{seq}/{shotcode}/maya/lighting/auto/v001/data/shot_setting.json")
    if not json_path.exists():
        raise FileNotFoundError(f"Run Step 1 first:\n  {json_path}")
    with open(json_path) as f:
        return json.load(f), json_path

def find_imported_cam(before_nodes, render_cam):
    """import 後找新增的 camera transform"""
    after     = set(cmds.ls(dag=True, type="transform"))
    new_nodes = after - before_nodes

    for node in new_nodes:
        shapes = cmds.listRelatives(node, shapes=True, type="camera") or []
        if shapes:
            return node

    # fallback: 場景裡找同名
    if cmds.objExists(render_cam):
        print(f"  [WARN] cam not in new nodes, using existing: {render_cam}")
        return render_cam

    raise RuntimeError(
        f"Cannot find imported camera.\n"
        f"  Expected: {render_cam}\n"
        f"  New nodes: {new_nodes}"
    )

def set_renderable_cam(imported_cam):
    """全部關掉，只開目標"""
    for shape in cmds.ls(type="camera"):
        cmds.setAttr(f"{shape}.renderable", 0)
    shapes = cmds.listRelatives(imported_cam, shapes=True, type="camera") or []
    if not shapes:
        raise RuntimeError(f"No camera shape under: {imported_cam}")
    cmds.setAttr(f"{shapes[0]}.renderable", 1)
    print(f"  [OK] Renderable: {shapes[0]}")

def apply_render_settings(settings):
    """從 JSON renderSettings 還原到 defaultRenderGlobals / defaultResolution"""
    rs  = settings.get("renderSettings", {})
    rg  = "defaultRenderGlobals"
    res = "defaultResolution"

    def set_safe(node, attr, val):
        if val is None:
            return
        try:
            cmds.setAttr(f"{node}.{attr}", val)
        except Exception as e:
            print(f"  [WARN] setAttr {node}.{attr} = {val} → {e}")

    # Resolution
    set_safe(res, "width",             rs.get("width"))
    set_safe(res, "height",            rs.get("height"))
    set_safe(res, "deviceAspectRatio", rs.get("deviceAspectRatio"))
    set_safe(res, "pixelAspect",       rs.get("pixelAspect"))

    # Frame range（用 renderFrameRange）
    rf = settings["renderFrameRange"]
    set_safe(rg, "startFrame",      rf["start"])
    set_safe(rg, "endFrame",        rf["end"])
    set_safe(rg, "animation",       True)
    set_safe(rg, "byFrameStep",     rs.get("byFrame", 1))
    set_safe(rg, "extensionPadding",rs.get("extensionPadding"))
    set_safe(rg, "putFrameBeforeExt", rs.get("putFrameBeforeExt"))
    set_safe(rg, "periodInExt",     rs.get("periodInExt"))

    print(f"  [OK] Resolution : {rs.get('width')} x {rs.get('height')}")
    print(f"  [OK] Render range: {rf['start']} - {rf['end']}")

def apply_camera_settings(imported_cam, settings):
    """從 JSON cameraSettings 還原 camera attributes"""
    cs         = settings.get("cameraSettings", {})
    cam_shapes = cmds.listRelatives(imported_cam, shapes=True, type="camera") or []
    if not cam_shapes:
        print(f"  [WARN] No camera shape to apply settings")
        return
    cam_shape = cam_shapes[0]

    def set_safe(attr, val):
        if val is None:
            return
        try:
            cmds.setAttr(f"{cam_shape}.{attr}", val)
        except Exception as e:
            print(f"  [WARN] cam {attr} = {val} → {e}")

    set_safe("focalLength",            cs.get("focalLength"))
    set_safe("horizontalFilmAperture", cs.get("horizontalFilmAperture"))
    set_safe("verticalFilmAperture",   cs.get("verticalFilmAperture"))
    set_safe("lensSqueezeRatio",       cs.get("lensSqueezeRatio"))
    set_safe("filmFit",                cs.get("filmFit"))
    set_safe("filmFitOffset",          cs.get("filmFitOffset"))
    set_safe("horizontalFilmOffset",   cs.get("horizontalFilmOffset"))
    set_safe("verticalFilmOffset",     cs.get("verticalFilmOffset"))
    set_safe("overscan",               cs.get("overscan"))
    set_safe("nearClipPlane",          cs.get("nearClipPlane"))
    set_safe("farClipPlane",           cs.get("farClipPlane"))
    set_safe("panZoomEnabled",         cs.get("panZoomEnabled"))
    set_safe("zoom",                   cs.get("zoom"))
    set_safe("horizontalPan",          cs.get("horizontalPan"))
    set_safe("verticalPan",            cs.get("verticalPan"))

    print(f"  [OK] Camera settings applied → {cam_shape}")
    print(f"       focalLength : {cs.get('focalLength')}")
    print(f"       aperture H/V: {cs.get('horizontalFilmAperture')} / {cs.get('verticalFilmAperture')}")
    print(f"       overscan    : {cs.get('overscan')}")

# ────────────────────────────────────────────────────────
def process_shot(shotcode):
    seq = shotcode.split("_")[1]

    print(f"\n{'='*60}")
    print(f"  SHOT: {shotcode}")
    print(f"{'='*60}")

    # ── Load JSON ──
    try:
        settings, json_path = load_json(shotcode)
    except FileNotFoundError as e:
        print(f"  [ERROR] {e}")
        return False

    render_cam  = settings["renderCamera"]
    cam_abc     = settings["camAbcPath"]
    rf          = settings["renderFrameRange"]
    is_animated = settings.get("cameraAnimated", False)
    anim_reason = settings.get("cameraAnimReason", "unknown")

    print(f"  Camera    : {render_cam}")
    print(f"  Animated  : {is_animated} ({anim_reason})")
    print(f"  Render    : {rf['start']} - {rf['end']}")

    if not Path(cam_abc).exists():
        print(f"  [ERROR] camRender.abc not found: {cam_abc}")
        return False

    # ── Open Arena scene ──
    if not ARENA_SCENE.exists():
        print(f"  [ERROR] Arena scene not found: {ARENA_SCENE}")
        return False

    print(f"  Opening Arena: {ARENA_SCENE.name}")
    cmds.file(str(ARENA_SCENE), open=True, force=True)
    print(f"  [OK] Opened")

    # ── Import camera abc ──
    before = set(cmds.ls(dag=True, type="transform"))
    try:
        cmds.AbcImport(cam_abc, mode="import")
    except Exception as e:
        print(f"  [ERROR] AbcImport: {e}")
        return False

    try:
        imported_cam = find_imported_cam(before, render_cam)
    except RuntimeError as e:
        print(f"  [ERROR] {e}")
        return False
    print(f"  [OK] Imported cam: {imported_cam}")

    # ── Set renderable ──
    try:
        set_renderable_cam(imported_cam)
    except RuntimeError as e:
        print(f"  [ERROR] {e}")
        return False

    # ── Apply render settings（resolution + frame range）──
    apply_render_settings(settings)

    # ── Apply camera settings（focal length, aperture etc）──
    apply_camera_settings(imported_cam, settings)

    # ── Save auto scene ──
    auto_dir   = PROJECT_ROOT / f"shots/{seq}/{shotcode}/maya/lighting/auto/v001"
    auto_scene = auto_dir / f"MSL_{shotcode}_light_v002_auto.ma"

    cmds.file(rename=str(auto_scene).replace("\\", "/"))
    cmds.file(save=True, type="mayaAscii")
    print(f"  [OK] Saved: {auto_scene.name}")

    # ── Update JSON ──
    settings["autoScene"]   = str(auto_scene).replace("\\", "/")
    settings["importedCam"] = imported_cam
    with open(json_path, "w") as f:
        json.dump(settings, f, indent=2)
    print(f"  [OK] JSON updated")

    return True

# ── Run ──
results = {}
for sc in SHOTCODES:
    ok = process_shot(sc)
    results[sc] = "OK" if ok else "FAILED"

print(f"\n{'='*60}")
print("  SUMMARY")
print(f"{'='*60}")
for sc, status in results.items():
    mark = "✓" if status == "OK" else "✗"
    print(f"  {mark} {sc} → {status}")
print()

if _IS_CMD:
    import maya.standalone as _sa
    _sa.uninitialize()
