
# backup_unsorted_to_shots_gui.py
# Version: 1.2
# Simple GUI: copy from SourceRoot\Cxx\... -> DestShotsRoot\Cxx\<Subpath>\...
#
# Features:
#  - Shot list scrollbar
#  - Keep drive letters (avoid .resolve() -> UNC)
#  - Open Explorer buttons (Source/Dest) + double-click preview row to open src/dst
#  - Logs saved into ./log folder (works for .py and .exe)
#  - Utility: Create any folder from a path + Open it
#  - Utility: Create destination folders for selected shots (DestRoot\Cxx\Subpath) only (no copy)

import os
import re
import sys
import time
import datetime
import shutil
import threading
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from concurrent.futures import ThreadPoolExecutor, as_completed
import nuke_copy_reads_nk_parser as nk

CXX_RE = re.compile(r"^C\d{2}$", re.IGNORECASE)

def now_stamp():
    return time.strftime("%Y%m%d_%H%M%S")

def human_time():
    return time.strftime("%Y-%m-%d %H:%M:%S")

def is_cxx_dir(p: Path) -> bool:
    return p.is_dir() and CXX_RE.match(p.name) is not None

def scan_cxx_folders(source_root: Path):
    if not source_root.exists():
        return []
    items = [p.name.upper() for p in source_root.iterdir() if is_cxx_dir(p)]
    items.sort(key=lambda s: int(s[1:]))  # C01..C99
    return items

def iter_files(root: Path):
    for p in root.rglob("*"):
        if p.is_file():
            yield p

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def open_in_explorer(path_str: str):
    p = path_str.strip()
    if not p:
        return False
    if os.path.isdir(p) or os.path.isfile(p):
        subprocess.Popen(["explorer", p])
        return True
    return False

def get_base_dir() -> Path:
    # base folder: .py -> script folder; .exe -> exe folder
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent

class ShotCopyTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        # Defaults based on your example
        self.var_source = tk.StringVar(value=r"Y:\202211_G_Billions\Shots\EP18\Design\AI_Gen\work\unsorted_AE")
        self.var_dest_root = tk.StringVar(value=r"Y:\202211_G_Billions\Shots\EP18\Shots")
        self.var_subpath = tk.StringVar(value=r"Comp\AE")
        self.var_overwrite = tk.BooleanVar(value=False)
        self.var_dryrun = tk.BooleanVar(value=True)

        # Utility: create folder
        self.var_mkdir_path = tk.StringVar(value=r"")

        self._stop_flag = False
        self._worker = None

        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True)

        # Paths
        box_paths = ttk.LabelFrame(frm, text="Paths")
        box_paths.pack(fill="x", **pad)

        ttk.Label(box_paths, text="Source Root (contains C01, C02...):").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(box_paths, textvariable=self.var_source, width=92).grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(box_paths, text="Browse...", command=self._browse_source).grid(row=0, column=2, **pad)

        ttk.Label(box_paths, text="Destination Shots Root:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(box_paths, textvariable=self.var_dest_root, width=92).grid(row=1, column=1, sticky="we", **pad)
        ttk.Button(box_paths, text="Browse...", command=self._browse_dest).grid(row=1, column=2, **pad)

        ttk.Label(box_paths, text="Destination Subpath (inside each Cxx):").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(box_paths, textvariable=self.var_subpath, width=92).grid(row=2, column=1, sticky="we", **pad)

        box_paths.columnconfigure(1, weight=1)

        # Options
        box_opts = ttk.LabelFrame(frm, text="Options")
        box_opts.pack(fill="x", **pad)

        ttk.Checkbutton(box_opts, text="Dry-run (no actual copy)", variable=self.var_dryrun).grid(row=0, column=0, sticky="w", **pad)
        ttk.Checkbutton(box_opts, text="Overwrite existing files", variable=self.var_overwrite).grid(row=0, column=1, sticky="w", **pad)

        # Main split area
        box_main = ttk.Frame(frm)
        box_main.pack(fill="both", expand=True, **pad)

        # Left: list of shots (with scrollbar)
        box_list = ttk.LabelFrame(box_main, text="Shots (Cxx) found in Source Root")
        box_list.pack(side="left", fill="y", padx=6, pady=6)

        list_frame = ttk.Frame(box_list)
        list_frame.pack(fill="y", expand=True, padx=8, pady=8)

        self.listbox = tk.Listbox(list_frame, selectmode="extended", width=18, height=24)
        sb_list = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb_list.set)

        self.listbox.pack(side="left", fill="y", expand=True)
        sb_list.pack(side="right", fill="y")

        btn_row = ttk.Frame(box_list)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btn_row, text="Refresh", command=self._refresh_list).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Select All", command=self._select_all).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Select None", command=self._select_none).pack(side="left", padx=4)

        # Right: preview/results
        box_preview = ttk.LabelFrame(box_main, text="Preview / Results (double-click row to open folders)")
        box_preview.pack(side="left", fill="both", expand=True, padx=6, pady=6)

        cols = ("shot", "src", "dst")
        self.tree = ttk.Treeview(box_preview, columns=cols, show="headings")
        self.tree.heading("shot", text="SHOT")
        self.tree.heading("src", text="SOURCE")
        self.tree.heading("dst", text="DESTINATION")
        self.tree.column("shot", width=80, anchor="w")
        self.tree.column("src", width=440, anchor="w")
        self.tree.column("dst", width=440, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(box_preview, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        self.tree.bind("<Double-1>", self._open_selected_preview_folders)

        # Bottom controls
        box_bottom = ttk.Frame(frm)
        box_bottom.pack(fill="x", **pad)

        self.btn_preview = ttk.Button(box_bottom, text="1) Preview", command=self._preview)
        self.btn_preview.pack(side="left", padx=6)

        self.btn_copy = ttk.Button(box_bottom, text="2) Copy", command=self._copy)
        self.btn_copy.pack(side="left", padx=6)

        self.btn_stop = ttk.Button(box_bottom, text="Stop", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=6)

        ttk.Button(box_bottom, text="Open Source", command=self._open_source_root).pack(side="left", padx=6)
        ttk.Button(box_bottom, text="Open Dest", command=self._open_dest_root).pack(side="left", padx=6)

        self.prog = ttk.Progressbar(box_bottom, mode="determinate")
        self.prog.pack(side="left", fill="x", expand=True, padx=10)

        self.lbl = ttk.Label(box_bottom, text="Idle")
        self.lbl.pack(side="left", padx=6)

        # ---- Create Folder Utility ----
        box_mkdir = ttk.LabelFrame(frm, text="Create Folder (Utility)")
        box_mkdir.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Label(box_mkdir, text="Folder Path:").pack(side="left", padx=6)
        ttk.Entry(box_mkdir, textvariable=self.var_mkdir_path, width=78).pack(side="left", padx=6, fill="x", expand=True)
        ttk.Button(box_mkdir, text="Create Folder", command=self._create_folder).pack(side="left", padx=6)
        ttk.Button(box_mkdir, text="Open", command=self._open_mkdir_path).pack(side="left", padx=6)

        ttk.Separator(box_mkdir, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(
            box_mkdir,
            text="Create Dest Folders for Selected Shots",
            command=self._create_dest_folders_for_selected
        ).pack(side="left", padx=6)

    # ---------- Browsing / selection ----------
    def _browse_source(self):
        p = filedialog.askdirectory(title="Select Source Root (contains C01, C02...)")
        if p:
            self.var_source.set(p)
            self._refresh_list()

    def _browse_dest(self):
        p = filedialog.askdirectory(title="Select Destination Shots Root")
        if p:
            self.var_dest_root.set(p)

    def _select_all(self):
        self.listbox.select_set(0, "end")

    def _select_none(self):
        self.listbox.selection_clear(0, "end")

    def _clear_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

    def _refresh_list(self):
        self.listbox.delete(0, "end")
        src = Path(os.path.normpath(self.var_source.get().strip()))
        shots = scan_cxx_folders(src)
        for s in shots:
            self.listbox.insert("end", s)
        self.lbl.config(text=f"Found {len(shots)} shots in source")

    def _get_selected_shots(self):
        idxs = self.listbox.curselection()
        return [self.listbox.get(i) for i in idxs]

    # ---------- Validation ----------
    def _validate(self):
        try:
            # IMPORTANT: do NOT .resolve() to avoid mapped drive turning into UNC
            src_root = Path(os.path.normpath(self.var_source.get().strip()))
            dest_root = Path(os.path.normpath(self.var_dest_root.get().strip()))
            subpath = self.var_subpath.get().strip().strip("\\/")

            if not src_root.exists() or not src_root.is_dir():
                raise ValueError(f"Source root not found: {src_root}")
            if not dest_root.exists() or not dest_root.is_dir():
                raise ValueError(f"Destination shots root not found: {dest_root}")
            if not subpath:
                raise ValueError("Destination Subpath is empty (e.g. Comp\\AE)")

            shots = self._get_selected_shots()
            if not shots:
                raise ValueError("No shots selected in the list (select C01..).")

            return src_root, dest_root, subpath, shots
        except Exception as e:
            messagebox.showerror("Invalid settings", str(e))
            return None

    # ---------- Preview ----------
    def _preview(self):
        v = self._validate()
        if not v:
            return
        src_root, dest_root, subpath, shots = v

        self._clear_tree()
        for shot in shots:
            src = src_root / shot
            dst = dest_root / shot / subpath
            self.tree.insert("", "end", values=(shot, str(src), str(dst)))
        self.lbl.config(text=f"Preview ready: {len(shots)} shot(s)")

    # ---------- Stop ----------
    def _stop(self):
        self._stop_flag = True
        self.lbl.config(text="Stopping...")

    # ---------- Explorer ----------
    def _open_source_root(self):
        p = self.var_source.get().strip()
        if not open_in_explorer(p):
            messagebox.showwarning("Open Source", f"Folder not found:\n{p}")

    def _open_dest_root(self):
        p = self.var_dest_root.get().strip()
        if not open_in_explorer(p):
            messagebox.showwarning("Open Dest", f"Folder not found:\n{p}")

    def _open_selected_preview_folders(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        if not vals or len(vals) < 3:
            return

        src = vals[1]
        dst = vals[2]

        opened_any = False
        if os.path.isdir(src):
            subprocess.Popen(["explorer", src])
            opened_any = True
        if os.path.isdir(dst):
            subprocess.Popen(["explorer", dst])
            opened_any = True

        if not opened_any:
            messagebox.showwarning("Open folders", f"Folders not found:\n{src}\n{dst}")

    # ---------- Utility: Create Folder ----------
    def _create_folder(self):
        p = self.var_mkdir_path.get().strip()
        if not p:
            messagebox.showwarning("Create Folder", "Please input a folder path.")
            return

        try:
            path = Path(os.path.normpath(p))
            if path.exists():
                messagebox.showinfo("Create Folder", f"Folder already exists:\n{path}")
                return

            path.mkdir(parents=True, exist_ok=True)
            messagebox.showinfo("Create Folder", f"Folder created:\n{path}")
        except Exception as e:
            messagebox.showerror("Create Folder", str(e))

    def _open_mkdir_path(self):
        p = self.var_mkdir_path.get().strip()
        if not p:
            return
        if not open_in_explorer(p):
            messagebox.showwarning("Open Folder", f"Folder not found:\n{p}")

    # ---------- Utility: Create Dest folders (no copy) ----------
    def _create_dest_folders_for_selected(self):
        v = self._validate()
        if not v:
            return
        _, dest_root, subpath, shots = v

        created = 0
        existed = 0
        failed = 0
        errs = []

        for shot in shots:
            try:
                dst_dir = dest_root / shot / subpath
                if dst_dir.exists():
                    existed += 1
                else:
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    created += 1
            except Exception as e:
                failed += 1
                errs.append(f"{shot}: {e}")

        msg = f"Created: {created}\nAlready existed: {existed}\nFailed: {failed}"
        if errs:
            msg += "\n\nErrors:\n" + "\n".join(errs[:10])
            if len(errs) > 10:
                msg += f"\n... ({len(errs)-10} more)"
        messagebox.showinfo("Create Dest Folders", msg)

    # ---------- Copy ----------
    def _copy(self):
        v = self._validate()
        if not v:
            return
        src_root, dest_root, subpath, shots = v

        dryrun = self.var_dryrun.get()
        overwrite = self.var_overwrite.get()

        # Log folder (works for .py and .exe)
        base_dir = get_base_dir()
        log_dir = base_dir / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"backup_unsorted_to_shots_{now_stamp()}.log"

        # UI state
        self._stop_flag = False
        self.btn_stop.config(state="normal")
        self.btn_preview.config(state="disabled")
        self.btn_copy.config(state="disabled")

        # Build tasks: per-file operations
        tasks = []
        for shot in shots:
            sdir = src_root / shot
            if not sdir.exists():
                continue
            for f in iter_files(sdir):
                rel = f.relative_to(sdir)  # keep structure under Cxx
                dst = dest_root / shot / subpath / rel
                tasks.append((f, dst))

        total = len(tasks)
        if total == 0:
            messagebox.showwarning("Nothing to copy", "No files found under selected shots.")
            self.btn_stop.config(state="disabled")
            self.btn_preview.config(state="normal")
            self.btn_copy.config(state="normal")
            return

        self.prog["value"] = 0
        self.prog["maximum"] = total
        self.lbl.config(text=f"Planned {total} file(s)")

        def worker():
            ok = 0
            skipped = 0
            failed = 0

            with open(log_path, "w", encoding="utf-8") as log:
                log.write(f"[{human_time()}] Start\n")
                log.write(f"Dry-run: {dryrun}\nOverwrite: {overwrite}\n")
                log.write(f"SourceRoot: {src_root}\nDestRoot: {dest_root}\nSubpath: {subpath}\n")
                log.write(f"Shots: {', '.join(shots)}\n")
                log.write("-" * 80 + "\n")

                for i, (src, dst) in enumerate(tasks, start=1):
                    if self._stop_flag:
                        log.write(f"[{human_time()}] STOP requested.\n")
                        break
                    try:
                        if dst.exists() and not overwrite:
                            skipped += 1
                            log.write(f"[SKIP_EXISTS] {src} -> {dst}\n")
                        else:
                            if not dryrun:
                                ensure_dir(dst.parent)
                                shutil.copy2(src, dst)
                            ok += 1
                            log.write(f"[OK{'_DRYRUN' if dryrun else ''}] {src} -> {dst}\n")
                    except Exception as e:
                        failed += 1
                        log.write(f"[FAIL] {src} -> {dst} | {e}\n")

                    self.after(0, lambda i=i: self._update_progress(i, total))

                log.write("-" * 80 + "\n")
                log.write(f"[{human_time()}] End | OK={ok} SKIP={skipped} FAIL={failed}\n")

            self.after(0, lambda: self._finish(log_path, ok, skipped, failed))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _update_progress(self, i, total):
        self.prog["value"] = i
        self.lbl.config(text=f"Copying {i}/{total}")

    def _finish(self, log_path, ok, skipped, failed):
        self.btn_stop.config(state="disabled")
        self.btn_preview.config(state="normal")
        self.btn_copy.config(state="normal")
        self.lbl.config(text=f"Done. OK={ok} SKIP={skipped} FAIL={failed}")
        messagebox.showinfo("Finished", f"Done.\nOK={ok} SKIP={skipped} FAIL={failed}\nLog:\n{log_path}")

class NukeCopyTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.var_nk_path = tk.StringVar(value=r"")
        self.var_target_drive = tk.StringVar(value=nk.TARGET_DRIVE)
        self.var_dryrun = tk.BooleanVar(value=nk.DRY_RUN)
        self.var_max_workers = tk.IntVar(value=nk.MAX_WORKERS)
        self.var_status = tk.StringVar(value="Idle")
        self._log_path = None
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True)

        box_paths = ttk.LabelFrame(frm, text="NK Script")
        box_paths.pack(fill="x", **pad)

        ttk.Label(box_paths, text="NK File:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(box_paths, textvariable=self.var_nk_path, width=92).grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(box_paths, text="Browse...", command=self._browse_nk).grid(row=0, column=2, **pad)

        box_paths.columnconfigure(1, weight=1)

        box_opts = ttk.LabelFrame(frm, text="Options")
        box_opts.pack(fill="x", **pad)

        ttk.Label(box_opts, text="Target Drive:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(box_opts, textvariable=self.var_target_drive, width=12).grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(box_opts, text="Max Workers:").grid(row=0, column=2, sticky="w", **pad)
        ttk.Spinbox(box_opts, from_=1, to=32, textvariable=self.var_max_workers, width=6).grid(
            row=0, column=3, sticky="w", **pad
        )

        ttk.Checkbutton(box_opts, text="Dry-run (no actual copy)", variable=self.var_dryrun).grid(
            row=0, column=4, sticky="w", **pad
        )

        box_reads = ttk.LabelFrame(frm, text="Read Paths (from .nk)")
        box_reads.pack(fill="both", expand=True, **pad)

        reads_frame = ttk.Frame(box_reads)
        reads_frame.pack(fill="both", expand=True, padx=8, pady=8)

        self.reads_list = tk.Listbox(reads_frame, height=12)
        reads_scroll = ttk.Scrollbar(reads_frame, orient="vertical", command=self.reads_list.yview)
        self.reads_list.configure(yscrollcommand=reads_scroll.set)

        self.reads_list.pack(side="left", fill="both", expand=True)
        reads_scroll.pack(side="right", fill="y")

        box_bottom = ttk.Frame(frm)
        box_bottom.pack(fill="x", **pad)

        ttk.Button(box_bottom, text="Run Copy", command=self._run_copy).pack(side="left", padx=6)
        ttk.Button(box_bottom, text="Open Log", command=self._open_log).pack(side="left", padx=6)

        self.prog = ttk.Progressbar(box_bottom, mode="determinate")
        self.prog.pack(side="left", fill="x", expand=True, padx=10)

        ttk.Label(box_bottom, textvariable=self.var_status).pack(side="left", padx=6)

    def _browse_nk(self):
        p = filedialog.askopenfilename(
            title="Select Nuke Script (.nk)",
            filetypes=[("Nuke Script", "*.nk"), ("All Files", "*.*")]
        )
        if p:
            self.var_nk_path.set(p)

    def _open_log(self):
        if not self._log_path:
            messagebox.showwarning("Open Log", "No log file yet.")
            return
        if not open_in_explorer(str(self._log_path)):
            messagebox.showwarning("Open Log", f"Log not found:\n{self._log_path}")

    def _validate(self):
        nk_path = self.var_nk_path.get().strip()
        if not nk_path:
            messagebox.showwarning("Invalid settings", "Please select a .nk file.")
            return None
        if not os.path.exists(nk_path):
            messagebox.showwarning("Invalid settings", f"NK file not found:\n{nk_path}")
            return None

        target_drive = self.var_target_drive.get().strip()
        if not target_drive:
            messagebox.showwarning("Invalid settings", "Target Drive is empty.")
            return None
        if re.match(r"^[A-Za-z]:$", target_drive):
            target_drive = f"{target_drive}/"

        try:
            max_workers = int(self.var_max_workers.get())
        except ValueError:
            messagebox.showwarning("Invalid settings", "Max Workers must be a number.")
            return None
        if max_workers < 1:
            messagebox.showwarning("Invalid settings", "Max Workers must be >= 1.")
            return None

        return nk_path, target_drive, max_workers, self.var_dryrun.get()

    def _run_copy(self):
        if self._worker and self._worker.is_alive():
            messagebox.showwarning("Running", "Copy is already running.")
            return

        settings = self._validate()
        if not settings:
            return
        nk_path, target_drive, max_workers, dryrun = settings

        nk.DRY_RUN = dryrun
        nk.TARGET_DRIVE = target_drive
        nk.MAX_WORKERS = max_workers

        base_dir = get_base_dir()
        log_dir = base_dir / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = log_dir / f"copy_reads_{now_stamp()}.log"
        nk.LOG_FILE = str(self._log_path)

        self.prog["value"] = 0
        self.var_status.set("Parsing...")
        self.reads_list.delete(0, "end")

        def worker():
            try:
                with open(nk.LOG_FILE, "w", encoding="utf-8") as f:
                    f.write("=== nuke copy reads log ===\n")
                    f.write(f"Started at {datetime.datetime.now().isoformat()}\n")
                    f.write(f"NK: {nk_path}\n")
                    f.write(f"DRY_RUN={nk.DRY_RUN}, TARGET_DRIVE={nk.TARGET_DRIVE}, MAX_WORKERS={nk.MAX_WORKERS}\n\n")

                nk.log(f"開始解析 .nk：{nk_path}")
                reads = nk.parse_nk_for_reads(nk_path)
                nk.log(f"找到 Read/DeepRead 節點數量：{len(reads)}")

                all_sources = []
                for r in reads:
                    all_sources.extend(nk.expand_read_to_files(r))

                if not all_sources:
                    self.after(0, lambda: self._finish_copy(0, 0, 0, 0, "No source files found."))
                    return

                unique_sources = sorted(set(all_sources))
                total = len(unique_sources)
                nk.log(f"展開後來源檔案數量：{len(all_sources)}")
                nk.log(f"去重後實際要處理：{total}")
                nk.log(f"Log 檔案位置：{os.path.abspath(nk.LOG_FILE)}")

                def update_read_list():
                    self.reads_list.delete(0, "end")
                    for src in unique_sources:
                        self.reads_list.insert("end", src)

                self.after(0, update_read_list)

                success = []
                missing = []
                errors = []
                dryrun_list = []
                done_count = 0

                def update_progress():
                    self.prog["value"] = done_count
                    self.prog["maximum"] = total
                    self.var_status.set(f"Copying {done_count}/{total}")

                self.after(0, update_progress)

                nk.log("開始平行複製檔案...")
                with ThreadPoolExecutor(max_workers=nk.MAX_WORKERS) as executor:
                    future_to_src = {executor.submit(nk.copy_worker, src): src for src in unique_sources}

                    for fut in as_completed(future_to_src):
                        status, src, dst, err = fut.result()
                        done_count += 1
                        self.after(0, update_progress)

                        if status == "ok":
                            success.append(src)
                            nk.log(f"成功複製：{src}  ->  {dst}")
                        elif status == "dry_run":
                            dryrun_list.append(src)
                            nk.log(f"[DRY_RUN] 模擬複製：{src}  ->  {dst}")
                        elif status == "missing":
                            missing.append(src)
                            nk.log(f"❌ 找不到來源檔案：{src}")
                        elif status == "error":
                            errors.append(src)
                            nk.log(f"❌ 複製失敗：{src}  ->  {dst}  原因：{err}")

                nk.log("========================================")
                nk.log("複製流程結束，統計如下：")
                nk.log(f"  成功複製：{len(success)}")
                nk.log(f"  模擬複製 (DRY_RUN)：{len(dryrun_list)}")
                nk.log(f"  缺少來源檔案：{len(missing)}")
                nk.log(f"  複製失敗：{len(errors)}")
                nk.log("========================================")

                self.after(0, lambda: self._finish_copy(
                    len(success), len(dryrun_list), len(missing), len(errors), "Done."
                ))
            except Exception as e:
                self.after(0, lambda: self._finish_copy(0, 0, 0, 0, f"Error: {e}"))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _finish_copy(self, success, dryrun, missing, errors, msg):
        self.var_status.set(msg)
        messagebox.showinfo(
            "Finished",
            f"{msg}\nSuccess: {success}\nDry-run: {dryrun}\nMissing: {missing}\nErrors: {errors}\nLog:\n{self._log_path}"
        )


class MainApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Backup Tools - Tabs")
        self.geometry("1120x780")

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        tab_shots = ShotCopyTab(notebook)
        tab_nuke = NukeCopyTab(notebook)

        notebook.add(tab_shots, text="TAB_A: vy_oneCopyShots")
        notebook.add(tab_nuke, text="TAB_B: Nuke copy reads")


if __name__ == "__main__":
    MainApp().mainloop()


'''
oneCopyAll通用型備份工具
vy_oneCopyShots_gui.py

把檔案存成 vy_oneCopyShots_gui.py
CMD 執行：
python D:/vy/vy_oneCopyShots_gui_v2.py

產生exe檔
pip install pyinstaller
# pyinstaller --noconfirm --onefile --windowed D:/vy/vy_oneCopyShots_gui_v2.py
pyinstaller --noconfirm --clean --onedir --windowed D:/vy/vy_oneCopyShots_gui_v2.py

完成後 exe 會在：
C:/Users/GJ/dist/backup_unsorted_to_shots_gui.exe

Source Root 指到：.../unsorted_AE
Refresh 後選 C01..Cxx
Destination Shots Root 指到：.../Shots/EP18/Shots
Subpath 填：Comp/AE
先勾 Dry-run 跑一次確認
取消 Dry-run 再 Copy
'''
