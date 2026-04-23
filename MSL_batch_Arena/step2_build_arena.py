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
VERSION_NOTE = ""   # ← 版本更新說明，例如 "fix rim light / add fog"
MAYA_SUBDIR = "auto"
MAYA_VERSION_DIR = "v001"
SOURCE_MAYA_SUBDIR = "auto"
SOURCE_MAYA_VERSION_DIR = "v001"
SHOT_SETTINGS_FILENAME = "shot_setting.json"
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
    global SHOTCODES, PROJECT_ROOT, ARENA_SCENE, VERSION_NOTE
    global MAYA_SUBDIR, MAYA_VERSION_DIR, SOURCE_MAYA_SUBDIR, SOURCE_MAYA_VERSION_DIR
    global SHOT_SETTINGS_FILENAME
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--shotcodes",    nargs="+", required=True)
    parser.add_argument("--project",      default=str(PROJECT_ROOT))
    parser.add_argument("--arena",        default=str(ARENA_SCENE))
    parser.add_argument("--version-note", default=VERSION_NOTE)
    parser.add_argument("--maya-subdir", default=MAYA_SUBDIR)
    parser.add_argument("--maya-version-dir", default=MAYA_VERSION_DIR)
    parser.add_argument("--source-maya-subdir", default=SOURCE_MAYA_SUBDIR)
    parser.add_argument("--source-maya-version-dir", default=SOURCE_MAYA_VERSION_DIR)
    parser.add_argument("--shot-settings-filename", default=SHOT_SETTINGS_FILENAME)
    args, _ = parser.parse_known_args()
    SHOTCODES    = args.shotcodes
    PROJECT_ROOT = Path(args.project)
    ARENA_SCENE  = Path(args.arena)
    VERSION_NOTE = args.version_note
    MAYA_SUBDIR = args.maya_subdir
    MAYA_VERSION_DIR = args.maya_version_dir
    SOURCE_MAYA_SUBDIR = args.source_maya_subdir
    SOURCE_MAYA_VERSION_DIR = args.source_maya_version_dir
    SHOT_SETTINGS_FILENAME = args.shot_settings_filename

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
def clean_optional_subdir(value):
    raw = str(value).strip().replace("\\", "/").strip("/")
    if raw in {"", "."}:
        return Path()
    return Path(*[part for part in raw.split("/") if part and part != "."])


def optional_subdir_text(value):
    text = str(clean_optional_subdir(value)).replace("\\", "/")
    return "" if text in {"", "."} else text


def build_auto_dir(project_root, seq, shotcode, maya_subdir, maya_version_dir):
    auto_root = project_root / f"shots/{seq}/{shotcode}/maya/lighting"
    subdir = clean_optional_subdir(maya_subdir)
    if str(subdir) not in {"", "."}:
        auto_root = auto_root / subdir
    return auto_root / maya_version_dir


def build_scene_name_tag(maya_subdir):
    custom1 = optional_subdir_text(maya_subdir)
    if not custom1 or custom1 == "auto":
        return "light"
    if custom1.startswith("auto_"):
        custom1 = custom1[len("auto_"):]
    return custom1


def load_json(shotcode):
    seq       = shotcode.split("_")[1]
    json_path = build_auto_dir(PROJECT_ROOT, seq, shotcode, SOURCE_MAYA_SUBDIR, SOURCE_MAYA_VERSION_DIR) / "data" / SHOT_SETTINGS_FILENAME
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
            print(f"  [WARN] setAttr {node}.{attr} = {val} -> {e}")

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

    # Playback range 對齊 renderFrameRange
    cmds.playbackOptions(
        animationStartTime=rf["start"], animationEndTime=rf["end"],
        minTime=rf["start"],            maxTime=rf["end"]
    )

    print(f"  [OK] Resolution  : {rs.get('width')} x {rs.get('height')}")
    print(f"  [OK] Render range: {rf['start']} - {rf['end']}")
    print(f"  [OK] Playback range set: {rf['start']} - {rf['end']}")

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
            print(f"  [WARN] cam {attr} = {val} -> {e}")

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
    set_safe("renderPanZoom",          cs.get("renderPanZoom"))
    set_safe("zoom",                   cs.get("zoom"))
    set_safe("horizontalPan",          cs.get("horizontalPan"))
    set_safe("verticalPan",            cs.get("verticalPan"))

    print(f"  [OK] Camera settings applied -> {cam_shape}")
    print(f"       focalLength : {cs.get('focalLength')}")
    print(f"       aperture H/V: {cs.get('horizontalFilmAperture')} / {cs.get('verticalFilmAperture')}")
    print(f"       overscan    : {cs.get('overscan')}")
    if cs.get("renderPanZoom"):
        print(f"       [2D Pan/Zoom] renderPanZoom=ON  zoom={cs.get('zoom')}  "
              f"pan=({cs.get('horizontalPan')}, {cs.get('verticalPan')})")
    elif cs.get("panZoomEnabled"):
        print(f"       [2D Pan/Zoom] panZoomEnabled=ON (renderPanZoom=OFF)  zoom={cs.get('zoom')}  "
              f"pan=({cs.get('horizontalPan')}, {cs.get('verticalPan')})")

def find_next_auto_version(auto_dir, shotcode, scene_name_tag):
    """
    掃描 auto_dir 下現有的 MSL_{shotcode}_{scene_name_tag}_v*_auto.ma
    回傳下一個版號 int 和格式化字串，例如 (3, "v003")
    沒有任何舊檔案時從 v001 開始
    """
    import re
    pattern = re.compile(
        rf"MSL_{re.escape(shotcode)}_{re.escape(scene_name_tag)}_v(\d+)_auto\.ma", re.IGNORECASE
    )
    max_ver = 0
    if auto_dir.exists():
        for f in auto_dir.glob(f"MSL_{shotcode}_{scene_name_tag}_v*_auto.ma"):
            m = pattern.match(f.name)
            if m:
                ver = int(m.group(1))
                if ver > max_ver:
                    max_ver = ver
    next_ver = max_ver + 1
    return next_ver, f"v{next_ver:03d}"

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

    # ── Collect render layers from Arena scene（包含 Arena_shadow 等額外 layer）──
    arena_layers = [
        l for l in cmds.ls(type="renderLayer")
        if not l.startswith("defaultRenderLayer")
    ]
    settings["renderLayers"] = arena_layers
    print(f"  [OK] Render layers (Arena): {arena_layers}")

    # ── Save auto scene（版號自動遞增）──
    auto_dir  = build_auto_dir(PROJECT_ROOT, seq, shotcode, MAYA_SUBDIR, MAYA_VERSION_DIR)
    auto_dir.mkdir(parents=True, exist_ok=True)
    scene_name_tag = build_scene_name_tag(MAYA_SUBDIR)
    ver_int, ver_str = find_next_auto_version(auto_dir, shotcode, scene_name_tag)
    auto_scene = auto_dir / f"MSL_{shotcode}_{scene_name_tag}_{ver_str}_auto.ma"

    cmds.file(rename=str(auto_scene).replace("\\", "/"))
    cmds.file(save=True, type="mayaAscii")
    print(f"  [OK] Saved: {auto_scene.name}  ({ver_str})")

    # ── Update JSON ──
    from datetime import datetime
    output_data_dir = auto_dir / "data"
    output_data_dir.mkdir(parents=True, exist_ok=True)
    output_json_path = output_data_dir / SHOT_SETTINGS_FILENAME

    settings["autoScene"] = str(auto_scene).replace("\\", "/")
    settings["autoSceneVer"] = ver_str
    settings["autoSceneVerInt"] = ver_int
    settings["importedCam"] = imported_cam
    settings["versionNote"] = VERSION_NOTE or ""
    settings["savedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings["arenaScene"] = str(ARENA_SCENE).replace("\\", "/")
    settings["sourceShotSettings"] = str(json_path).replace("\\", "/")
    settings["shotSettingsPath"] = str(output_json_path).replace("\\", "/")
    settings["mayaSubdir"] = optional_subdir_text(MAYA_SUBDIR)
    settings["mayaVersionDir"] = MAYA_VERSION_DIR
    settings["sceneNameTag"] = scene_name_tag
    with open(output_json_path, "w") as f:
        json.dump(settings, f, indent=2)
    print(f"  [OK] JSON updated -> {output_json_path}")
    if VERSION_NOTE:
        print(f"  [NOTE] {VERSION_NOTE}")

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
    mark = "OK" if status == "OK" else "FAIL"
    print(f"  [{mark}] {sc} -> {status}")
print()

if _IS_CMD:
    import maya.standalone as _sa
    _sa.uninitialize()
