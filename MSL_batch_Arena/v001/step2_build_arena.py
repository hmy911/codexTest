# ============================================================
# STEP 2 - multi shot, open Arena → import cam abc → save auto
# Maya Script Editor → Python tab
# ============================================================

import json
from pathlib import Path
import maya.cmds as cmds

# ── 改這裡 ──────────────────────────────────────
SHOTCODES    = ["101_0280_0060"]
# SHOTCODES    = ["101_0280_0060", "101_0280_0070"]
PROJECT_ROOT = Path("X:/projects/2508_MASHLE")
ARENA_SCENE  = (PROJECT_ROOT
    / "assets/environment/Arena/work/scenes/vincentyang"
    / "batch_Arena/Arena_Light_setC_v001.ma")
# ────────────────────────────────────────────────

# ── Load plugins ──
for plugin in ["AbcExport", "AbcImport"]:
    if not cmds.pluginInfo(plugin, query=True, loaded=True):
        try:
            cmds.loadPlugin(plugin)
            print(f"[OK] Loaded: {plugin}")
        except Exception as e:
            print(f"[WARN] {plugin}: {e}")

def process_shot(shotcode):
    seq = shotcode.split("_")[1]

    print(f"\n{'='*60}")
    print(f"  SHOT: {shotcode}")
    print(f"{'='*60}")

    # ── Load JSON ──
    json_path = (PROJECT_ROOT
        / f"shots/{seq}/{shotcode}/maya/lighting/auto/v001/data/shot_setting.json")

    if not json_path.exists():
        print(f"  [ERROR] JSON not found, run Step 1 first:\n  {json_path}")
        return False

    with open(json_path) as f:
        settings = json.load(f)

    render_cam  = settings["renderCamera"]
    frame_start = settings["frameRange"]["start"]
    frame_end   = settings["frameRange"]["end"]
    cam_abc     = settings["camAbcPath"]

    print(f"  Camera : {render_cam}")
    print(f"  Frames : {frame_start} - {frame_end}")
    print(f"  Abc    : {cam_abc}")

    if not Path(cam_abc).exists():
        print(f"  [ERROR] camRender.abc not found: {cam_abc}")
        return False

    # ── Open Arena scene ──
    if not ARENA_SCENE.exists():
        print(f"  [ERROR] Arena scene not found: {ARENA_SCENE}")
        return False

    print(f"  Opening Arena: {ARENA_SCENE}")
    cmds.file(str(ARENA_SCENE), open=True, force=True)
    print(f"  [OK] Opened Arena")

    # ── Import camera from .abc ──
    before = set(cmds.ls(dag=True, type="transform"))
    try:
        cmds.AbcImport(cam_abc, mode="import")
    except Exception as e:
        print(f"  [ERROR] AbcImport failed: {e}")
        return False

    after     = set(cmds.ls(dag=True, type="transform"))
    new_nodes = after - before
    print(f"  [OK] Imported nodes: {new_nodes}")

    # ── Find imported camera transform ──
    imported_cam = None
    for node in new_nodes:
        shapes = cmds.listRelatives(node, shapes=True, type="camera") or []
        if shapes:
            imported_cam = node
            break

    if not imported_cam:
        # fallback: 場景裡找同名
        if cmds.objExists(render_cam):
            imported_cam = render_cam
            print(f"  [WARN] cam not in new nodes, using existing: {imported_cam}")
        else:
            print(f"  [ERROR] Cannot find imported camera. New nodes: {new_nodes}")
            return False

    print(f"  [OK] Imported cam: {imported_cam}")

    # ── Set renderable ──
    for shape in cmds.ls(type="camera"):
        cmds.setAttr(f"{shape}.renderable", 0)

    cam_shapes = cmds.listRelatives(imported_cam, shapes=True, type="camera") or []
    if not cam_shapes:
        print(f"  [ERROR] No camera shape under: {imported_cam}")
        return False

    cmds.setAttr(f"{cam_shapes[0]}.renderable", 1)
    print(f"  [OK] Renderable: {cam_shapes[0]}")

    # ── Apply frame range ──
    cmds.setAttr("defaultRenderGlobals.startFrame", frame_start)
    cmds.setAttr("defaultRenderGlobals.endFrame",   frame_end)
    cmds.setAttr("defaultRenderGlobals.animation",  True)
    print(f"  [OK] Frame range: {frame_start} - {frame_end}")

    # ── Save auto scene ──
    auto_dir   = PROJECT_ROOT / f"shots/{seq}/{shotcode}/maya/lighting/auto/v001"
    auto_scene = auto_dir / f"MSL_{shotcode}_light_v002_auto.ma"

    cmds.file(rename=str(auto_scene).replace("\\", "/"))
    cmds.file(save=True, type="mayaAscii")
    print(f"  [OK] Saved: {auto_scene}")

    # ── Update JSON ──
    settings["autoScene"]   = str(auto_scene).replace("\\", "/")
    settings["importedCam"] = imported_cam
    with open(json_path, "w") as f:
        json.dump(settings, f, indent=2)
    print(f"  [OK] JSON updated")

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
