"""
STEP 3 - submit all render layers to Deadline
Usage (commandline): mayapy step3_submit_deadline.py --shotcodes 101_0320_0020
Usage (Maya Script Editor): 設定 SHOTCODES 後直接執行
"""

import os, sys, json, subprocess, tempfile, re
from pathlib import Path
from datetime import datetime

# ══════════════════════════════════════════════
SHOTCODES    = ["101_0320_0020"]
PROJECT_ROOT = Path("X:/projects/2508_MASHLE")
DEADLINE_CMD = Path(r"C:\Program Files\Thinkbox\Deadline10\bin\deadlinecommand.exe")
OCIO_CONFIG  = "X:/projects/2508_MASHLE/assets/OCIO/MSL_OCIOv2.1_ACESv1.3_v001.ocio"
RENDER_LAYERS = [
    "rs_Arena_bty",
    "rs_Arena_data",
    "rs_Arena_effect_light",
    "rs_Arena_fog_light",
    "rs_Arena_crypto",
]
MAYA_SUBDIR = "auto"
MAYA_VERSION_DIR = "v001"
RENDER_SUBDIR = "lighting"
RENDER_VERSION_SUFFIX = ""
RENDER_VERSION_PADDING = 2
SHOT_SETTINGS_FILENAME = "shot_setting.json"
SUBMIT_INFO_FILENAME = "submit_info.json"
# ══════════════════════════════════════════════

def _parse_args():
    global SHOTCODES, PROJECT_ROOT
    global MAYA_SUBDIR, MAYA_VERSION_DIR, RENDER_SUBDIR
    global RENDER_VERSION_SUFFIX, RENDER_VERSION_PADDING
    global SHOT_SETTINGS_FILENAME, SUBMIT_INFO_FILENAME
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--shotcodes", nargs="+", required=True)
    parser.add_argument("--project",   default=str(PROJECT_ROOT))
    parser.add_argument("--maya-subdir", default=MAYA_SUBDIR)
    parser.add_argument("--maya-version-dir", default=MAYA_VERSION_DIR)
    parser.add_argument("--render-subdir", default=RENDER_SUBDIR)
    parser.add_argument("--render-version-suffix", default=RENDER_VERSION_SUFFIX)
    parser.add_argument("--render-version-padding", type=int, default=RENDER_VERSION_PADDING)
    parser.add_argument("--render-version-no-suffix", action="store_true")
    parser.add_argument("--shot-settings-filename", default=SHOT_SETTINGS_FILENAME)
    parser.add_argument("--submit-info-filename", default=SUBMIT_INFO_FILENAME)
    args, _ = parser.parse_known_args()
    SHOTCODES    = args.shotcodes
    PROJECT_ROOT = Path(args.project)
    MAYA_SUBDIR = args.maya_subdir
    MAYA_VERSION_DIR = args.maya_version_dir
    RENDER_SUBDIR = args.render_subdir
    RENDER_VERSION_SUFFIX = "" if args.render_version_no_suffix else args.render_version_suffix
    RENDER_VERSION_PADDING = args.render_version_padding
    SHOT_SETTINGS_FILENAME = args.shot_settings_filename
    SUBMIT_INFO_FILENAME = args.submit_info_filename

if len(sys.argv) > 1:
    try:
        _parse_args()
    except Exception:
        pass

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


def build_render_root(project_root, seq, shotcode, render_subdir):
    render_root = project_root / f"shots/{seq}/{shotcode}/images/3d_renders"
    subdir = clean_optional_subdir(render_subdir)
    if str(subdir) not in {"", "."}:
        render_root = render_root / subdir
    return render_root


def load_json(shotcode):
    seq       = shotcode.split("_")[1]
    json_path = build_auto_dir(PROJECT_ROOT, seq, shotcode, MAYA_SUBDIR, MAYA_VERSION_DIR) / "data" / SHOT_SETTINGS_FILENAME
    if not json_path.exists():
        raise FileNotFoundError(f"Run Step 1+2 first:\n  {json_path}")
    with open(json_path) as f:
        return json.load(f)

def write_ini(path, data):
    with open(path, "w") as f:
        for k, v in data.items():
            f.write(f"{k}={v}\n")

def find_next_version(project_root, seq, shotcode):
    """
    掃描 images/3d_renders/lighting/ 下現有版本
    找最大 vXX 號，回傳下一個 vXX_auto
    例：現有 v03 → 回傳 "v04_auto"
    """
    lighting_dir = build_render_root(project_root, seq, shotcode, RENDER_SUBDIR)

    if not lighting_dir.exists():
        return f"v{1:0{RENDER_VERSION_PADDING}d}{RENDER_VERSION_SUFFIX}"

    max_ver = 0
    for d in lighting_dir.iterdir():
        if not d.is_dir():
            continue
        m = re.match(r"v(\d+)", d.name)
        if m:
            ver = int(m.group(1))
            if ver > max_ver:
                max_ver = ver

    next_ver = max_ver + 1
    return f"v{next_ver:0{RENDER_VERSION_PADDING}d}{RENDER_VERSION_SUFFIX}"

# ────────────────────────────────────────────────────────
def submit_layer(layer, shotcode, seq, settings, auto_scene,
                 batch_name, output_root, tmp_dir, idx):

    render_cam   = settings["importedCam"]
    rf           = settings["renderFrameRange"]
    render_start = rf["start"]
    render_end   = rf["end"]
    is_animated  = settings.get("cameraAnimated", False)
    anim_reason  = settings.get("cameraAnimReason", "")

    layer_short  = layer.replace("rs_", "")
    frames_str   = f"{render_start}-{render_end}"

    project_path = PROJECT_ROOT / f"shots/{seq}/{shotcode}/maya"

    # ── job_info ──
    job_info = {
        "BatchName"                 : batch_name,
        "Plugin"                    : "MayaBatch",
        "Name"                      : f"{batch_name} - {layer} - {render_cam}",
        "Pool"                      : "maya_2025_msl",
        "SecondaryPool"             : "maya_2025_msl",
        "Priority"                  : "10" if is_animated else "30",
        "Frames"                    : frames_str,
        "ChunkSize"                 : "5",
        "ExtraInfo0"                : "2508_MASHLE",
        "OutputDirectory0"          : str(output_root).replace("/", "\\"),
        "OutputFilename0"           : f"{layer_short}.####.exr",
        "UserName"                  : os.getenv("USERNAME", "solvfx"),
        "OverrideTaskExtraInfoNames": "False",
        "Comment"                   : "cam:Moving" if is_animated else f"cam:{anim_reason}",
    }

    # ── plugin_info ──
    plugin_info = {
        "Version"                 : "2025",
        "Renderer"                : "arnold",
        "Camera"                  : render_cam,
        "Camera0"                 : "",
        "Camera1"                 : render_cam,
        "CountRenderableCameras"  : "0",
        "Animation"               : "1",
        "Build"                   : "64bit",
        "ImageWidth"              : str(settings["renderSettings"].get("width",  2700)),
        "ImageHeight"             : str(settings["renderSettings"].get("height", 1800)),
        "SceneFile"               : auto_scene.replace("/", "\\"),
        "ProjectPath"             : str(project_path).replace("/", "\\"),
        "OutputFilePath"          : str(output_root).replace("/", "\\"),
        "OutputFilePrefix"        : "<RenderLayer>/<RenderLayer>",
        "RenderLayer"             : layer,
        "UsingRenderLayers"       : "1",
        "UseLegacyRenderLayers"   : "0",
        "RenderSetupIncludeLights": "0",
        "MayaToArnoldVersion"     : "5",
        "ArnoldVerbose"           : "2",
        "EnableOpenColorIO"       : "1",
        "OCIOConfigFile"          : OCIO_CONFIG,
        "OCIOPolicyFile"          : "",
        "StrictErrorChecking"     : "0",
        "MaxProcessors"           : "0",
        "LocalRendering"          : "0",
        "UseLocalAssetCaching"    : "0",
        "RenderHalfFrames"        : "0",
        "FrameNumberOffset"       : "0",
        "IgnoreError211"          : "0",
        "StartupScript"           : "",
    }

    job_file    = tmp_dir / f"job_{idx:02d}_{layer}.job"
    plugin_file = tmp_dir / f"plugin_{idx:02d}_{layer}.job"
    write_ini(job_file,    job_info)
    write_ini(plugin_file, plugin_info)

    result = subprocess.run(
        [str(DEADLINE_CMD), str(job_file), str(plugin_file)],
        capture_output=True, text=True
    )

    ok     = result.returncode == 0
    job_id = result.stdout.strip()

    submit_tag = "  [SUBMIT RANGE]" if is_animated else ""
    print(f"  [{'OK' if ok else 'ERROR'}] {layer:35s} frames={frames_str}{submit_tag}")
    print(f"         output -> {output_root}")
    if job_id:
        print(f"         jobId  -> {job_id}")
    if not ok:
        print(f"         STDERR: {result.stderr.strip()}")

    return {
        "layer"      : layer,
        "layerShort" : layer_short,
        "frames"     : frames_str,
        "outputRoot" : str(output_root).replace("/", "\\"),
        "outputFile" : f"{layer_short}.####.exr",
        "jobId"      : job_id,
        "success"    : ok,
        "stderr"     : result.stderr.strip() if not ok else "",
    }

# ────────────────────────────────────────────────────────
def process_shot(shotcode):
    seq = shotcode.split("_")[1]

    print(f"\n{'='*60}")
    print(f"  SHOT: {shotcode}")
    print(f"{'='*60}")

    try:
        settings = load_json(shotcode)
    except FileNotFoundError as e:
        print(f"  [ERROR] {e}")
        return False

    auto_scene    = settings.get("autoScene")
    render_cam    = settings.get("importedCam")
    rf            = settings["renderFrameRange"]
    is_animated   = settings.get("cameraAnimated", False)
    anim_reason   = settings.get("cameraAnimReason", "")
    # renderLayers 來自 step2 掃描 Arena scene（含 Arena_shadow 等）
    # fallback 到 hardcoded RENDER_LAYERS 以防舊 JSON 沒有此欄位
    render_layers = settings.get("renderLayers") or RENDER_LAYERS

    # ── Validate ──
    if not auto_scene:
        print(f"  [ERROR] autoScene not in JSON -> run Step 2 first")
        return False
    if not Path(auto_scene).exists():
        print(f"  [ERROR] auto scene not found: {auto_scene}")
        return False
    if not render_cam:
        print(f"  [ERROR] importedCam not in JSON -> run Step 2 first")
        return False
    if not DEADLINE_CMD.exists():
        print(f"  [ERROR] deadlinecommand not found: {DEADLINE_CMD}")
        return False

    scene_name = Path(auto_scene).stem
    variant_label = (optional_subdir_text(RENDER_SUBDIR) or optional_subdir_text(MAYA_SUBDIR)).replace("\\", "_").replace("/", "_")
    batch_name = f"{scene_name}_{variant_label}" if variant_label and variant_label != "lighting" else scene_name

    # ── Auto version ──
    next_ver   = find_next_version(PROJECT_ROOT, seq, shotcode)
    output_root = build_render_root(PROJECT_ROOT, seq, shotcode, RENDER_SUBDIR) / next_ver
    output_root.mkdir(parents=True, exist_ok=True)

    submit_tag = "  *** [SUBMIT RANGE] ***" if is_animated else "  (static cam)"
    print(f"  BatchName : {batch_name}")
    print(f"  Camera    : {render_cam}")
    print(f"  Frames    : {rf['start']} - {rf['end']}{submit_tag}")
    print(f"  Animated  : {is_animated} ({anim_reason})")
    print(f"  Layers    : {len(render_layers)}  {render_layers}")
    print(f"  Output ver: {next_ver}")
    print(f"  Output    : {output_root}")
    if not is_animated:
        print(f"  [INFO] Static camera -> single frame {rf['start']}")

    tmp_dir     = Path(tempfile.mkdtemp(prefix=f"msl_{shotcode}_"))
    layer_infos = []

    for idx, layer in enumerate(render_layers):
        info = submit_layer(
            layer, shotcode, seq, settings,
            auto_scene, batch_name, output_root, tmp_dir, idx
        )
        layer_infos.append(info)

    success = sum(1 for i in layer_infos if i["success"])
    print(f"\n  Submitted: {success}/{len(render_layers)} layers")

    # ── Write submit_info.json ──
    submit_info = {
        "shotcode"        : shotcode,
        "batchName"       : batch_name,
        "sceneFile"       : auto_scene,
        "camera"          : render_cam,
        "cameraAnimated"  : is_animated,
        "cameraReason"    : anim_reason,
        "frameRange"      : settings["frameRange"],
        "renderFrameRange": rf,
        "mayaSubdir"      : optional_subdir_text(MAYA_SUBDIR),
        "mayaVersionDir"  : MAYA_VERSION_DIR,
        "renderSubdir"    : optional_subdir_text(RENDER_SUBDIR),
        "outputVersion"   : next_ver,
        "outputRoot"      : str(output_root).replace("/", "\\"),
        "submittedBy"     : os.getenv("USERNAME", "solvfx"),
        "submittedAt"     : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "deadlineCmd"     : str(DEADLINE_CMD),
        "layers"          : layer_infos,
        "totalLayers"     : len(render_layers),
        "successLayers"   : success,
    }

    data_dir = build_auto_dir(PROJECT_ROOT, seq, shotcode, MAYA_SUBDIR, MAYA_VERSION_DIR) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    submit_path = data_dir / SUBMIT_INFO_FILENAME
    with open(submit_path, "w") as f:
        json.dump(submit_info, f, indent=2)
    print(f"  [OK] submit_info.json -> {submit_path}")

    return success == len(render_layers)

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
