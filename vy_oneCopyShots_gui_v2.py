# backup_unsorted_to_shots_gui.py
# Version: 2.0 (PySide6)
# Simple GUI: copy from SourceRoot\Cxx\... -> DestShotsRoot\Cxx\<Subpath>\...
#
# Features:
#  - Shot list scrollbar
#  - Keep drive letters (avoid .resolve() -> UNC)
#  - Open Explorer buttons (Source/Dest) + double-click preview row to open src/dst
#  - Logs saved into ./log folder (works for .py and .exe)
#  - Utility: Create any folder from a path + Open it
#  - Utility: Create destination folders for selected shots (DestRoot\Cxx\Subpath) only (no copy)
#  - TAB_B: Parse Nuke Read/DeepRead paths and copy with progress

import os
import re
import sys
import time
import datetime
import shutil
import threading
import subprocess
from pathlib import Path
from typing import Optional, List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6 import QtCore, QtWidgets

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


class ShotCopyWorker(QtCore.QObject):
    progress = QtCore.Signal(int, int)
    status = QtCore.Signal(str)
    finished = QtCore.Signal(str, int, int, int)
    warn = QtCore.Signal(str)

    def __init__(self, src_root: Path, dest_root: Path, subpath: str, shots: List[str],
                 dryrun: bool, overwrite: bool, stop_event: threading.Event):
        super().__init__()
        self.src_root = src_root
        self.dest_root = dest_root
        self.subpath = subpath
        self.shots = shots
        self.dryrun = dryrun
        self.overwrite = overwrite
        self.stop_event = stop_event

    def run(self):
        base_dir = get_base_dir()
        log_dir = base_dir / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"backup_unsorted_to_shots_{now_stamp()}.log"

        tasks = []
        for shot in self.shots:
            sdir = self.src_root / shot
            if not sdir.exists():
                continue
            for f in iter_files(sdir):
                rel = f.relative_to(sdir)
                dst = self.dest_root / shot / self.subpath / rel
                tasks.append((f, dst))

        total = len(tasks)
        if total == 0:
            self.warn.emit("No files found under selected shots.")
            self.finished.emit(str(log_path), 0, 0, 0)
            return

        self.progress.emit(0, total)
        self.status.emit(f"Planned {total} file(s)")

        ok = 0
        skipped = 0
        failed = 0

        with open(log_path, "w", encoding="utf-8") as log:
            log.write(f"[{human_time()}] Start\n")
            log.write(f"Dry-run: {self.dryrun}\nOverwrite: {self.overwrite}\n")
            log.write(f"SourceRoot: {self.src_root}\nDestRoot: {self.dest_root}\nSubpath: {self.subpath}\n")
            log.write(f"Shots: {', '.join(self.shots)}\n")
            log.write("-" * 80 + "\n")

            for i, (src, dst) in enumerate(tasks, start=1):
                if self.stop_event.is_set():
                    log.write(f"[{human_time()}] STOP requested.\n")
                    break
                try:
                    if dst.exists() and not self.overwrite:
                        skipped += 1
                        log.write(f"[SKIP_EXISTS] {src} -> {dst}\n")
                    else:
                        if not self.dryrun:
                            ensure_dir(dst.parent)
                            shutil.copy2(src, dst)
                        ok += 1
                        log.write(f"[OK{'_DRYRUN' if self.dryrun else ''}] {src} -> {dst}\n")
                except Exception as e:
                    failed += 1
                    log.write(f"[FAIL] {src} -> {dst} | {e}\n")

                self.progress.emit(i, total)
                self.status.emit(f"Copying {i}/{total}")

            log.write("-" * 80 + "\n")
            log.write(f"[{human_time()}] End | OK={ok} SKIP={skipped} FAIL={failed}\n")

        self.finished.emit(str(log_path), ok, skipped, failed)


class ShotCopyTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_event = threading.Event()
        self._thread = None
        self._worker = None
        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        box_paths = QtWidgets.QGroupBox("Paths")
        layout.addWidget(box_paths)
        grid = QtWidgets.QGridLayout(box_paths)

        self.edit_source = QtWidgets.QLineEdit(r"Y:\202211_G_Billions\Shots\EP18\Design\AI_Gen\work\unsorted_AE")
        self.edit_dest = QtWidgets.QLineEdit(r"Y:\202211_G_Billions\Shots\EP18\Shots")
        self.edit_subpath = QtWidgets.QLineEdit(r"Comp\AE")

        btn_browse_source = QtWidgets.QPushButton("Browse...")
        btn_browse_dest = QtWidgets.QPushButton("Browse...")
        btn_browse_source.clicked.connect(self._browse_source)
        btn_browse_dest.clicked.connect(self._browse_dest)

        grid.addWidget(QtWidgets.QLabel("Source Root (contains C01, C02...):"), 0, 0)
        grid.addWidget(self.edit_source, 0, 1)
        grid.addWidget(btn_browse_source, 0, 2)

        grid.addWidget(QtWidgets.QLabel("Destination Shots Root:"), 1, 0)
        grid.addWidget(self.edit_dest, 1, 1)
        grid.addWidget(btn_browse_dest, 1, 2)

        grid.addWidget(QtWidgets.QLabel("Destination Subpath (inside each Cxx):"), 2, 0)
        grid.addWidget(self.edit_subpath, 2, 1, 1, 2)

        box_opts = QtWidgets.QGroupBox("Options")
        layout.addWidget(box_opts)
        opts_layout = QtWidgets.QHBoxLayout(box_opts)
        self.chk_dryrun = QtWidgets.QCheckBox("Dry-run (no actual copy)")
        self.chk_overwrite = QtWidgets.QCheckBox("Overwrite existing files")
        self.chk_dryrun.setChecked(True)
        opts_layout.addWidget(self.chk_dryrun)
        opts_layout.addWidget(self.chk_overwrite)
        opts_layout.addStretch()

        main_split = QtWidgets.QHBoxLayout()
        layout.addLayout(main_split, 1)

        box_list = QtWidgets.QGroupBox("Shots (Cxx) found in Source Root")
        main_split.addWidget(box_list)
        list_layout = QtWidgets.QVBoxLayout(box_list)
        self.list_shots = QtWidgets.QListWidget()
        self.list_shots.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        list_layout.addWidget(self.list_shots)

        list_btns = QtWidgets.QHBoxLayout()
        list_layout.addLayout(list_btns)
        btn_refresh = QtWidgets.QPushButton("Refresh")
        btn_select_all = QtWidgets.QPushButton("Select All")
        btn_select_none = QtWidgets.QPushButton("Select None")
        btn_refresh.clicked.connect(self._refresh_list)
        btn_select_all.clicked.connect(self._select_all)
        btn_select_none.clicked.connect(self._select_none)
        list_btns.addWidget(btn_refresh)
        list_btns.addWidget(btn_select_all)
        list_btns.addWidget(btn_select_none)

        box_preview = QtWidgets.QGroupBox("Preview / Results (double-click row to open folders)")
        main_split.addWidget(box_preview, 1)
        preview_layout = QtWidgets.QVBoxLayout(box_preview)
        self.table_preview = QtWidgets.QTableWidget(0, 3)
        self.table_preview.setHorizontalHeaderLabels(["SHOT", "SOURCE", "DESTINATION"])
        self.table_preview.horizontalHeader().setStretchLastSection(True)
        self.table_preview.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table_preview.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table_preview.cellDoubleClicked.connect(self._open_preview_row)
        preview_layout.addWidget(self.table_preview)

        box_bottom = QtWidgets.QHBoxLayout()
        layout.addLayout(box_bottom)
        self.btn_preview = QtWidgets.QPushButton("1) Preview")
        self.btn_copy = QtWidgets.QPushButton("2) Copy")
        self.btn_stop = QtWidgets.QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_preview.clicked.connect(self._preview)
        self.btn_copy.clicked.connect(self._copy)
        self.btn_stop.clicked.connect(self._stop)

        btn_open_source = QtWidgets.QPushButton("Open Source")
        btn_open_dest = QtWidgets.QPushButton("Open Dest")
        btn_open_source.clicked.connect(self._open_source_root)
        btn_open_dest.clicked.connect(self._open_dest_root)

        self.progress = QtWidgets.QProgressBar()
        self.label_status = QtWidgets.QLabel("Idle")

        box_bottom.addWidget(self.btn_preview)
        box_bottom.addWidget(self.btn_copy)
        box_bottom.addWidget(self.btn_stop)
        box_bottom.addWidget(btn_open_source)
        box_bottom.addWidget(btn_open_dest)
        box_bottom.addWidget(self.progress, 1)
        box_bottom.addWidget(self.label_status)

        box_mkdir = QtWidgets.QGroupBox("Create Folder (Utility)")
        layout.addWidget(box_mkdir)
        mkdir_layout = QtWidgets.QHBoxLayout(box_mkdir)
        self.edit_mkdir = QtWidgets.QLineEdit("")
        btn_create_folder = QtWidgets.QPushButton("Create Folder")
        btn_open_folder = QtWidgets.QPushButton("Open")
        btn_create_folder.clicked.connect(self._create_folder)
        btn_open_folder.clicked.connect(self._open_mkdir_path)
        mkdir_layout.addWidget(QtWidgets.QLabel("Folder Path:"))
        mkdir_layout.addWidget(self.edit_mkdir, 1)
        mkdir_layout.addWidget(btn_create_folder)
        mkdir_layout.addWidget(btn_open_folder)
        mkdir_layout.addWidget(QtWidgets.QFrame(frameShape=QtWidgets.QFrame.VLine))
        btn_create_dest = QtWidgets.QPushButton("Create Dest Folders for Selected Shots")
        btn_create_dest.clicked.connect(self._create_dest_folders_for_selected)
        mkdir_layout.addWidget(btn_create_dest)

    def _browse_source(self):
        p = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Source Root (contains C01, C02...)")
        if p:
            self.edit_source.setText(p)
            self._refresh_list()

    def _browse_dest(self):
        p = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Destination Shots Root")
        if p:
            self.edit_dest.setText(p)

    def _select_all(self):
        for i in range(self.list_shots.count()):
            self.list_shots.item(i).setSelected(True)

    def _select_none(self):
        self.list_shots.clearSelection()

    def _refresh_list(self):
        self.list_shots.clear()
        src = Path(os.path.normpath(self.edit_source.text().strip()))
        shots = scan_cxx_folders(src)
        self.list_shots.addItems(shots)
        self.label_status.setText(f"Found {len(shots)} shots in source")

    def _get_selected_shots(self):
        return [item.text() for item in self.list_shots.selectedItems()]

    def _validate(self):
        try:
            src_root = Path(os.path.normpath(self.edit_source.text().strip()))
            dest_root = Path(os.path.normpath(self.edit_dest.text().strip()))
            subpath = self.edit_subpath.text().strip().strip("\\/")

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
            QtWidgets.QMessageBox.critical(self, "Invalid settings", str(e))
            return None

    def _preview(self):
        v = self._validate()
        if not v:
            return
        src_root, dest_root, subpath, shots = v

        self.table_preview.setRowCount(0)
        for shot in shots:
            src = src_root / shot
            dst = dest_root / shot / subpath
            row = self.table_preview.rowCount()
            self.table_preview.insertRow(row)
            self.table_preview.setItem(row, 0, QtWidgets.QTableWidgetItem(shot))
            self.table_preview.setItem(row, 1, QtWidgets.QTableWidgetItem(str(src)))
            self.table_preview.setItem(row, 2, QtWidgets.QTableWidgetItem(str(dst)))
        self.label_status.setText(f"Preview ready: {len(shots)} shot(s)")

    def _stop(self):
        self._stop_event.set()
        self.label_status.setText("Stopping...")

    def _open_source_root(self):
        p = self.edit_source.text().strip()
        if not open_in_explorer(p):
            QtWidgets.QMessageBox.warning(self, "Open Source", f"Folder not found:\n{p}")

    def _open_dest_root(self):
        p = self.edit_dest.text().strip()
        if not open_in_explorer(p):
            QtWidgets.QMessageBox.warning(self, "Open Dest", f"Folder not found:\n{p}")

    def _open_preview_row(self, row, _column):
        src = self.table_preview.item(row, 1).text() if self.table_preview.item(row, 1) else ""
        dst = self.table_preview.item(row, 2).text() if self.table_preview.item(row, 2) else ""
        opened_any = False
        if os.path.isdir(src):
            subprocess.Popen(["explorer", src])
            opened_any = True
        if os.path.isdir(dst):
            subprocess.Popen(["explorer", dst])
            opened_any = True
        if not opened_any:
            QtWidgets.QMessageBox.warning(self, "Open folders", f"Folders not found:\n{src}\n{dst}")

    def _create_folder(self):
        p = self.edit_mkdir.text().strip()
        if not p:
            QtWidgets.QMessageBox.warning(self, "Create Folder", "Please input a folder path.")
            return

        try:
            path = Path(os.path.normpath(p))
            if path.exists():
                QtWidgets.QMessageBox.information(self, "Create Folder", f"Folder already exists:\n{path}")
                return

            path.mkdir(parents=True, exist_ok=True)
            QtWidgets.QMessageBox.information(self, "Create Folder", f"Folder created:\n{path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Create Folder", str(e))

    def _open_mkdir_path(self):
        p = self.edit_mkdir.text().strip()
        if not p:
            return
        if not open_in_explorer(p):
            QtWidgets.QMessageBox.warning(self, "Open Folder", f"Folder not found:\n{p}")

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
        QtWidgets.QMessageBox.information(self, "Create Dest Folders", msg)

    def _copy(self):
        v = self._validate()
        if not v:
            return
        src_root, dest_root, subpath, shots = v

        dryrun = self.chk_dryrun.isChecked()
        overwrite = self.chk_overwrite.isChecked()

        self._stop_event.clear()
        self.btn_stop.setEnabled(True)
        self.btn_preview.setEnabled(False)
        self.btn_copy.setEnabled(False)

        self._thread = QtCore.QThread(self)
        self._worker = ShotCopyWorker(src_root, dest_root, subpath, shots, dryrun, overwrite, self._stop_event)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._update_progress)
        self._worker.status.connect(self.label_status.setText)
        self._worker.warn.connect(self._show_warning)
        self._worker.finished.connect(self._finish_copy)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _show_warning(self, msg: str):
        QtWidgets.QMessageBox.warning(self, "Warning", msg)

    def _update_progress(self, i: int, total: int):
        self.progress.setMaximum(total)
        self.progress.setValue(i)

    def _finish_copy(self, log_path: str, ok: int, skipped: int, failed: int):
        self.btn_stop.setEnabled(False)
        self.btn_preview.setEnabled(True)
        self.btn_copy.setEnabled(True)
        self.label_status.setText(f"Done. OK={ok} SKIP={skipped} FAIL={failed}")
        QtWidgets.QMessageBox.information(
            self,
            "Finished",
            f"Done.\nOK={ok} SKIP={skipped} FAIL={failed}\nLog:\n{log_path}",
        )


class NukeCopyWorker(QtCore.QObject):
    progress = QtCore.Signal(int, int)
    status = QtCore.Signal(str)
    finished = QtCore.Signal(int, int, int, int, str)
    reads_ready = QtCore.Signal(list)

    def __init__(self, nk_path: str, target_drive: str, max_workers: int, dryrun: bool, log_path: str):
        super().__init__()
        self.nk_path = nk_path
        self.target_drive = target_drive
        self.max_workers = max_workers
        self.dryrun = dryrun
        self.log_path = log_path

    def run(self):
        nk.DRY_RUN = self.dryrun
        nk.TARGET_DRIVE = self.target_drive
        nk.MAX_WORKERS = self.max_workers
        nk.LOG_FILE = self.log_path

        with open(nk.LOG_FILE, "w", encoding="utf-8") as f:
            f.write("=== nuke copy reads log ===\n")
            f.write(f"Started at {datetime.datetime.now().isoformat()}\n")
            f.write(f"NK: {self.nk_path}\n")
            f.write(f"DRY_RUN={nk.DRY_RUN}, TARGET_DRIVE={nk.TARGET_DRIVE}, MAX_WORKERS={nk.MAX_WORKERS}\n\n")

        nk.log(f"開始解析 .nk：{self.nk_path}")
        reads = nk.parse_nk_for_reads(self.nk_path)
        nk.log(f"找到 Read/DeepRead 節點數量：{len(reads)}")

        read_entries = []
        for r in reads:
            raw_path = (r.file or "").strip()
            if raw_path:
                display_path = NukeCopyTab.format_sequence_display(raw_path, r.first, r.last)
                read_entries.append({"display": display_path, "raw": raw_path})

        unique_entries = {}
        for entry in read_entries:
            unique_entries.setdefault(entry["display"], entry)
        sorted_entries = [unique_entries[key] for key in sorted(unique_entries)]
        self.reads_ready.emit(sorted_entries)

        all_sources = []
        for r in reads:
            all_sources.extend(nk.expand_read_to_files(r))

        if not all_sources:
            self.finished.emit(0, 0, 0, 0, "No source files found.")
            return

        unique_sources = sorted(set(all_sources))
        total = len(unique_sources)
        nk.log(f"展開後來源檔案數量：{len(all_sources)}")
        nk.log(f"去重後實際要處理：{total}")
        nk.log(f"Log 檔案位置：{os.path.abspath(nk.LOG_FILE)}")

        success = []
        missing = []
        errors = []
        dryrun_list = []
        done_count = 0

        self.progress.emit(done_count, total)
        self.status.emit("Copying 0/%d" % total)

        nk.log("開始平行複製檔案...")
        with ThreadPoolExecutor(max_workers=nk.MAX_WORKERS) as executor:
            future_to_src = {executor.submit(nk.copy_worker, src): src for src in unique_sources}
            for fut in as_completed(future_to_src):
                status, src, dst, err = fut.result()
                done_count += 1
                self.progress.emit(done_count, total)
                self.status.emit(f"Copying {done_count}/{total}")

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

        self.finished.emit(len(success), len(dryrun_list), len(missing), len(errors), "Done.")


class NukeCopyTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None
        self._log_path = None
        self._read_entries: List[Dict[str, str]] = []
        self._build_ui()

    @staticmethod
    def format_sequence_display(path: str, first: Optional[int], last: Optional[int]) -> str:
        if not path:
            return ""
        display_path = path

        if "#" in display_path and "%" not in display_path:
            match = re.search(r"(#+)", display_path)
            if match:
                hashes = match.group(1)
                pad = len(hashes)
                display_path = display_path.replace(hashes, f"%0{pad}d")

        if "%" in display_path and first is not None and last is not None:
            try:
                start = display_path % first
                end = display_path % last
                start_dir, start_name = os.path.split(start)
                _, end_name = os.path.split(end)
                start_root, start_ext = os.path.splitext(start_name)
                end_root, _ = os.path.splitext(end_name)
                return os.path.join(start_dir, f"{start_root}-{end_root}{start_ext}")
            except TypeError:
                return display_path

        return display_path

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        box_paths = QtWidgets.QGroupBox("NK Script")
        layout.addWidget(box_paths)
        grid = QtWidgets.QGridLayout(box_paths)

        self.edit_nk_path = QtWidgets.QLineEdit("")
        btn_browse = QtWidgets.QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_nk)

        grid.addWidget(QtWidgets.QLabel("NK File:"), 0, 0)
        grid.addWidget(self.edit_nk_path, 0, 1)
        grid.addWidget(btn_browse, 0, 2)

        box_opts = QtWidgets.QGroupBox("Options")
        layout.addWidget(box_opts)
        opts_layout = QtWidgets.QGridLayout(box_opts)

        self.edit_target_drive = QtWidgets.QLineEdit(nk.TARGET_DRIVE)
        self.spin_max_workers = QtWidgets.QSpinBox()
        self.spin_max_workers.setRange(1, 32)
        self.spin_max_workers.setValue(nk.MAX_WORKERS)
        self.chk_dryrun = QtWidgets.QCheckBox("Dry-run (no actual copy)")
        self.chk_dryrun.setChecked(nk.DRY_RUN)

        opts_layout.addWidget(QtWidgets.QLabel("Target Drive:"), 0, 0)
        opts_layout.addWidget(self.edit_target_drive, 0, 1)
        opts_layout.addWidget(QtWidgets.QLabel("Max Workers:"), 0, 2)
        opts_layout.addWidget(self.spin_max_workers, 0, 3)
        opts_layout.addWidget(self.chk_dryrun, 0, 4)

        box_reads = QtWidgets.QGroupBox("Read Paths (from .nk)")
        layout.addWidget(box_reads, 1)
        reads_layout = QtWidgets.QVBoxLayout(box_reads)
        self.list_reads = QtWidgets.QListWidget()
        self.list_reads.itemDoubleClicked.connect(self._open_selected_read_folder)
        reads_layout.addWidget(self.list_reads, 1)

        reads_btns = QtWidgets.QHBoxLayout()
        reads_layout.addLayout(reads_btns)
        btn_copy_path = QtWidgets.QPushButton("Copy Path")
        btn_open_folder = QtWidgets.QPushButton("Open Folder")
        btn_copy_path.clicked.connect(self._copy_selected_read_path)
        btn_open_folder.clicked.connect(self._open_selected_read_folder)
        reads_btns.addWidget(btn_copy_path)
        reads_btns.addWidget(btn_open_folder)
        reads_btns.addStretch()

        box_bottom = QtWidgets.QHBoxLayout()
        layout.addLayout(box_bottom)
        btn_run = QtWidgets.QPushButton("Run Copy")
        btn_open_log = QtWidgets.QPushButton("Open Log")
        btn_run.clicked.connect(self._run_copy)
        btn_open_log.clicked.connect(self._open_log)

        self.progress = QtWidgets.QProgressBar()
        self.label_status = QtWidgets.QLabel("Idle")

        box_bottom.addWidget(btn_run)
        box_bottom.addWidget(btn_open_log)
        box_bottom.addWidget(self.progress, 1)
        box_bottom.addWidget(self.label_status)

    def _browse_nk(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Nuke Script (.nk)",
            "",
            "Nuke Script (*.nk);;All Files (*)",
        )
        if p:
            self.edit_nk_path.setText(p)

    def _open_log(self):
        if not self._log_path:
            QtWidgets.QMessageBox.warning(self, "Open Log", "No log file yet.")
            return
        if not open_in_explorer(str(self._log_path)):
            QtWidgets.QMessageBox.warning(self, "Open Log", f"Log not found:\n{self._log_path}")

    def _copy_selected_read_path(self):
        items = self.list_reads.selectedItems()
        if not items:
            QtWidgets.QMessageBox.warning(self, "Copy Path", "No read path selected.")
            return
        row = self.list_reads.row(items[0])
        raw_path = self._read_entries[row]["raw"]
        QtWidgets.QApplication.clipboard().setText(raw_path)
        self.label_status.setText("Path copied to clipboard.")

    def _open_selected_read_folder(self):
        items = self.list_reads.selectedItems()
        if not items:
            QtWidgets.QMessageBox.warning(self, "Open Folder", "No read path selected.")
            return
        row = self.list_reads.row(items[0])
        raw_path = self._read_entries[row]["raw"]
        folder = os.path.dirname(raw_path)
        if not open_in_explorer(folder):
            QtWidgets.QMessageBox.warning(self, "Open Folder", f"Folder not found:\n{folder}")

    def _validate(self):
        nk_path = self.edit_nk_path.text().strip()
        if not nk_path:
            QtWidgets.QMessageBox.warning(self, "Invalid settings", "Please select a .nk file.")
            return None
        if not os.path.exists(nk_path):
            QtWidgets.QMessageBox.warning(self, "Invalid settings", f"NK file not found:\n{nk_path}")
            return None

        target_drive = self.edit_target_drive.text().strip()
        if not target_drive:
            QtWidgets.QMessageBox.warning(self, "Invalid settings", "Target Drive is empty.")
            return None
        if re.match(r"^[A-Za-z]:$", target_drive):
            target_drive = f"{target_drive}/"

        max_workers = int(self.spin_max_workers.value())
        dryrun = self.chk_dryrun.isChecked()
        return nk_path, target_drive, max_workers, dryrun

    def _run_copy(self):
        if self._thread and self._thread.isRunning():
            QtWidgets.QMessageBox.warning(self, "Running", "Copy is already running.")
            return

        settings = self._validate()
        if not settings:
            return
        nk_path, target_drive, max_workers, dryrun = settings

        base_dir = get_base_dir()
        log_dir = base_dir / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = log_dir / f"copy_reads_{now_stamp()}.log"

        self.progress.setValue(0)
        self.label_status.setText("Parsing...")
        self.list_reads.clear()
        self._read_entries = []

        self._thread = QtCore.QThread(self)
        self._worker = NukeCopyWorker(nk_path, target_drive, max_workers, dryrun, str(self._log_path))
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._update_progress)
        self._worker.status.connect(self.label_status.setText)
        self._worker.reads_ready.connect(self._update_read_list)
        self._worker.finished.connect(self._finish_copy)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _update_read_list(self, entries: list):
        self._read_entries = entries
        self.list_reads.clear()
        for entry in entries:
            self.list_reads.addItem(entry["display"])

    def _update_progress(self, i: int, total: int):
        self.progress.setMaximum(total)
        self.progress.setValue(i)

    def _finish_copy(self, success: int, dryrun: int, missing: int, errors: int, msg: str):
        self.label_status.setText(msg)
        QtWidgets.QMessageBox.information(
            self,
            "Finished",
            f"{msg}\nSuccess: {success}\nDry-run: {dryrun}\nMissing: {missing}\nErrors: {errors}\nLog:\n{self._log_path}",
        )


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Backup Tools - Tabs")
        self.resize(1180, 820)

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(ShotCopyTab(), "TAB_A: vy_oneCopyShots")
        tabs.addTab(NukeCopyTab(), "TAB_B: Nuke copy reads")
        self.setCentralWidget(tabs)


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()


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
