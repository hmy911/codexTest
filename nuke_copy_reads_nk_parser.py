# copy_reads_nk_parser.py
# 解析 .nk 檔案中的 Read / DeepRead，複製所有使用到的檔案到指定磁碟
#
# 用法（Windows CMD）：
#   py copy_reads_nk_parser.py "path/to/script.nk"           # 預設 DRY_RUN=True，只模擬
#   py copy_reads_nk_parser.py "path/to/script.nk" --dry     # 強制只模擬
#   py copy_reads_nk_parser.py "path/to/script.nk" --copy    # 真的複製

import os
import re
import sys
import shutil
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ======================
# CONFIG（預設值，可被參數覆蓋 DRY_RUN）
# ======================
DRY_RUN = True               # 預設：只模擬
TARGET_DRIVE = "D:/"         # 目標磁碟機（會保留後面資料夾結構）
MAX_WORKERS = 8              # 平行複製 thread 數量
# log 檔寫在腳本所在資料夾，避免權限問題
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "copy_reads_log.txt")


# ======================
# LOG 工具
# ======================
def log(msg: str):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ======================
# .nk 解析
# ======================
class ReadEntry:
    def __init__(self):
        self.node_type = "Read"
        self.name = None
        self.file = None
        self.first = None
        self.last = None

    def __repr__(self):
        return f"<{self.node_type} {self.name} file={self.file} first={self.first} last={self.last}>"


def parse_nk_for_reads(nk_path):
    """從 .nk 文字解析所有 Read / DeepRead node"""
    reads = []

    with open(nk_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    current = None
    brace_depth = 0

    re_node_start = re.compile(r'^\s*(Read|DeepRead)\b')
    re_name = re.compile(r'^\s*name\s+(.+)$')
    re_file = re.compile(r'^\s*file\s+(.+)$')
    re_first = re.compile(r'^\s*first\s+(-?\d+)')
    re_last = re.compile(r'^\s*last\s+(-?\d+)')

    for line in lines:
        if current is None:
            m = re_node_start.match(line)
            if m:
                current = ReadEntry()
                current.node_type = m.group(1)
                brace_depth = line.count("{") - line.count("}")
                if brace_depth <= 0:
                    brace_depth = 1
            continue

        brace_depth += line.count("{") - line.count("}")

        m_name = re_name.match(line)
        if m_name:
            val = m_name.group(1).strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith('{') and val.endswith('}')):
                val = val[1:-1]
            current.name = val

        m_file = re_file.match(line)
        if m_file:
            val = m_file.group(1).strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith('{') and val.endswith('}')):
                val = val[1:-1]
            current.file = val

        m_first = re_first.match(line)
        if m_first:
            current.first = int(m_first.group(1))

        m_last = re_last.match(line)
        if m_last:
            current.last = int(m_last.group(1))

        if brace_depth <= 0:
            reads.append(current)
            current = None

    return reads


# ======================
# 路徑 / 檔案展開
# ======================
def build_dst_path(src_path: str) -> str:
    """把來源路徑換成目標磁碟，但保留後面資料夾結構"""
    drive, rest = os.path.splitdrive(src_path)
    rest = rest.lstrip("\\/")  # 去掉開頭的 / 或 \
    return os.path.join(TARGET_DRIVE, rest)


def expand_read_to_files(read: ReadEntry):
    """
    將一個 ReadEntry 展開成多個實際檔案路徑（對於序列）。
    支援：
      - %04d 這種 Nuke 標準格式
      - CHB2.####.png / ### / ## 這種寫法（自動轉成 %0Nd）
    """
    files = []
    path = (read.file or "").strip()
    if not path:
        return files

    # 跳過帶有 [ ] 的 TCL/表達式（沒辦法純文字評估）
    if "[" in path and "]" in path:
        log(f"跳過 TCL/表達式路徑：{read}")
        return files

    # ★ 新增：如果有 # 但沒有 %，自動把 #### 轉成 %0Nd
    if "#" in path and "%" not in path:
        m = re.search(r"(#+)", path)
        if m:
            hashes = m.group(1)
            pad = len(hashes)
            fmt = "%%0%dd" % pad   # 4 個 # → %04d
            new_path = path.replace(hashes, fmt)
            log(f"將井字序列轉換：{path}  ->  {new_path}")
            path = new_path

    if "%" in path:
        first = read.first if read.first is not None else 1
        last = read.last if read.last is not None else first
        log(f"序列 {read.node_type} {read.name}  {first}~{last}  pattern={path}")
        for f in range(first, last + 1):
            try:
                files.append(path % f)
            except TypeError:
                files.append(path)
                break
    else:
        log(f"單檔 {read.node_type} {read.name}  {path}")
        files.append(path)

    return files


# ======================
# 複製 worker（平行用）
# ======================
def copy_worker(src_path: str):
    """
    平行複製 worker。
    回傳 (status, src, dst, error_msg)
      status: "ok" / "missing" / "error" / "dry_run"
    """
    if not os.path.exists(src_path):
        return ("missing", src_path, None, "source not found")

    dst_path = build_dst_path(src_path)

    if DRY_RUN:
        return ("dry_run", src_path, dst_path, None)

    try:
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        shutil.copy2(src_path, dst_path)
        return ("ok", src_path, dst_path, None)
    except Exception as e:
        return ("error", src_path, dst_path, str(e))


# ======================
# 主流程
# ======================
def main():
    global DRY_RUN

    if len(sys.argv) < 2:
        print("用法：")
        print("  py copy_reads_nk_parser.py script.nk [--dry | --copy]")
        print("")
        print("  --dry   只模擬（預設模式）")
        print("  --copy  真的複製檔案到目標磁碟")
        sys.exit(1)

    nk_path = sys.argv[1]
    extra_args = sys.argv[2:]

    # 解析 DRY_RUN 參數
    if "--copy" in extra_args:
        DRY_RUN = False
    elif "--dry" in extra_args:
        DRY_RUN = True
    # 若沒帶參數，就用預設 True

    print(f"DRY_RUN = {DRY_RUN}")

    if not os.path.exists(nk_path):
        print(f"找不到 .nk 檔案：{nk_path}")
        sys.exit(1)

    # 初始化 log 檔
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("=== copy_reads_nk_parser.py log ===\n")
        f.write(f"Started at {datetime.datetime.now().isoformat()}\n")
        f.write(f"NK: {nk_path}\n")
        f.write(f"DRY_RUN={DRY_RUN}, TARGET_DRIVE={TARGET_DRIVE}, MAX_WORKERS={MAX_WORKERS}\n\n")

    log(f"開始解析 .nk：{nk_path}")
    reads = parse_nk_for_reads(nk_path)
    log(f"找到 Read/DeepRead 節點數量：{len(reads)}")

    all_sources = []
    for r in reads:
        all_sources.extend(expand_read_to_files(r))

    if not all_sources:
        log("沒有任何來源檔案（可能所有 Read 都是表達式或空）")
        return

    unique_sources = sorted(set(all_sources))
    total = len(unique_sources)
    log(f"展開後來源檔案數量：{len(all_sources)}")
    log(f"去重後實際要處理：{total}")
    log(f"Log 檔案位置：{os.path.abspath(LOG_FILE)}")

    success = []
    missing = []
    errors = []
    dryrun = []

    log("開始平行複製檔案...")

    done_count = 0

    def print_progress():
        percent = (done_count / total) * 100.0
        bar_len = 30
        filled = int(bar_len * done_count / total)
        bar = "#" * filled + "-" * (bar_len - filled)
        sys.stdout.write(f"\r進度：[{bar}] {done_count}/{total} ({percent:5.1f}%)")
        sys.stdout.flush()

    print_progress()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_src = {executor.submit(copy_worker, src): src for src in unique_sources}

        for fut in as_completed(future_to_src):
            status, src, dst, err = fut.result()
            done_count += 1
            print_progress()

            if status == "ok":
                success.append(src)
                log(f"成功複製：{src}  ->  {dst}")
            elif status == "dry_run":
                dryrun.append(src)
                log(f"[DRY_RUN] 模擬複製：{src}  ->  {dst}")
            elif status == "missing":
                missing.append(src)
                log(f"❌ 找不到來源檔案：{src}")
            elif status == "error":
                errors.append(src)
                log(f"❌ 複製失敗：{src}  ->  {dst}  原因：{err}")

    sys.stdout.write("\n")
    log("========================================")
    log("複製流程結束，統計如下：")
    log(f"  成功複製：{len(success)}")
    log(f"  模擬複製 (DRY_RUN)：{len(dryrun)}")
    log(f"  缺少來源檔案：{len(missing)}")
    log(f"  複製失敗：{len(errors)}")
    log("========================================")

    if missing:
        log("缺少來源檔案清單：")
        for p in missing:
            log(f"  MISSING: {p}")

    if errors:
        log("複製失敗清單：")
        for p in errors:
            log(f"  ERROR: {p}")

    log("全部完成。")


if __name__ == "__main__":
    main()

# "C:\Program Files\Nuke16.0v4\python.exe" "D:\vy\nuke_copy_reads_nk_parser.py" "Y:\202509_TWM3\Shots\Part_B\C01\Comp\nuke\_WIP\C01_Comp_v02_396_cleanup.nk" --copy
# "C:\Program Files\Nuke16.0v4\python.exe" "D:\vy\nuke_copy_reads_nk_parser.py" "Y:\202509_TWM3\Shots\Part_B\C01\Comp\nuke\_WIP\C01_Comp_v06_0_cleanup.nk" --copy
# "C:\Program Files\Nuke16.0v4\python.exe" "D:\vy\nuke_copy_reads_nk_parser.py" "X:/202511_Rainie_Concert/Shots/C07/Comp/nuke/_WIP/C07_Comp_v02_4_VY.nk" --copy
# "C:\Program Files\Nuke16.0v4\python.exe" "D:\vy\nuke_copy_reads_nk_parser.py" "X:/202511_Rainie_Concert/Shots/C30/Comp/nuke/_WIP/C30_Comp_v03_4_VY.nk" --copy
