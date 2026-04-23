# ============================================================
# STEP 1 - multi shot, with open file
# Maya Script Editor → Python tab
# ============================================================

import json
from pathlib import Path
import maya.cmds as cmds
import maya.mel as mel

# ── 改這裡：輸入多個 shotcode ────────────────────
SHOTCODES    = ["101_0280_0060"]
# SHOTCODES    = ["101_0280_0060", "101_0280_0070"]
PROJECT_ROOT = Path("X:/projects/2508_MASHLE")
# ────────────────────────────────────────────────

# ── Load plugins ──
for plugin in ["AbcExport", "AbcImport"]:
    if not cmds.pluginInfo(plugin, query=True, loaded=True):
        try:
            cmds.loadPlugin(plugin)
            print(f"[OK] Loaded: {plugin}")
        except Exception as e:
            print(f"[WARN] {plugin}: {e}")

def find_render_cam():
    defaults = {"persp", "top", "front", "side", "camera_turntable"}
    all_cams = []
    for cam_shape in cmds.ls(type="camera"):
        parents = cmds.listRelatives(cam_shape, parent=True)
        if not parents:
            continue
        cam_transform = parents[0]
        base_name = cam_transform.split(":")[-1]
        if base_name in defaults:
            continue
        if base_name.startswith("pasted__"):
            continue
        all_cams.append((cam_transform, cam_shape))

    for transform, shape in all_cams:
        if cmds.getAttr(f"{shape}.renderable"):
            cmds.setAttr(f"{shape}.renderable", 1)
            return transform
    for transform, shape in all_cams:
        if "MainCam" in transform:
            cmds.setAttr(f"{shape}.renderable", 1)
            print(f"  [WARN] renderable=False, using MainCam by name: {transform}")
            return transform
    if len(all_cams) == 1:
        transform, shape = all_cams[0]
        cmds.setAttr(f"{shape}.renderable", 1)
        print(f"  [WARN] only one cam, using: {transform}")
        return transform
    raise RuntimeError(f"Cannot find render cam. Candidates: {all_cams}")

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
        render_cam = find_render_cam()
    except RuntimeError as e:
        print(f"  [ERROR] {e}")
        return False
    print(f"  [OK] Camera: {render_cam}")

    # ── Frame range ──
    frame_start = int(cmds.playbackOptions(q=True, animationStartTime=True))
    frame_end   = frame_start
    # frame_end   = int(cmds.playbackOptions(q=True, animationEndTime=True))
    print(f"  [OK] Frames: {frame_start} - {frame_end}")

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
        cmds.select(render_cam, replace=True)
        mel.eval(
            f'AbcExport -j "-frameRange {frame_start} {frame_end} '
            f'-dataFormat ogawa -root {render_cam} -file \\"{abc_path}\\"";'
        )
        print(f"  [OK] camRender.abc → {abc_path}")
    except Exception as e:
        print(f"  [ERROR] AbcExport failed: {e}")
        return False

    # ── Write JSON ──
    settings = {
        "shotcode"     : shotcode,
        "seq"          : seq,
        "renderCamera" : render_cam,
        "frameRange"   : {"start": frame_start, "end": frame_end},
        "renderLayers" : render_layers,
        "camAbcPath"   : abc_path,
        "references"   : refs,
    }
    json_path = data_dir / "shot_setting.json"
    with open(json_path, "w") as f:
        json.dump(settings, f, indent=2)
    print(f"  [OK] shot_setting.json → {json_path}")

    return True

# ── Run all shots ──
results = {}
for sc in SHOTCODES:
    ok = process_shot(sc)
    results[sc] = "OK" if ok else "FAILED"

# ── Summary ──
print(f"\n{'='*60}")
print("  SUMMARY")
print(f"{'='*60}")
for sc, status in results.items():
    mark = "✓" if status == "OK" else "✗"
    print(f"  {mark} {sc} → {status}")
print()
