"""
STEP 1 - export camera abc + full settings JSON
Usage (commandline): mayapy step1_export_shot.py --shotcodes 101_0280_0060 101_0280_0080
Usage (Maya Script Editor): 設定 SHOTCODES 後直接執行
"""

import os, sys, json
from pathlib import Path

# ══════════════════════════════════════════════
SHOTCODES    = ["101_036A_0020"]
PROJECT_ROOT = Path("X:/projects/2508_MASHLE")
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
    global SHOTCODES, PROJECT_ROOT
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--shotcodes", nargs="+", required=True)
    parser.add_argument("--project",   default=str(PROJECT_ROOT))
    args, _ = parser.parse_known_args()
    SHOTCODES    = args.shotcodes
    PROJECT_ROOT = Path(args.project)

if _IS_CMD:
    _parse_args()

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
def find_scene_path(project_root, seq, shotcode):
    """
    自動搜尋 lighting work 目錄下的 .mb
    支援多種命名格式，有多個版本時取最新
    """
    work_dir = project_root / f"shots/{seq}/{shotcode}/maya/lighting/work"

    if not work_dir.exists():
        raise FileNotFoundError(f"Work dir not found:\n  {work_dir}")

    mb_files = list(work_dir.glob("*.mb"))
    if not mb_files:
        raise FileNotFoundError(f"No .mb files in:\n  {work_dir}")

    candidates = [f for f in mb_files if shotcode in f.name]
    if not candidates:
        raise FileNotFoundError(
            f"No .mb matching '{shotcode}' in:\n  {work_dir}\n"
            f"  Found: {[f.name for f in mb_files]}"
        )

    candidates.sort()
    return candidates[-1]

def find_render_cam():
    """
    回傳 (cam_full, cam_transform, cam_shape)
    cam_full      = 完整 DAG 路徑（用於 AbcExport -root，避免同名衝突）
    cam_transform = 短名稱（用於 Deadline Camera 欄位）
    cam_shape     = shape 節點名稱
    """
    defaults = {"persp", "top", "front", "side", "camera_turntable"}
    all_cams = []

    for cam_shape in cmds.ls(type="camera"):
        parents = cmds.listRelatives(cam_shape, parent=True, fullPath=True)
        if not parents:
            continue
        cam_full = parents[0]                          # 完整 DAG
        cam_name = cam_full.split("|")[-1]             # 短名稱
        base_name = cam_name.split(":")[-1]
        if base_name in defaults or base_name.startswith("pasted__"):
            continue
        all_cams.append((cam_full, cam_name, cam_shape))

    # 優先 renderable=True
    for full, name, shape in all_cams:
        if cmds.getAttr(f"{shape}.renderable"):
            cmds.setAttr(f"{shape}.renderable", 1)
            print(f"  [OK] Renderable cam: {name}")
            return full, name, shape

    # fallback: MainCam
    for full, name, shape in all_cams:
        if "MainCam" in name or "mainCam" in name.lower():
            cmds.setAttr(f"{shape}.renderable", 1)
            print(f"  [WARN] renderable=False, using MainCam: {name}")
            return full, name, shape

    # fallback: 唯一非預設 cam
    if len(all_cams) == 1:
        full, name, shape = all_cams[0]
        cmds.setAttr(f"{shape}.renderable", 1)
        print(f"  [WARN] only one cam, using: {name}")
        return full, name, shape

    raise RuntimeError(
        f"Cannot find render cam.\n"
        f"  Candidates: {[(n, s) for _, n, s in all_cams]}"
    )

def check_camera_animated(cam_transform):
    """
    回傳 (is_animated: bool, reason: str)
    檢查 translate + rotate 六個 channel
    """
    attrs = ["translateX","translateY","translateZ",
             "rotateX",   "rotateY",   "rotateZ"]
    all_keys = []
    all_vals = []
    for attr in attrs:
        keys = cmds.keyframe(cam_transform, attribute=attr,
                             query=True, timeChange=True)  or []
        vals = cmds.keyframe(cam_transform, attribute=attr,
                             query=True, valueChange=True) or []
        all_keys.extend(keys)
        all_vals.extend(vals)

    if not all_keys:
        return False, "no_keyframes"
    if len(all_keys) == 1:
        return False, "single_keyframe"
    if len(set(round(v, 6) for v in all_vals)) == 1:
        return False, "all_keyframes_identical"
    return True, "animated"

def get_attr_safe(node, attr, default=None):
    try:
        return cmds.getAttr(f"{node}.{attr}")
    except Exception:
        return default

def collect_render_settings():
    rg  = "defaultRenderGlobals"
    res = "defaultResolution"
    return {
        "width"             : get_attr_safe(res, "width"),
        "height"            : get_attr_safe(res, "height"),
        "deviceAspectRatio" : get_attr_safe(res, "deviceAspectRatio"),
        "pixelAspect"       : get_attr_safe(res, "pixelAspect"),
        "dotsPerInch"       : get_attr_safe(res, "dotsPerInch"),
        "startFrame"        : get_attr_safe(rg,  "startFrame"),
        "endFrame"          : get_attr_safe(rg,  "endFrame"),
        "byFrame"           : get_attr_safe(rg,  "byFrameStep"),
        "imageFormat"       : get_attr_safe(rg,  "imageFormat"),
        "animation"         : get_attr_safe(rg,  "animation"),
        "extensionPadding"  : get_attr_safe(rg,  "extensionPadding"),
        "outFormatControl"  : get_attr_safe(rg,  "outFormatControl"),
        "putFrameBeforeExt" : get_attr_safe(rg,  "putFrameBeforeExt"),
        "periodInExt"       : get_attr_safe(rg,  "periodInExt"),
        "currentRenderer"   : get_attr_safe(rg,  "currentRenderer"),
        "renderAll"         : get_attr_safe(rg,  "renderAll"),
    }

def collect_camera_settings(cam_shape):
    return {
        "focalLength"            : get_attr_safe(cam_shape, "focalLength"),
        "horizontalFilmAperture" : get_attr_safe(cam_shape, "horizontalFilmAperture"),
        "verticalFilmAperture"   : get_attr_safe(cam_shape, "verticalFilmAperture"),
        "lensSqueezeRatio"       : get_attr_safe(cam_shape, "lensSqueezeRatio"),
        "filmFit"                : get_attr_safe(cam_shape, "filmFit"),
        "filmFitOffset"          : get_attr_safe(cam_shape, "filmFitOffset"),
        "horizontalFilmOffset"   : get_attr_safe(cam_shape, "horizontalFilmOffset"),
        "verticalFilmOffset"     : get_attr_safe(cam_shape, "verticalFilmOffset"),
        "displayResolution"      : get_attr_safe(cam_shape, "displayResolution"),
        "displayGateMask"        : get_attr_safe(cam_shape, "displayGateMask"),
        "displayGateMaskOpacity" : get_attr_safe(cam_shape, "displayGateMaskOpacity"),
        "overscan"               : get_attr_safe(cam_shape, "overscan"),
        "nearClipPlane"          : get_attr_safe(cam_shape, "nearClipPlane"),
        "farClipPlane"           : get_attr_safe(cam_shape, "farClipPlane"),
        "panZoomEnabled"         : get_attr_safe(cam_shape, "panZoomEnabled"),
        "zoom"                   : get_attr_safe(cam_shape, "zoom"),
        "horizontalPan"          : get_attr_safe(cam_shape, "horizontalPan"),
        "verticalPan"            : get_attr_safe(cam_shape, "verticalPan"),
        "renderable"             : get_attr_safe(cam_shape, "renderable"),
    }

# ────────────────────────────────────────────────────────
def process_shot(shotcode):
    seq = shotcode.split("_")[1]

    print(f"\n{'='*60}")
    print(f"  SHOT: {shotcode}")
    print(f"{'='*60}")

    # ── Find + open scene ──
    try:
        scene_path = find_scene_path(PROJECT_ROOT, seq, shotcode)
    except FileNotFoundError as e:
        print(f"  [ERROR] {e}")
        return False

    print(f"  Scene  : {scene_path.name}")
    print(f"  Opening: {scene_path}")
    cmds.file(str(scene_path), open=True, force=True)
    print(f"  [OK] Opened")

    # ── Camera ──
    try:
        cam_full, cam_transform, cam_shape = find_render_cam()
    except RuntimeError as e:
        print(f"  [ERROR] {e}")
        return False
    print(f"  [OK] Camera : {cam_transform}")
    print(f"       Shape  : {cam_shape}")
    print(f"       DAG    : {cam_full}")

    # ── Frame range ──
    frame_start = int(cmds.playbackOptions(q=True, animationStartTime=True))
    frame_end   = int(cmds.playbackOptions(q=True, animationEndTime=True))
    print(f"  [OK] Timeline: {frame_start} - {frame_end}")

    # ── Camera animated check（用短名稱）──
    is_animated, anim_reason = check_camera_animated(cam_transform)
    if is_animated:
        render_start = frame_start
        render_end   = frame_end
        print(f"  [OK] Camera animated → render {render_start}-{render_end}")
    else:
        render_start = frame_start
        render_end   = frame_start
        print(f"  [WARN] Camera static ({anim_reason}) → single frame {render_start}")

    # ── Collect settings ──
    render_settings = collect_render_settings()
    camera_settings = collect_camera_settings(cam_shape)
    camera_settings["transform"] = cam_transform
    camera_settings["shape"]     = cam_shape
    camera_settings["dagPath"]   = cam_full

    render_layers = [
        l for l in cmds.ls(type="renderLayer")
        if not l.startswith("defaultRenderLayer")
    ]
    print(f"  [OK] Layers: {render_layers}")

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

    # ── Export camera .abc（用完整 DAG 路徑）──
    abc_path = str(data_dir / "camRender.abc").replace("\\", "/")
    try:
        cmds.select(cam_full, replace=True)
        mel.eval(
            f'AbcExport -j "-frameRange {frame_start} {frame_end} '
            f'-dataFormat ogawa '
            f'-worldSpace '
            f'-root {cam_full} '
            f'-file \\"{abc_path}\\"";'
        )
        print(f"  [OK] camRender.abc → {abc_path}")
    except Exception as e:
        print(f"  [ERROR] AbcExport: {e}")
        return False

    # ── Write JSON ──
    settings = {
        "shotcode"        : shotcode,
        "seq"             : seq,
        "sourceScene"     : str(scene_path).replace("\\", "/"),
        "renderCamera"    : cam_transform,   # 短名稱 → Deadline Camera 欄位
        "renderCameraFull": cam_full,        # 完整 DAG → 備用
        "frameRange"      : {"start": frame_start,  "end": frame_end},
        "renderFrameRange": {"start": render_start,  "end": render_end},
        "cameraAnimated"  : is_animated,
        "cameraAnimReason": anim_reason,
        "renderSettings"  : render_settings,
        "cameraSettings"  : camera_settings,
        "renderLayers"    : render_layers,
        "camAbcPath"      : abc_path,
        "references"      : refs,
    }

    json_path = data_dir / "shot_setting.json"
    with open(json_path, "w") as f:
        json.dump(settings, f, indent=2)
    print(f"  [OK] shot_setting.json → {json_path}")

    rs = render_settings
    cs = camera_settings
    print(f"  --- Render ---")
    print(f"      Resolution  : {rs['width']} x {rs['height']}")
    print(f"      Aspect      : device={rs['deviceAspectRatio']}  pixel={rs['pixelAspect']}")
    print(f"      Submit range: {render_start} - {render_end}")
    print(f"  --- Camera ---")
    print(f"      animated    : {is_animated} ({anim_reason})")
    print(f"      focalLength : {cs['focalLength']}")
    print(f"      aperture H/V: {cs['horizontalFilmAperture']} / {cs['verticalFilmAperture']}")
    print(f"      overscan    : {cs['overscan']}")

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
    