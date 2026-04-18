import hou
import os

# -------- 共用：判斷是不是「檔案類」參數 --------
def iter_file_parms(node):
    for parm in node.parms():
        pt = parm.parmTemplate()
        if pt.type() != hou.parmTemplateType.String:
            continue
        st = pt.stringType()
        if st in (
            hou.stringParmType.FileReference,
            hou.stringParmType.Image,
            hou.stringParmType.NodeReference,
        ):
            yield parm

# -------- 找某個路徑是不是被其他 node 使用 --------
def find_users_of_path(path_str, owner_node):
    """在整個 scene 裡找有沒有其它節點的參數有包含這個文字"""
    users = []
    if not path_str:
        return users

    all_nodes = hou.node("/").allSubChildren()
    for n in all_nodes:
        if n == owner_node:
            continue
        for p in n.parms():
            try:
                raw = p.unexpandedString()
            except hou.OperationFailed:
                continue
            if not isinstance(raw, str):
                continue
            if path_str in raw:
                users.append("%s.%s" % (n.path(), p.name()))
                break  # 一個 node 找到一個就夠了
    return users

# -------- 列出所有 filecache 狀態 --------
def report_filecaches():
    print("========== FILECACHE REPORT ==========")
    all_nodes = hou.node("/").allSubChildren()

    for n in all_nodes:
        ntype = n.type().name().lower()
        if "filecache" not in ntype:
            continue

        # 嘗試抓 output 路徑
        out_parm = None
        for name in ("sopoutput", "file", "filename"):
            if n.parm(name):
                out_parm = n.parm(name)
                break

        out_path = out_parm.evalAsString() if out_parm else ""

        bypass = n.isBypassed()
        display_flag = getattr(n, "isDisplayFlagSet", lambda: False)()
        render_flag  = getattr(n, "isRenderFlagSet",  lambda: False)()

        users = find_users_of_path(out_path, n)
        used_by_others = len(users) > 0

        print("\nNode:   %s" % n.path())
        print("  Type: %s" % n.type().name())
        print("  Bypass: %s" % ("YES" if bypass else "no"))
        print("  DisplayFlag: %s  RenderFlag: %s" % (display_flag, render_flag))
        print("  Cache Path: %s" % (out_path or "<no path>"))
        print("  Ref count: %d" % len(users))
        if used_by_others:
            for u in users:
                print("    -> used in: %s" % u)
        else:
            print("    -> (no parameter references this path)")

# -------- 列出所有 ABC / texture / 其他外部檔案 --------
def report_external_files():
    print("========== EXTERNAL FILES ==========")
    exts_of_interest = [
        ".bgeo", ".bgeo.sc", ".abc", ".obj", ".usd", ".usda", ".usdc",
        ".exr", ".rat", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".hdr"
    ]

    all_nodes = hou.node("/").allSubChildren()
    for n in all_nodes:
        for parm in iter_file_parms(n):
            raw = parm.unexpandedString()
            try:
                val = parm.evalAsString()
            except hou.OperationFailed:
                val = raw

            if not raw:
                continue

            low = val.lower()
            if any(low.endswith(ext) for ext in exts_of_interest):
                print("\nNode: %s" % n.path())
                print("  Parm: %s" % parm.name())
                print("  File: %s" % val)

# 在 Python Shell 直接呼叫：
# report_filecaches()
# report_external_files()
