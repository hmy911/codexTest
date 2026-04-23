import json
import os
import queue
import re
import shlex
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk


APP_DIR = Path(__file__).resolve().parent
CONFIG_FILENAME = "msl_batch_arena_gui_config.json"
APP_TITLE = "MSL Batch Arena GUI"
ROOT_BG = "#0f141a"
PANEL_BG = "#17212b"
PANEL_BORDER = "#2a3947"
TEXT_BG = "#0c1117"
TEXT_FG = "#e6edf3"
LABEL_FG = "#c4d1de"
MUTED_FG = "#8ea1b3"
ACCENT_BG = "#2f81f7"
ACCENT_ACTIVE_BG = "#4c9aff"
BUTTON_BG = "#243140"
BUTTON_ACTIVE_BG = "#32465a"
BUTTON_FG = "#f3f7fb"
LINK_BG = PANEL_BG
LINK_FG = "#66b3ff"
LINK_DISABLED_FG = "#6f8191"
IMAGE_FILE_SUFFIXES = {".exr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".iff"}


@dataclass
class AppConfig:
    mayapy_path: str = r"C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe"
    project_root: str = r"D:\path\to\project"
    step1_path: str = r"D:\path\to\MSL_batch_Arena\step1_export_shot.py"
    step2_path: str = r"D:\path\to\MSL_batch_Arena\step2_build_arena.py"
    step3_path: str = r"D:\path\to\MSL_batch_Arena\step3_submit_deadline.py"
    arena_scene: str = r"D:\path\to\Arena_Light_setC_v001.ma"
    json_note: str = ""
    extra_step1_args: str = ""
    extra_step2_args: str = ""
    extra_step3_args: str = ""
    step2_custom1: str = "auto"
    step3_custom_name2: str = "lighting"


@dataclass
class ShotTargets:
    shot_root: Path
    maya_auto_dir: Path
    latest_maya_file: Path | None
    lighting_dir: Path
    latest_image_dir: Path | None
    latest_image_file: Path | None


def load_config() -> AppConfig:
    config_path = get_read_config_path()
    if not config_path.exists():
        return AppConfig()

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return AppConfig()

    data = asdict(AppConfig())
    if "version_note" in raw and "json_note" not in raw:
        raw["json_note"] = raw["version_note"]
    data.update({key: value for key, value in raw.items() if key in data})
    return AppConfig(**data)


def get_primary_config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / CONFIG_FILENAME
    return APP_DIR / CONFIG_FILENAME


def get_fallback_config_path() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "MSL_Batch_Arena_GUI" / CONFIG_FILENAME
    return APP_DIR / CONFIG_FILENAME


def get_read_config_path() -> Path:
    primary = get_primary_config_path()
    if primary.exists():
        return primary

    fallback = get_fallback_config_path()
    if fallback.exists():
        return fallback

    return primary


def save_config(config: AppConfig) -> Path:
    payload = json.dumps(asdict(config), indent=2, ensure_ascii=False)
    primary = get_primary_config_path()

    try:
        primary.parent.mkdir(parents=True, exist_ok=True)
        primary.write_text(payload, encoding="utf-8")
        return primary
    except OSError:
        fallback = get_fallback_config_path()
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text(payload, encoding="utf-8")
        return fallback


def parse_shotcodes(raw_text: str) -> list[str]:
    tokens = []
    for line in raw_text.replace(",", " ").splitlines():
        tokens.extend(piece.strip() for piece in line.split())
    return [token for token in tokens if token]


def parse_extra_args(raw_text: str) -> list[str]:
    if not raw_text.strip():
        return []
    return shlex.split(raw_text, posix=False)


def build_shot_targets(project_root: str, shotcode: str, step2_custom1: str = "auto", step3_custom_name2: str = "lighting") -> ShotTargets | None:
    parts = shotcode.split("_")
    if len(parts) < 3:
        return None

    seq = parts[1]
    shot_root = Path(project_root) / "shots" / seq / shotcode
    maya_auto_dir = shot_root / "maya" / "lighting" / (step2_custom1.strip() or "auto") / "v001"
    lighting_dir = shot_root / "images" / "3d_renders" / (step3_custom_name2.strip() or "lighting")

    return ShotTargets(
        shot_root=shot_root,
        maya_auto_dir=maya_auto_dir,
        latest_maya_file=find_latest_auto_maya_file(maya_auto_dir, shotcode, step2_custom1),
        lighting_dir=lighting_dir,
        latest_image_dir=find_latest_version_dir(lighting_dir),
        latest_image_file=find_latest_image_file(lighting_dir),
    )


def build_scene_name_tag(step2_custom1: str) -> str:
    custom1 = step2_custom1.strip()
    if not custom1 or custom1 == "auto":
        return "light"
    if custom1.startswith("auto_"):
        custom1 = custom1[len("auto_"):]
    return custom1


def find_latest_auto_maya_file(auto_dir: Path, shotcode: str, step2_custom1: str) -> Path | None:
    if not auto_dir.exists():
        return None

    scene_name_tag = build_scene_name_tag(step2_custom1)
    version_re = re.compile(
        rf"MSL_{re.escape(shotcode)}_{re.escape(scene_name_tag)}_v(\d+)_auto\.(ma|mb)$",
        re.IGNORECASE,
    )
    candidates: list[tuple[int, Path]] = []
    for path in auto_dir.iterdir():
        if not path.is_file():
            continue
        match = version_re.match(path.name)
        if match:
            candidates.append((int(match.group(1)), path))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1].name.lower()))
    return candidates[-1][1]


def find_latest_version_dir(base_dir: Path) -> Path | None:
    if not base_dir.exists():
        return None

    version_re = re.compile(r"^v(\d+)", re.IGNORECASE)
    candidates: list[tuple[int, Path]] = []
    for path in base_dir.iterdir():
        if not path.is_dir():
            continue
        match = version_re.match(path.name)
        if match:
            candidates.append((int(match.group(1)), path))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1].name.lower()))
    return candidates[-1][1]


def find_latest_image_file(lighting_dir: Path) -> Path | None:
    latest_dir = find_latest_version_dir(lighting_dir)
    if latest_dir is None or not latest_dir.exists():
        return None

    image_files = [
        path for path in latest_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_FILE_SUFFIXES
    ]
    if not image_files:
        return None

    image_files.sort(key=lambda path: (path.stat().st_mtime, str(path).lower()))
    return image_files[-1]


class BatchRunner:
    def __init__(self, config: AppConfig, shotcodes: list[str], enabled_steps: list[str]):
        self.config = config
        self.shotcodes = shotcodes
        self.enabled_steps = enabled_steps
        self.process: subprocess.Popen[str] | None = None
        self.stop_requested = False

    def validate(self) -> list[str]:
        errors = []
        required = {
            "mayapy_path": "Mayapy path",
            "project_root": "Project root",
            "step1_path": "Step 1 script",
            "step2_path": "Step 2 script",
            "step3_path": "Step 3 script",
        }
        if "step2" in self.enabled_steps:
            required["arena_scene"] = "Arena scene"

        for field_name, label in required.items():
            value = getattr(self.config, field_name).strip()
            if not value:
                errors.append(f"{label} is required.")

        if not self.shotcodes:
            errors.append("At least one shotcode is required.")

        if not self.enabled_steps:
            errors.append("Select at least one step.")
        return errors

    def build_commands(self) -> list[tuple[str, list[str]]]:
        commands: list[tuple[str, list[str]]] = []
        steps = {
            "step1": (self.config.step1_path, parse_extra_args(self.config.extra_step1_args)),
            "step2": (self.config.step2_path, parse_extra_args(self.config.extra_step2_args)),
            "step3": (self.config.step3_path, parse_extra_args(self.config.extra_step3_args)),
        }

        for step_name in ["step1", "step2", "step3"]:
            if step_name not in self.enabled_steps:
                continue

            script_path, extra_args = steps[step_name]
            command = [
                self.config.mayapy_path,
                script_path,
                "--project",
                self.config.project_root,
                "--shotcodes",
                *self.shotcodes,
            ]
            if step_name == "step2":
                command.extend(["--arena", self.config.arena_scene])
                if self.config.json_note.strip():
                    command.extend(["--version-note", self.config.json_note.strip()])
                command.extend(["--maya-subdir", self.config.step2_custom1.strip() or "auto"])
            elif step_name == "step3":
                command.extend(["--maya-subdir", self.config.step2_custom1.strip() or "auto"])
                command.extend(["--render-subdir", self.config.step3_custom_name2.strip() or "lighting"])
                command.append("--render-version-no-suffix")
            command.extend(extra_args)
            commands.append((step_name, command))
        return commands

    def stop(self) -> None:
        self.stop_requested = True
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def run(
        self,
        on_log,
        on_step_changed,
        on_finished,
    ) -> None:
        try:
            commands = self.build_commands()
            total = len(commands)
            for index, (step_name, command) in enumerate(commands, start=1):
                if self.stop_requested:
                    on_log("Run stopped before next step.\n")
                    on_finished(False)
                    return

                on_step_changed(step_name, index, total)
                on_log(f"\n[{step_name}] {subprocess.list2cmdline(command)}\n")
                child_env = os.environ.copy()
                # Maya's embedded Python may inherit a cp950 console encoding on
                # Traditional Chinese Windows, which crashes on unicode symbols
                # like checkmarks printed by the batch scripts. Force UTF-8 for
                # stdio so those scripts can log safely.
                child_env["PYTHONIOENCODING"] = "utf-8"
                child_env["PYTHONUTF8"] = "1"
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=child_env,
                )

                assert self.process.stdout is not None
                for line in self.process.stdout:
                    on_log(line)

                return_code = self.process.wait()
                self.process = None

                if self.stop_requested:
                    on_log(f"[{step_name}] Stopped by user.\n")
                    on_finished(False)
                    return

                if return_code != 0:
                    on_log(f"[{step_name}] Failed with exit code {return_code}.\n")
                    on_finished(False)
                    return

                on_log(f"[{step_name}] Completed.\n")

            on_finished(True)
        except Exception as exc:
            on_log(f"\n[ERROR] {exc}\n")
            on_finished(False)


class BatchArenaGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1280x860")
        self.root.minsize(1100, 760)

        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.runner: BatchRunner | None = None
        self.worker: threading.Thread | None = None

        self.config_vars: dict[str, tk.StringVar] = {}
        self.config_entries: dict[str, tk.Entry] = {}
        self.link_labels: dict[str, tk.Label] = {}
        self.link_buttons: dict[str, ttk.Button] = {}
        self.link_targets: dict[str, Path | None] = {}
        self.step_vars = {
            "step1": tk.BooleanVar(value=True),
            "step2": tk.BooleanVar(value=True),
            "step3": tk.BooleanVar(value=True),
        }
        self.status_var = tk.StringVar(value="Ready")
        self.selected_shot_var = tk.StringVar(value="No shot selected")
        self.ui_font_size = tk.IntVar(value=9)
        self.font_size_label_var = tk.StringVar(value="")
        self.ui_font = tkfont.Font(family="Segoe UI", size=9)
        self.panel_title_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.mono_font = tkfont.Font(family="Consolas", size=9)
        self.link_font = tkfont.Font(family="Segoe UI", size=8, underline=True)
        self.shot_menu = tk.Menu(
            self.root,
            tearoff=False,
            bg=PANEL_BG,
            fg=TEXT_FG,
            activebackground=ACCENT_BG,
            activeforeground="#ffffff",
        )

        self._build_style()
        self._build_layout()
        self._apply_font_size()
        self._load_initial_config()
        self.root.bind("<Control-minus>", lambda _event: self._change_font_size(-1))
        self.root.bind("<Control-equal>", lambda _event: self._change_font_size(1))
        self.root.bind("<Control-plus>", lambda _event: self._change_font_size(1))
        self.root.after(150, self.shot_text.focus_set)
        self._schedule_queue_poll()

    def _build_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        self.root.configure(bg=ROOT_BG)
        style.configure("Root.TFrame", background=ROOT_BG)
        style.configure("Panel.TFrame", background=PANEL_BG)
        style.configure(
            "Panel.TLabelframe",
            background=PANEL_BG,
            borderwidth=1,
            relief="solid",
            bordercolor=PANEL_BORDER,
            lightcolor=PANEL_BORDER,
            darkcolor=PANEL_BORDER,
        )
        style.configure("Panel.TLabelframe.Label", background=PANEL_BG, foreground=LABEL_FG)
        style.configure("Panel.TLabelframe.Label", font=self.panel_title_font)
        style.configure("TLabel", background=ROOT_BG, foreground=LABEL_FG, font=self.ui_font)
        style.configure("Panel.TLabel", background=PANEL_BG, foreground=LABEL_FG, font=self.ui_font)
        style.configure(
            "TEntry",
            fieldbackground=TEXT_BG,
            foreground=TEXT_FG,
            background=TEXT_BG,
            insertcolor=TEXT_FG,
            bordercolor=PANEL_BORDER,
            lightcolor=PANEL_BORDER,
            darkcolor=PANEL_BORDER,
            font=self.ui_font,
        )
        style.map(
            "TEntry",
            fieldbackground=[("readonly", TEXT_BG)],
            foreground=[("readonly", TEXT_FG)],
        )
        style.configure(
            "Soft.TButton",
            padding=(7, 4),
            background=BUTTON_BG,
            foreground=BUTTON_FG,
            bordercolor=PANEL_BORDER,
            lightcolor=PANEL_BORDER,
            darkcolor=PANEL_BORDER,
            font=self.ui_font,
        )
        style.map(
            "Soft.TButton",
            background=[("active", BUTTON_ACTIVE_BG), ("pressed", BUTTON_ACTIVE_BG)],
            foreground=[("disabled", MUTED_FG)],
        )
        style.configure(
            "Tiny.TButton",
            padding=(4, 2),
            background=BUTTON_BG,
            foreground=BUTTON_FG,
            bordercolor=PANEL_BORDER,
            lightcolor=PANEL_BORDER,
            darkcolor=PANEL_BORDER,
            font=self.ui_font,
        )
        style.map(
            "Tiny.TButton",
            background=[("active", BUTTON_ACTIVE_BG), ("pressed", BUTTON_ACTIVE_BG)],
            foreground=[("disabled", MUTED_FG)],
        )
        style.configure(
            "Accent.TButton",
            padding=(9, 5),
            background=ACCENT_BG,
            foreground="#ffffff",
            bordercolor=ACCENT_BG,
            lightcolor=ACCENT_BG,
            darkcolor=ACCENT_BG,
            font=self.ui_font,
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_ACTIVE_BG), ("pressed", ACCENT_ACTIVE_BG)],
            foreground=[("disabled", MUTED_FG)],
        )
        style.configure("TCheckbutton", background=PANEL_BG, foreground=LABEL_FG, font=self.ui_font)
        style.map(
            "TCheckbutton",
            background=[("active", PANEL_BG)],
            foreground=[("disabled", MUTED_FG)],
        )
        style.configure("Status.TLabel", background=PANEL_BG, foreground=TEXT_FG)

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=16, style="Root.TFrame")
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=7)
        container.columnconfigure(1, weight=5)
        container.rowconfigure(0, weight=1)

        left = ttk.Frame(container, style="Root.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.rowconfigure(0, weight=4)
        left.rowconfigure(1, weight=2)
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(container, style="Root.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=0)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(2, weight=0)
        right.columnconfigure(0, weight=1)

        self._build_shot_panel(left)
        self._build_links_panel(left)
        self._build_paths_panel(right)
        self._build_log_panel(right)
        self._build_action_panel(right)

    def _build_paths_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Pipeline Setup", padding=12, style="Panel.TLabelframe")
        panel.grid(row=0, column=0, sticky="ew")
        panel.columnconfigure(1, weight=1)

        field_specs = [
            ("mayapy_path", "Mayapy", "file", [("Executable", "*.exe"), ("All Files", "*.*")]),
            ("project_root", "Project Root", "directory", None),
            ("step1_path", "Step 1 Script", "file", [("Python", "*.py"), ("All Files", "*.*")]),
            ("step2_path", "Step 2 Script", "file", [("Python", "*.py"), ("All Files", "*.*")]),
            ("step3_path", "Step 3 Script", "file", [("Python", "*.py"), ("All Files", "*.*")]),
            ("arena_scene", "Arena Scene", "file", [("Maya Scene", "*.ma *.mb"), ("All Files", "*.*")]),
            ("json_note", "Step 2 JSON Note", "text", None),
            ("step2_custom1", "Step 2 Custom1", "text", None),
            ("step3_custom_name2", "Step 3 Custom Name2", "text", None),
            ("extra_step1_args", "Step 1 Extra Args", "text", None),
            ("extra_step2_args", "Step 2 Extra Args", "text", None),
            ("extra_step3_args", "Step 3 Extra Args", "text", None),
        ]

        for row, (name, label, kind, filetypes) in enumerate(field_specs):
            ttk.Label(panel, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
            var = tk.StringVar()
            self.config_vars[name] = var
            if name in {"project_root", "step2_custom1", "step3_custom_name2"}:
                var.trace_add("write", lambda *_args: self._update_selected_shot_links())
            entry = tk.Entry(
                panel,
                textvariable=var,
                font=self.ui_font,
                bg=TEXT_BG,
                fg=TEXT_FG,
                insertbackground=TEXT_FG,
                relief="solid",
                borderwidth=1,
                highlightthickness=1,
                highlightbackground=PANEL_BORDER,
                highlightcolor=ACCENT_BG,
            )
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            entry.bind("<Button-1>", self._focus_entry, add="+")
            entry.bind("<Control-a>", self._select_all_entry, add="+")
            entry.bind("<Control-A>", self._select_all_entry, add="+")
            self.config_entries[name] = entry
            if kind != "text":
                ttk.Button(
                    panel,
                    text="Browse",
                    style="Tiny.TButton",
                    width=7,
                    command=lambda n=name, k=kind, f=filetypes: self._browse_into(n, k, f),
                ).grid(row=row, column=2, sticky="w", padx=(8, 0), pady=4)

        ttk.Button(panel, text="Save Config", style="Accent.TButton", command=self.save_current_config).grid(
            row=len(field_specs),
            column=2,
            sticky="e",
            padx=(8, 0),
            pady=(10, 0),
        )

    def _build_shot_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Shot Batch", padding=12, style="Panel.TLabelframe")
        panel.grid(row=0, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(3, weight=3)
        panel.rowconfigure(5, weight=2)

        step_row = ttk.Frame(panel, style="Panel.TFrame")
        step_row.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ttk.Checkbutton(step_row, text="Step 1 Export", variable=self.step_vars["step1"]).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(step_row, text="Step 2 Build Arena", variable=self.step_vars["step2"]).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(step_row, text="Step 3 Submit Deadline", variable=self.step_vars["step3"]).pack(side="left")

        input_header = ttk.Frame(panel, style="Panel.TFrame")
        input_header.grid(row=1, column=0, sticky="ew")
        input_header.columnconfigure(0, weight=1)

        ttk.Label(input_header, text="Shotcode Input", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        button_row = ttk.Frame(input_header, style="Panel.TFrame")
        button_row.grid(row=0, column=1, sticky="e")
        ttk.Button(button_row, text="Paste", style="Tiny.TButton", width=6, command=self._paste_into_shot_text).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(button_row, text="Clear", style="Tiny.TButton", width=6, command=self._clear_shot_text).pack(side="left")

        ttk.Label(
            panel,
            text="One per line, or paste space/comma separated values.",
            style="Panel.TLabel",
        ).grid(row=2, column=0, sticky="nw", pady=(6, 0))

        input_frame = ttk.Frame(panel, style="Panel.TFrame")
        input_frame.grid(row=3, column=0, sticky="nsew", pady=(8, 10))
        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(0, weight=1)

        self.shot_text = tk.Text(
            input_frame,
            height=6,
            wrap="word",
            font=self.mono_font,
            bg=TEXT_BG,
            fg=TEXT_FG,
            insertbackground=TEXT_FG,
            selectbackground=ACCENT_BG,
            selectforeground="#ffffff",
            relief="solid",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=PANEL_BORDER,
            highlightcolor=ACCENT_BG,
            padx=8,
            pady=8,
        )
        self.shot_text.grid(row=0, column=0, sticky="nsew")
        shot_scrollbar = ttk.Scrollbar(input_frame, orient="vertical", command=self.shot_text.yview)
        shot_scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self.shot_text.configure(yscrollcommand=shot_scrollbar.set)
        self.shot_text.bind("<<Modified>>", self._on_shot_text_changed)
        self.shot_text.bind("<Button-1>", self._focus_shot_text, add="+")
        self.shot_text.bind("<Control-v>", self._paste_into_shot_text)
        self.shot_text.bind("<Control-V>", self._paste_into_shot_text)
        self.shot_text.bind("<Shift-Insert>", self._paste_into_shot_text)
        self.shot_text.bind("<Control-a>", self._select_all_shot_text)
        self.shot_text.bind("<Control-A>", self._select_all_shot_text)
        self.shot_text.bind("<Button-3>", self._show_shot_menu, add="+")

        preview_frame = ttk.Frame(panel, style="Panel.TFrame")
        preview_frame.grid(row=5, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(1, weight=1)

        ttk.Label(preview_frame, text="Parsed Shotcodes", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        list_frame = ttk.Frame(preview_frame, style="Panel.TFrame")
        list_frame.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.shot_list = tk.Listbox(
            list_frame,
            height=6,
            font=self.mono_font,
            bg=TEXT_BG,
            fg=TEXT_FG,
            selectbackground=ACCENT_BG,
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground=PANEL_BORDER,
            highlightcolor=ACCENT_BG,
        )
        self.shot_list.grid(row=0, column=0, sticky="nsew")
        shot_list_scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.shot_list.yview)
        shot_list_scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self.shot_list.configure(yscrollcommand=shot_list_scrollbar.set)
        self.shot_list.bind("<<ListboxSelect>>", self._on_shot_list_selected)

    def _build_links_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Shot Links", padding=12, style="Panel.TLabelframe")
        panel.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        panel.columnconfigure(1, weight=1)
        panel.columnconfigure(2, weight=0)

        ttk.Label(panel, text="Selected Shot", style="Panel.TLabel").grid(row=0, column=0, sticky="w", pady=3, padx=(0, 10))
        ttk.Label(panel, textvariable=self.selected_shot_var, style="Panel.TLabel").grid(row=0, column=1, sticky="w", pady=3)
        ttk.Button(panel, text="Refresh", style="Tiny.TButton", command=self._update_selected_shot_links).grid(
            row=0,
            column=2,
            sticky="e",
            pady=3,
        )

        link_rows = [
            ("shot_root", "Shot Root"),
            ("maya_auto_dir", "Maya Auto Folder"),
            ("latest_maya_file", "Latest Auto Maya"),
            ("lighting_dir", "Render Images Root"),
            ("latest_image_dir", "Latest Image Version"),
            ("latest_image_file", "Latest Image File"),
        ]

        for row, (key, label_text) in enumerate(link_rows, start=1):
            ttk.Label(panel, text=label_text, style="Panel.TLabel").grid(row=row, column=0, sticky="nw", pady=3, padx=(0, 10))
            link = tk.Label(
                panel,
                text="(not found)",
                fg=LINK_DISABLED_FG,
                bg=LINK_BG,
                cursor="arrow",
                anchor="w",
                justify="left",
                font=self.link_font,
                padx=4,
                pady=2,
                wraplength=520,
            )
            link.grid(row=row, column=1, sticky="ew", pady=3)
            link.bind("<Button-1>", lambda _event, target_key=key: self._open_link_target(target_key))
            button = ttk.Button(
                panel,
                text="Open",
                style="Tiny.TButton",
                command=lambda target_key=key: self._open_link_target(target_key),
            )
            button.grid(row=row, column=2, sticky="e", pady=3, padx=(8, 0))
            self.link_labels[key] = link
            self.link_buttons[key] = button
            self.link_targets[key] = None

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Execution Log", padding=12, style="Panel.TLabelframe")
        panel.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        ttk.Label(panel, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")

        self.log_text = tk.Text(
            panel,
            wrap="word",
            state="disabled",
            font=self.mono_font,
            bg=TEXT_BG,
            fg=TEXT_FG,
            insertbackground=TEXT_FG,
            selectbackground=ACCENT_BG,
            selectforeground="#ffffff",
            relief="solid",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=PANEL_BORDER,
            highlightcolor=ACCENT_BG,
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

    def _build_action_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Actions", padding=12, style="Panel.TLabelframe")
        panel.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        panel.columnconfigure(0, weight=1)

        font_row = ttk.Frame(panel, style="Panel.TFrame")
        font_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(font_row, text="Text Size", style="Panel.TLabel").pack(side="left")
        ttk.Button(font_row, text="A-", style="Tiny.TButton", width=4, command=lambda: self._change_font_size(-1)).pack(
            side="left", padx=(16, 8)
        )
        ttk.Label(font_row, textvariable=self.font_size_label_var, style="Panel.TLabel").pack(side="left", padx=8)
        ttk.Button(font_row, text="A+", style="Tiny.TButton", width=4, command=lambda: self._change_font_size(1)).pack(
            side="left", padx=(8, 0)
        )

        ttk.Button(panel, text="Preview Commands", style="Soft.TButton", command=self.preview_commands).grid(
            row=1, column=0, sticky="ew", pady=(0, 8)
        )
        ttk.Button(panel, text="Run Selected Steps", style="Accent.TButton", command=self.run_pipeline).grid(
            row=2, column=0, sticky="ew", pady=(0, 8)
        )
        ttk.Button(panel, text="Stop", style="Soft.TButton", command=self.stop_pipeline).grid(
            row=3, column=0, sticky="ew"
        )

    def _load_initial_config(self) -> None:
        config = load_config()
        for field in fields(AppConfig):
            if field.name in self.config_vars:
                self.config_vars[field.name].set(getattr(config, field.name))
        self._update_selected_shot_links()

    def _browse_into(self, target_name: str, kind: str, filetypes) -> None:
        current = self.config_vars[target_name].get().strip()
        initial_dir = str(Path(current).parent) if current else str(APP_DIR)
        if kind == "directory":
            selected = filedialog.askdirectory(initialdir=initial_dir)
        else:
            selected = filedialog.askopenfilename(initialdir=initial_dir, filetypes=filetypes)
        if selected:
            self.config_vars[target_name].set(selected)
            if target_name == "project_root":
                self._update_selected_shot_links()

    def _on_shot_text_changed(self, _event=None) -> None:
        if not self.shot_text.edit_modified():
            return
        self.shot_text.edit_modified(False)
        shotcodes = parse_shotcodes(self.shot_text.get("1.0", "end"))
        selected_shot = self._get_selected_shotcode()
        self.shot_list.delete(0, "end")
        for shotcode in shotcodes:
            self.shot_list.insert("end", shotcode)
        if shotcodes:
            selected_index = shotcodes.index(selected_shot) if selected_shot in shotcodes else 0
            self.shot_list.selection_set(selected_index)
            self.shot_list.activate(selected_index)
            self.shot_list.see(selected_index)
        self._update_selected_shot_links()

    def _on_shot_list_selected(self, _event=None) -> None:
        self._update_selected_shot_links()

    def _focus_shot_text(self, _event=None) -> None:
        self.shot_text.focus_set()

    def _focus_entry(self, event) -> None:
        event.widget.focus_set()

    def _select_all_entry(self, event) -> str:
        widget = event.widget
        widget.focus_set()
        widget.selection_range(0, "end")
        widget.icursor("end")
        return "break"

    def _paste_into_shot_text(self, _event=None) -> str:
        try:
            clipboard_text = self.root.clipboard_get()
        except tk.TclError:
            return "break"

        self.shot_text.focus_set()
        self.shot_text.insert("insert", clipboard_text)
        self.shot_text.see("insert")
        return "break"

    def _clear_shot_text(self) -> None:
        self.shot_text.delete("1.0", "end")
        self.shot_text.focus_set()

    def _select_all_shot_text(self, _event=None) -> str:
        self.shot_text.focus_set()
        self.shot_text.tag_add("sel", "1.0", "end-1c")
        self.shot_text.mark_set("insert", "1.0")
        self.shot_text.see("insert")
        return "break"

    def _show_shot_menu(self, event) -> str:
        self.shot_text.focus_set()
        self.shot_menu.delete(0, "end")
        self.shot_menu.add_command(label="Paste", command=self._paste_into_shot_text)
        self.shot_menu.add_command(label="Select All", command=self._select_all_shot_text)
        self.shot_menu.add_separator()
        self.shot_menu.add_command(label="Clear", command=lambda: self.shot_text.delete("1.0", "end"))
        self.shot_menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _get_selected_shotcode(self) -> str | None:
        selection = self.shot_list.curselection()
        if not selection:
            return None
        return self.shot_list.get(selection[0])

    def _update_selected_shot_links(self) -> None:
        shotcode = self._get_selected_shotcode()
        if not shotcode:
            self.selected_shot_var.set("No shot selected")
            for key in self.link_labels:
                self._set_link_target(key, None)
            return

        self.selected_shot_var.set(shotcode)
        targets = build_shot_targets(
            self.config_vars["project_root"].get().strip(),
            shotcode,
            self.config_vars["step2_custom1"].get().strip() or "auto",
            self.config_vars["step3_custom_name2"].get().strip() or "lighting",
        )
        if targets is None:
            for key in self.link_labels:
                self._set_link_target(key, None)
            return

        self._set_link_target("shot_root", targets.shot_root)
        self._set_link_target("maya_auto_dir", targets.maya_auto_dir)
        self._set_link_target("latest_maya_file", targets.latest_maya_file)
        self._set_link_target("lighting_dir", targets.lighting_dir)
        self._set_link_target("latest_image_dir", targets.latest_image_dir)
        self._set_link_target("latest_image_file", targets.latest_image_file)

    def _set_link_target(self, key: str, path: Path | None) -> None:
        label = self.link_labels[key]
        button = self.link_buttons[key]
        self.link_targets[key] = path
        if path is None:
            label.configure(text="(not found)", fg=LINK_DISABLED_FG, cursor="arrow")
            button.state(["disabled"])
            return

        if path.exists():
            label.configure(text=str(path), fg=LINK_FG, cursor="hand2")
            button.state(["!disabled"])
            return

        label.configure(text=f"{path}  [missing]", fg=LINK_DISABLED_FG, cursor="arrow")
        button.state(["!disabled"])

    def _find_existing_ancestor(self, path: Path) -> Path | None:
        current = path
        while True:
            if current.exists():
                return current
            if current.parent == current:
                return None
            current = current.parent

    def _open_link_target(self, key: str) -> None:
        path = self.link_targets.get(key)
        if path is None:
            self.status_var.set(f"{key}: no target")
            return

        if not path.exists():
            fallback = self._find_existing_ancestor(path)
            if fallback is None:
                messagebox.showwarning(APP_TITLE, f"Path does not exist:\n{path}")
                self.status_var.set(f"{key}: missing path")
                return
            path = fallback
            self.status_var.set(f"{key}: opened nearest existing path")
            messagebox.showwarning(
                APP_TITLE,
                f"Original path is missing.\n\nOpening nearest existing path instead:\n{path}",
            )

        try:
            open_target = path.parent if path.is_file() else path
            os.startfile(open_target)
            self.status_var.set(f"Opened: {open_target}")
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Cannot open path:\n{path}\n\n{exc}")

    def _apply_font_size(self) -> None:
        size = max(8, min(20, self.ui_font_size.get()))
        self.ui_font_size.set(size)
        self.font_size_label_var.set(f"{size} pt")
        self.ui_font.configure(size=size)
        self.panel_title_font.configure(size=size + 1)
        self.mono_font.configure(size=size)
        self.link_font.configure(size=max(8, size - 1))

    def _change_font_size(self, delta: int) -> None:
        self.ui_font_size.set(self.ui_font_size.get() + delta)
        self._apply_font_size()

    def _schedule_queue_poll(self) -> None:
        self._drain_queue()
        self.root.after(120, self._schedule_queue_poll)

    def _drain_queue(self) -> None:
        while True:
            try:
                event, payload = self.queue.get_nowait()
            except queue.Empty:
                return

            if event == "log":
                self._append_log(str(payload))
            elif event == "step":
                step_name, index, total = payload
                self.status_var.set(f"Running {step_name} ({index}/{total})")
            elif event == "finished":
                success = bool(payload)
                self.status_var.set("Completed" if success else "Stopped / Failed")
                if success:
                    messagebox.showinfo(APP_TITLE, "Batch pipeline finished.")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _collect_config(self) -> AppConfig:
        data = {name: var.get() for name, var in self.config_vars.items()}
        return AppConfig(**data)

    def _collect_runner(self) -> BatchRunner:
        config = self._collect_config()
        shotcodes = parse_shotcodes(self.shot_text.get("1.0", "end"))
        enabled_steps = [name for name, var in self.step_vars.items() if var.get()]
        return BatchRunner(config, shotcodes, enabled_steps)

    def save_current_config(self) -> None:
        save_path = save_config(self._collect_config())
        self.status_var.set(f"Config saved: {save_path}")

    def preview_commands(self) -> None:
        runner = self._collect_runner()
        errors = runner.validate()
        if errors:
            messagebox.showerror(APP_TITLE, "\n".join(errors))
            return

        self._append_log("\n=== Command Preview ===\n")
        for step_name, command in runner.build_commands():
            self._append_log(f"[{step_name}] {subprocess.list2cmdline(command)}\n")
        self._append_log("=======================\n")

    def run_pipeline(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning(APP_TITLE, "A run is already in progress.")
            return

        self.save_current_config()
        self.runner = self._collect_runner()
        errors = self.runner.validate()
        if errors:
            messagebox.showerror(APP_TITLE, "\n".join(errors))
            return

        self.status_var.set("Starting")
        self._append_log("\n=== New Run ===\n")
        self.worker = threading.Thread(
            target=self.runner.run,
            kwargs={
                "on_log": lambda text: self.queue.put(("log", text)),
                "on_step_changed": lambda step_name, index, total: self.queue.put(
                    ("step", (step_name, index, total))
                ),
                "on_finished": lambda success: self.queue.put(("finished", success)),
            },
            daemon=True,
        )
        self.worker.start()

    def stop_pipeline(self) -> None:
        if self.runner:
            self.runner.stop()
            self.status_var.set("Stopping...")
            self._append_log("\n[INFO] Stop requested.\n")


def main() -> None:
    root = tk.Tk()
    BatchArenaGUI(root)
    root.mainloop()
