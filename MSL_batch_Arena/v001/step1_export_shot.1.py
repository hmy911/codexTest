"""
STEP 1 - export camera abc + full settings JSON
Usage (commandline): mayapy step1_export_shot.py --shotcodes 101_0280_0060 101_0280_0080
Usage (Maya Script Editor): 設定 SHOTCODES 後直接執行
"""

import os, sys, json
from pathlib import Path

# ══════════════════════════════════════════════
# MAYA SCRIPT EDITOR MODE：改這裡
SHOTCODES    = ["101_0280_0060"]
# SHOTCODES    = ["101_0280_0060", "101_0280_0070"]
PROJECT_ROOT = Path("X:/projects/2508_MASHLE")
# ══════════════════════════════════════════════

# ── commandline mode: 覆蓋上面的設定 ──
def _parse_args():
    global SHOTCODES, PROJECT_ROOT    # ← 兩個一起放最頂部
    if len(sys.argv) > 1:
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--shotcodes", nargs="+", required=True)
        parser.add_argument("--project",   default=str(PROJECT_ROOT))
        args, _ = parser.parse_known_args()
        SHOTCODES    = args.shotcodes
        PROJECT_ROOT = Path(args.project)

try:
    _parse_args()
except Exception:
    pass  # Script Editor では argparse skip

import maya.cmds as cmds
import maya.mel  as mel

# ── Load plugins ──
for plugin in ["AbcExport", "AbcImport"]:
    if not cmds.pluginInfo(plugin, query=True, loaded=True):
        try:
            cmds.loadPlugin(plugin)
            print(f"[OK] Loaded: {plugin}")
        except Exception as e:
            print(f"[WARN] {plugin}: {e}")

# ────────────────────────────────────────────────────────
def find_render_cam():
    defaults = {"persp", "top", "front", "side", "camera_turntable"}
    all_cams = []
    for cam_shape in cmds.ls(type="camera"):
        parents = cmds.listRelatives(cam_shape, parent=True)
        if not parents:
            continue
        cam_transform = parents[0]
        base_name = cam_transform.split(":")[-1]
        if base_name in defaults or base_name.startswith("pasted__"):
            continue
        all_cams.append((cam_transform, cam_shape))

    for t, s in all_cams:
        if cmds.getAttr(f"{s}.renderable"):
            cmds.setAttr(f"{s}.renderable", 1)
            return t, s
    for t, s in all_cams:
        if "MainCam" in t:
            cmds.setAttr(f"{s}.renderable", 1)
            print(f"  [WARN] renderable=False, using MainCam: {t}")
            return t, s
    if len(all_cams) == 1:
        t, s = all_cams[0]
        cmds.setAttr(f"{s}.renderable", 1)
        print(f"  [WARN] only one cam, using: {t}")
        return t, s
    raise RuntimeError(f"Cannot find render cam. Candidates: {all_cams}")

def get_attr_safe(node, attr, default=None):
    try:
        return cmds.getAttr(f"{node}.{attr}")
    except Exception:
        return default

def collect_render_settings():
    rg  = "defaultRenderGlobals"
    res = "defaultResolution"
    return {
        # Resolution
        "width"              : get_attr_safe(res, "width"),
        "height"             : get_attr_safe(res, "height"),
        "deviceAspectRatio"  : get_attr_safe(res, "deviceAspectRatio"),
        "pixelAspect"        : get_attr_safe(res, "pixelAspect"),
        "dotsPerInch"        : get_attr_safe(res, "dotsPerInch"),
        # Frame range
        "startFrame"         : get_attr_safe(rg, "startFrame"),
        "endFrame"           : get_attr_safe(rg, "endFrame"),
        "byFrame"            : get_attr_safe(rg, "byFrameStep"),
        # Image
        "imageFormat"        : get_attr_safe(rg, "imageFormat"),
        "animation"          : get_attr_safe(rg, "animation"),
        "extensionPadding"   : get_attr_safe(rg, "extensionPadding"),
        "outFormatControl"   : get_attr_safe(rg, "outFormatControl"),
        "putFrameBeforeExt"  : get_attr_safe(rg, "putFrameBeforeExt"),
        "periodInExt"        : get_attr_safe(rg, "periodInExt"),
        # Renderer
        "currentRenderer"    : get_attr_safe(rg, "currentRenderer"),
        "renderAll"          : get_attr_safe(rg, "renderAll"),
    }

def collect_camera_settings(cam_transform, cam_shape):
    return {
        "transform"              : cam_transform,
        "shape"                  : cam_shape,
        # Lens
        "focalLength"            : get_attr_safe(cam_shape, "focalLength"),
        "horizontalFilmAperture" : get_attr_safe(cam_shape, "horizontalFilmAperture"),
        "verticalFilmAperture"   : get_attr_safe(cam_shape, "verticalFilmAperture"),
        "lensSqueezeRatio"       : get_attr_safe(cam_shape, "lensSqueezeRatio"),
        # Film back
        "filmFit"                : get_attr_safe(cam_shape, "filmFit"),
        "filmFitOffset"          : get_attr_safe(cam_shape, "filmFitOffset"),
        "horizontalFilmOffset"   : get_attr_safe(cam_shape, "horizontalFilmOffset"),
        "verticalFilmOffset"     : get_attr_safe(cam_shape, "verticalFilmOffset"),
        # Gate / display
        "displayResolution"      : get_attr_safe(cam_shape, "displayResolution"),
        "displayGateMask"        : get_attr_safe(cam_shape, "displayGateMask"),
        "displayGateMaskOpacity" : get_attr_safe(cam_shape, "displayGateMaskOpacity"),
        "overscan"               : get_attr_safe(cam_shape, "overscan"),
        # Clip
        "nearClipPlane"          : get_attr_safe(cam_shape, "nearClipPlane"),
        "farClipPlane"           : get_attr_safe(cam_shape, "farClipPlane"),
        # Pan zoom
        "panZoomEnabled"         : get_attr_safe(cam_shape, "panZoomEnabled"),
        "zoom"                   : get_attr_safe(cam_shape, "zoom"),
        "horizontalPan"          : get_attr_safe(cam_shape, "horizontalPan"),
        "verticalPan"            : get_attr_safe(cam_shape, "verticalPan"),
        # Renderable
        "renderable"             : get_attr_safe(cam_shape, "renderable"),
    }

# ────────────────────────────────────────────────────────
def process_shot(shotcode):
    seq = shotcode.split("_")[1]

    print(f"\n{'='*60}")
    print(f"  SHOT: {shotcode}")
    print(f"{'='*60}")

    # ── Open scene ──
    scene_path = (PROJECT_ROOT
        / f"shots/{seq}/{shotcode}/maya/lighting/work"
        / f"MSL_{shotcode}_light_v01.mb")

    if not scene_path.exists():
        print(f"  [ERROR] Scene not found: {scene_path}")
        return False

    print(f"  Opening: {scene_path}")
    cmds.file(str(scene_path), open=True, force=True)
    print(f"  [OK] Opened")

    # ── Camera ──
    try:
        cam_transform, cam_shape = find_render_cam()
    except RuntimeError as e:
        print(f"  [ERROR] {e}")
        return False
    print(f"  [OK] Camera: {cam_transform} / {cam_shape}")

    # ── Frame range from timeline ──
    frame_start = int(cmds.playbackOptions(q=True, animationStartTime=True))
    frame_start = frame_end
    # frame_end   = int(cmds.playbackOptions(q=True, animationEndTime=True))
    print(f"  [OK] Frames: {frame_start} - {frame_end}")

    # ── Collect all settings ──
    render_settings = collect_render_settings()
    camera_settings = collect_camera_settings(cam_transform, cam_shape)

    # ── Render layers ──
    render_layers = [
        l for l in cmds.ls(type="renderLayer")
        if not l.startswith("defaultRenderLayer")
    ]
    print(f"  [OK] Layers: {render_layers}")

    # ── References ──
    refs = []
    for ref_node in cmds.ls(type="reference"):
        try:
            refs.append({
                "namespace": cmds.referenceQuery(ref_node, namespace=True),
                "path"     : cmds.referenceQuery(ref_node, filename=True),
            })
        except Exception:
            pass

    # ── Output dirs ──
    auto_dir = PROJECT_ROOT / f"shots/{seq}/{shotcode}/maya/lighting/auto/v001"
    data_dir = auto_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # ── Export camera .abc ──
    abc_path = str(data_dir / "camRender.abc").replace("\\", "/")
    try:
        cmds.select(cam_transform, replace=True)
        mel.eval(
            f'AbcExport -j "-frameRange {frame_start} {frame_end} '
            f'-dataFormat ogawa -root {cam_transform} -file \\"{abc_path}\\"";'
        )
        print(f"  [OK] camRender.abc → {abc_path}")
    except Exception as e:
        print(f"  [ERROR] AbcExport: {e}")
        return False

    # ── Write JSON ──
    settings = {
        "shotcode"       : shotcode,
        "seq"            : seq,
        "renderCamera"   : cam_transform,
        "frameRange"     : {"start": frame_start, "end": frame_end},
        "renderSettings" : render_settings,
        "cameraSettings" : camera_settings,
        "renderLayers"   : render_layers,
        "camAbcPath"     : abc_path,
        "references"     : refs,
    }

    json_path = data_dir / "shot_setting.json"
    with open(json_path, "w") as f:
        json.dump(settings, f, indent=2)
    print(f"  [OK] shot_setting.json → {json_path}")

    # ── Print summary ──
    rs = render_settings
    cs = camera_settings
    print(f"  --- Render Settings ---")
    print(f"      Resolution : {rs['width']} x {rs['height']}")
    print(f"      Aspect     : device={rs['deviceAspectRatio']}  pixel={rs['pixelAspect']}")
    print(f"      Renderer   : {rs['currentRenderer']}")
    print(f"  --- Camera Settings ---")
    print(f"      focalLength            : {cs['focalLength']}")
    print(f"      filmAperture H/V       : {cs['horizontalFilmAperture']} / {cs['verticalFilmAperture']}")
    print(f"      lensSqueezeRatio       : {cs['lensSqueezeRatio']}")
    print(f"      filmFit                : {cs['filmFit']}")
    print(f"      overscan               : {cs['overscan']}")
    print(f"      nearClip / farClip     : {cs['nearClipPlane']} / {cs['farClipPlane']}")
    print(f"      displayResolution      : {cs['displayResolution']}")
    print(f"      panZoom / zoom         : {cs['panZoomEnabled']} / {cs['zoom']}")

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

# mayapy step1_export_shot.py --shotcodes 101_0280_0060 101_0280_0080

# :: 或指定 project root
# mayapy step1_export_shot.py --shotcodes 101_0280_0060 --project X:/projects/2508_MASHLE

# "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" "W:\vy\efx\MSL_batch_Arena\step1_export_shot.py" --shotcodes 101_0280_0060

