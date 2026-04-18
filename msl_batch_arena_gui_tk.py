import json
import queue
import shlex
import subprocess
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "msl_batch_arena_gui_config.json"
APP_TITLE = "MSL Batch Arena GUI"


@dataclass
class AppConfig:
    mayapy_path: str = r"C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe"
    project_root: str = r"X:\projects\2508_MASHLE"
    step1_path: str = r"W:\vy\efx\MSL_batch_Arena\step1_export_shot.py"
    step2_path: str = r"W:\vy\efx\MSL_batch_Arena\step2_build_arena.py"
    step3_path: str = r"W:\vy\efx\MSL_batch_Arena\step3_submit_deadline.py"
    arena_scene: str = (
        r"X:\projects\2508_MASHLE\assets\environment\Arena\work\scenes"
        r"\vincentyang\batch_Arena\Arena_Light_setC_v001.ma"
    )
    version_note: str = ""
    extra_step1_args: str = ""
    extra_step2_args: str = ""
    extra_step3_args: str = ""


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        return AppConfig()

    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return AppConfig()

    data = asdict(AppConfig())
    data.update({key: value for key, value in raw.items() if key in data})
    return AppConfig(**data)


def save_config(config: AppConfig) -> None:
    CONFIG_PATH.write_text(
        json.dumps(asdict(config), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def parse_shotcodes(raw_text: str) -> list[str]:
    tokens = []
    for line in raw_text.replace(",", " ").splitlines():
        tokens.extend(piece.strip() for piece in line.split())
    return [token for token in tokens if token]


def parse_extra_args(raw_text: str) -> list[str]:
    if not raw_text.strip():
        return []
    return shlex.split(raw_text, posix=False)


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
                if self.config.version_note.strip():
                    command.extend(["--version-note", self.config.version_note.strip()])
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
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
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
        self.step_vars = {
            "step1": tk.BooleanVar(value=True),
            "step2": tk.BooleanVar(value=True),
            "step3": tk.BooleanVar(value=True),
        }
        self.status_var = tk.StringVar(value="Ready")

        self._build_style()
        self._build_layout()
        self._load_initial_config()
        self._schedule_queue_poll()

    def _build_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        self.root.configure(bg="#f1efe8")
        style.configure("Root.TFrame", background="#f1efe8")
        style.configure("Panel.TLabelframe", background="#f7f5ee", borderwidth=1)
        style.configure("Panel.TLabelframe.Label", background="#f7f5ee", foreground="#253342")
        style.configure("Soft.TButton", padding=(10, 6))
        style.configure("Accent.TButton", padding=(12, 8))
        style.configure("Status.TLabel", background="#f1efe8", foreground="#253342")

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=16, style="Root.TFrame")
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=3)
        container.columnconfigure(1, weight=2)
        container.rowconfigure(0, weight=1)

        left = ttk.Frame(container, style="Root.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(container, style="Root.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        self._build_paths_panel(left)
        self._build_shot_panel(left)
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
            ("version_note", "Version Note", "text", None),
            ("extra_step1_args", "Extra Step 1 Args", "text", None),
            ("extra_step2_args", "Extra Step 2 Args", "text", None),
            ("extra_step3_args", "Extra Step 3 Args", "text", None),
        ]

        for row, (name, label, kind, filetypes) in enumerate(field_specs):
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
            var = tk.StringVar()
            self.config_vars[name] = var
            entry = ttk.Entry(panel, textvariable=var)
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            if kind != "text":
                ttk.Button(
                    panel,
                    text="Browse",
                    style="Soft.TButton",
                    command=lambda n=name, k=kind, f=filetypes: self._browse_into(n, k, f),
                ).grid(row=row, column=2, sticky="ew", padx=(8, 0), pady=4)

        ttk.Button(panel, text="Save Config", style="Accent.TButton", command=self.save_current_config).grid(
            row=len(field_specs),
            column=2,
            sticky="e",
            padx=(8, 0),
            pady=(10, 0),
        )

    def _build_shot_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Shot Batch", padding=12, style="Panel.TLabelframe")
        panel.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        step_row = ttk.Frame(panel, style="Root.TFrame")
        step_row.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ttk.Checkbutton(step_row, text="Step 1 Export", variable=self.step_vars["step1"]).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(step_row, text="Step 2 Build Arena", variable=self.step_vars["step2"]).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(step_row, text="Step 3 Submit Deadline", variable=self.step_vars["step3"]).pack(side="left")

        ttk.Label(
            panel,
            text="Shotcodes: one per line, or paste space/comma separated values.",
        ).grid(row=1, column=0, sticky="nw")

        self.shot_text = tk.Text(
            panel,
            height=10,
            wrap="word",
            font=("Consolas", 11),
            bg="#fffdfa",
            relief="solid",
            borderwidth=1,
        )
        self.shot_text.grid(row=2, column=0, sticky="nsew", pady=(8, 10))
        self.shot_text.bind("<<Modified>>", self._on_shot_text_changed)

        preview_frame = ttk.Frame(panel, style="Root.TFrame")
        preview_frame.grid(row=3, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)

        ttk.Label(preview_frame, text="Parsed Shotcodes").grid(row=0, column=0, sticky="w")
        self.shot_list = tk.Listbox(preview_frame, height=8, font=("Consolas", 11))
        self.shot_list.grid(row=1, column=0, sticky="nsew", pady=(6, 0))

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Execution Log", padding=12, style="Panel.TLabelframe")
        panel.grid(row=0, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        ttk.Label(panel, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")

        self.log_text = tk.Text(
            panel,
            wrap="word",
            state="disabled",
            font=("Consolas", 10),
            bg="#14212b",
            fg="#f3f2eb",
            insertbackground="#f3f2eb",
            relief="solid",
            borderwidth=1,
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

    def _build_action_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Actions", padding=12, style="Panel.TLabelframe")
        panel.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        panel.columnconfigure(0, weight=1)

        ttk.Button(panel, text="Preview Commands", style="Soft.TButton", command=self.preview_commands).grid(
            row=0, column=0, sticky="ew", pady=(0, 8)
        )
        ttk.Button(panel, text="Run Selected Steps", style="Accent.TButton", command=self.run_pipeline).grid(
            row=1, column=0, sticky="ew", pady=(0, 8)
        )
        ttk.Button(panel, text="Stop", style="Soft.TButton", command=self.stop_pipeline).grid(
            row=2, column=0, sticky="ew"
        )

    def _load_initial_config(self) -> None:
        config = load_config()
        for field in fields(AppConfig):
            self.config_vars[field.name].set(getattr(config, field.name))

    def _browse_into(self, target_name: str, kind: str, filetypes) -> None:
        current = self.config_vars[target_name].get().strip()
        initial_dir = str(Path(current).parent) if current else str(APP_DIR)
        if kind == "directory":
            selected = filedialog.askdirectory(initialdir=initial_dir)
        else:
            selected = filedialog.askopenfilename(initialdir=initial_dir, filetypes=filetypes)
        if selected:
            self.config_vars[target_name].set(selected)

    def _on_shot_text_changed(self, _event=None) -> None:
        if not self.shot_text.edit_modified():
            return
        self.shot_text.edit_modified(False)
        shotcodes = parse_shotcodes(self.shot_text.get("1.0", "end"))
        self.shot_list.delete(0, "end")
        for shotcode in shotcodes:
            self.shot_list.insert("end", shotcode)

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
        save_config(self._collect_config())
        self.status_var.set("Config saved")

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
