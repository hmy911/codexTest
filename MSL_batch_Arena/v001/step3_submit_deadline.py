"""
Step 3: Submit all render layers as one Deadline batch
Usage: python step3_submit_deadline.py --shotcode 101_0280_0060
"""

import os, json, argparse, subprocess, tempfile
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path("X:/projects/2508_MASHLE")
DEADLINE_CMD = Path(r"C:\Program Files\Thinkbox\Deadline10\bin\deadlinecommand.exe")
OCIO_CONFIG  = "X:/projects/2508_MASHLE/assets/OCIO/MSL_OCIOv2.1_ACESv1.3_v001.ocio"

# ── Arena render layers（固定，和 Arena 場景一致）──
RENDER_LAYERS = [
    "rs_Arena_bty",
    "rs_Arena_data",
    "rs_Arena_effect_light",
    "rs_Arena_fog_light",
    "rs_Arena_crypto",
]

def load_settings(shotcode):
    seq       = shotcode.split("_")[1]
    json_path = (PROJECT_ROOT
        / f"shots/{seq}/{shotcode}/maya/lighting/auto/v001/data/shot_setting.json")
    if not json_path.exists():
        raise FileNotFoundError(f"Run step1+2 first:\n  {json_path}")
    with open(json_path) as f:
        return json.load(f)

def write_ini(path, data):
    with open(path, "w") as f:
        for k, v in data.items():
            f.write(f"{k}={v}\n")

def submit_one_layer(layer_name, shotcode, seq, settings,
                     auto_scene, batch_name, tmp_dir, idx):
    """Submit 單一 render layer，回傳 job id"""

    render_cam  = settings["importedCam"]
    frame_start = settings["frameRange"]["start"]
    frame_end   = settings["frameRange"]["end"]
    scene_name  = Path(auto_scene).stem   # MSL_101_0280_0060_light_v002_auto

    # layer short name（rs_Arena_bty → Arena_bty）
    layer_short = layer_name.replace("rs_", "")

    # Output paths（完全對應真實結構）
    output_base = (PROJECT_ROOT
        / f"shots/{seq}/{shotcode}/maya/3d_data/workingImages"
        / scene_name / layer_short)
    output_base.mkdir(parents=True, exist_ok=True)

    project_path = PROJECT_ROOT / f"shots/{seq}/{shotcode}/maya"

    output_win   = str(output_base).replace("/", "\\")
    scene_win    = auto_scene.replace("/", "\\")
    project_win  = str(project_path).replace("/", "\\")
    # OutputFilePath → workingImages/ (帶尾斜線)
    output_file_path_win = str(
        PROJECT_ROOT / f"shots/{seq}/{shotcode}/maya/3d_data/workingImages/"
    ).replace("/", "\\")

    job_info = {
        "BatchName"                 : batch_name,
        "Plugin"                    : "MayaBatch",
        "Name"                      : f"{batch_name} - {layer_name} - {render_cam}",
        "Pool"                      : "maya_2025_msl",
        "SecondaryPool"             : "maya_2025_msl",
        "Priority"                  : "60",
        "Frames"                    : f"{frame_start}-{frame_end}",
        "ExtraInfo0"                : "2508_MASHLE",
        "OutputDirectory0"          : output_win,
        "OutputFilename0"           : f"{layer_short}.####.exr",
        "UserName"                  : os.getenv("USERNAME", "solvfx"),
        "OverrideTaskExtraInfoNames": "False",
    }

    plugin_info = {
        "Version"                : "2025",
        "Renderer"               : "arnold",
        "Camera"                 : render_cam,
        "Camera0"                : "",
        "Camera1"                : render_cam,
        "CountRenderableCameras" : "0",
        "Animation"              : "1",
        "Build"                  : "64bit",
        "ImageWidth"             : "2700",
        "ImageHeight"            : "1800",
        "SceneFile"              : scene_win,
        "ProjectPath"            : project_win,
        "OutputFilePath"         : output_file_path_win,
        "OutputFilePrefix"       : "<Scene>/<RenderLayer>/<RenderLayer>",
        "RenderLayer"            : layer_name,
        "UsingRenderLayers"      : "1",
        "UseLegacyRenderLayers"  : "0",
        "RenderSetupIncludeLights": "0",
        "MayaToArnoldVersion"    : "5",
        "ArnoldVerbose"          : "2",
        "EnableOpenColorIO"      : "1",
        "OCIOConfigFile"         : OCIO_CONFIG,
        "OCIOPolicyFile"         : "",
        "StrictErrorChecking"    : "0",
        "MaxProcessors"          : "0",
        "LocalRendering"         : "0",
        "UseLocalAssetCaching"   : "0",
        "RenderHalfFrames"       : "0",
        "FrameNumberOffset"      : "0",
        "IgnoreError211"         : "0",
        "StartupScript"          : "",
    }

    job_file    = tmp_dir / f"job_{idx:02d}_{layer_name}.job"
    plugin_file = tmp_dir / f"plugin_{idx:02d}_{layer_name}.job"
    write_ini(job_file, job_info)
    write_ini(plugin_file, plugin_info)

    result = subprocess.run(
        [str(DEADLINE_CMD), str(job_file), str(plugin_file)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Deadline submission failed [{layer_name}]:\n{result.stderr}"
        )
    print(f"[OK] Submitted: {layer_name}")
    print(f"     {result.stdout.strip()}")
    return result.stdout.strip()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shotcode", required=True)
    args = parser.parse_args()

    shotcode = args.shotcode
    seq      = shotcode.split("_")[1]
    settings = load_settings(shotcode)

    auto_scene  = settings["autoScene"]
    render_cam  = settings["importedCam"]
    scene_name  = Path(auto_scene).stem   # MSL_101_0280_0060_light_v002_auto
    batch_name  = scene_name              # BatchName = scene stem（和範例一致）

    if not DEADLINE_CMD.exists():
        raise FileNotFoundError(f"deadlinecommand not found:\n  {DEADLINE_CMD}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="msl_deadline_"))

    print(f"\n=== MSL Arena Submit: {shotcode} ===")
    print(f"    BatchName : {batch_name}")
    print(f"    Camera    : {render_cam}")
    print(f"    Frames    : {settings['frameRange']['start']}-{settings['frameRange']['end']}")
    print(f"    Layers    : {RENDER_LAYERS}\n")

    job_ids = []
    for idx, layer in enumerate(RENDER_LAYERS):
        job_id = submit_one_layer(
            layer, shotcode, seq, settings,
            auto_scene, batch_name, tmp_dir, idx
        )
        job_ids.append((layer, job_id))

    print(f"\n=== All {len(RENDER_LAYERS)} jobs submitted ===")
    for layer, jid in job_ids:
        print(f"  {layer:30s} → {jid}")

if __name__ == "__main__":
    main()