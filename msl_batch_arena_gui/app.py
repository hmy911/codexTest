import queue
import threading
from dataclasses import fields

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, Pretty, RichLog, Static, TextArea

from .config import APP_NAME, AppConfig, load_config, resource_path, save_config
from .runner import BatchRunner, parse_shotcodes


FIELD_ORDER = [
    ("mayapy_path", "Mayapy"),
    ("project_root", "Project Root"),
    ("source_scripts_root", "Source Scripts Root"),
    ("step1_path", "Step 1 Script"),
    ("step2_path", "Step 2 Script"),
    ("step3_path", "Step 3 Script"),
    ("arena_scene", "Arena Scene"),
    ("version_note", "Version Note"),
    ("extra_step1_args", "Extra Step 1 Args"),
    ("extra_step2_args", "Extra Step 2 Args"),
    ("extra_step3_args", "Extra Step 3 Args"),
]


class MessageScreen(ModalScreen[None]):
    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.title = title
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self.title, classes="dialog_title")
            yield Static(self.body, classes="dialog_body")
            yield Button("Close", variant="primary", id="dialog_close")

    @on(Button.Pressed, "#dialog_close")
    def close_dialog(self) -> None:
        self.dismiss(None)


class ArenaApp(App):
    CSS_PATH = str(resource_path("app.tcss"))
    BINDINGS = [
        ("f5", "run_pipeline", "Run"),
        ("f6", "preview_commands", "Preview"),
        ("f7", "save_config", "Save Config"),
        ("f8", "stop_pipeline", "Stop"),
        ("ctrl+c", "quit", "Quit"),
    ]

    class RunnerEvent(Message):
        def __init__(self, kind: str, payload) -> None:
            self.kind = kind
            self.payload = payload
            super().__init__()

    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.runner: BatchRunner | None = None
        self.worker_thread: threading.Thread | None = None
        self.event_queue: queue.Queue[tuple[str, object]] = queue.Queue()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="root"):
            with VerticalScroll(id="left"):
                yield Static("MSL_batch_Arena_GUI", id="hero")
                yield Static("Textual interface for the original step1 / step2 / step3 Maya pipeline.", classes="subtitle")
                with Vertical(id="config_panel", classes="panel"):
                    yield Label("Pipeline Setup", classes="panel_title")
                    for field_name, label in FIELD_ORDER:
                        yield Label(label, classes="field_label")
                        yield Input(value=getattr(self.config, field_name), id=field_name)

                with Vertical(id="shot_panel", classes="panel"):
                    yield Label("Shot Batch", classes="panel_title")
                    with Horizontal(classes="check_row"):
                        yield Checkbox("Step 1", value=True, id="enable_step1")
                        yield Checkbox("Step 2", value=True, id="enable_step2")
                        yield Checkbox("Step 3", value=True, id="enable_step3")
                    yield Label("Shotcodes", classes="field_label")
                    yield TextArea("", id="shotcodes")
                    yield Static("Parsed Shotcodes", classes="field_label")
                    yield Pretty([], id="shot_preview")

            with Vertical(id="right"):
                with Vertical(id="actions_panel", classes="panel"):
                    yield Label("Actions", classes="panel_title")
                    with Horizontal(classes="button_row"):
                        yield Button("Preview Commands", id="preview", variant="default")
                        yield Button("Run Selected Steps", id="run", variant="success")
                        yield Button("Save Config", id="save", variant="primary")
                        yield Button("Stop", id="stop", variant="warning")
                    yield Static("Ready", id="status")

                with Vertical(id="log_panel", classes="panel"):
                    yield Label("Execution Log", classes="panel_title")
                    yield RichLog(id="log", markup=False, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.15, self._drain_worker_events)
        self._refresh_shot_preview()

    def _collect_config(self) -> AppConfig:
        data = {}
        for field in fields(AppConfig):
            widget = self.query_one(f"#{field.name}", Input)
            data[field.name] = widget.value
        return AppConfig(**data)

    def _selected_steps(self) -> list[str]:
        selected = []
        if self.query_one("#enable_step1", Checkbox).value:
            selected.append("step1")
        if self.query_one("#enable_step2", Checkbox).value:
            selected.append("step2")
        if self.query_one("#enable_step3", Checkbox).value:
            selected.append("step3")
        return selected

    def _shotcode_text(self) -> str:
        return self.query_one("#shotcodes", TextArea).text

    def _refresh_shot_preview(self) -> None:
        shotcodes = parse_shotcodes(self._shotcode_text())
        self.query_one("#shot_preview", Pretty).update(shotcodes)

    def _append_log(self, message: str) -> None:
        self.query_one("#log", RichLog).write(message.rstrip("\n"))

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    @on(TextArea.Changed, "#shotcodes")
    def handle_shotcodes_changed(self) -> None:
        self._refresh_shot_preview()

    @on(Button.Pressed, "#save")
    def save_button(self) -> None:
        self.action_save_config()

    @on(Button.Pressed, "#preview")
    def preview_button(self) -> None:
        self.action_preview_commands()

    @on(Button.Pressed, "#run")
    def run_button(self) -> None:
        self.action_run_pipeline()

    @on(Button.Pressed, "#stop")
    def stop_button(self) -> None:
        self.action_stop_pipeline()

    def action_save_config(self) -> None:
        self.config = self._collect_config()
        save_config(self.config)
        self._set_status("Config saved")
        self._append_log("[info] Config saved.")

    def action_preview_commands(self) -> None:
        runner = BatchRunner(self._collect_config(), parse_shotcodes(self._shotcode_text()), self._selected_steps())
        errors = runner.validate()
        if errors:
            self.push_screen(MessageScreen("Validation Error", "\n".join(errors)))
            return

        self._append_log("=== Command Preview ===")
        for spec in runner.build_commands():
            self._append_log(f"[{spec.step_name}] {' '.join(spec.command)}")
        self._append_log("=======================")
        self._set_status("Preview generated")

    def action_run_pipeline(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            self.push_screen(MessageScreen("Busy", "A pipeline run is already in progress."))
            return

        self.action_save_config()
        self.runner = BatchRunner(self.config, parse_shotcodes(self._shotcode_text()), self._selected_steps())
        errors = self.runner.validate()
        if errors:
            self.push_screen(MessageScreen("Validation Error", "\n".join(errors)))
            return

        self._append_log("=== New Run ===")
        self._set_status("Starting")
        self.worker_thread = threading.Thread(target=self._run_in_thread, daemon=True)
        self.worker_thread.start()

    def action_stop_pipeline(self) -> None:
        if self.runner:
            self.runner.stop()
            self._set_status("Stopping...")
            self._append_log("[info] Stop requested.")

    def _run_in_thread(self) -> None:
        assert self.runner is not None
        self.runner.run(
            on_log=lambda text: self.event_queue.put(("log", text)),
            on_step_changed=lambda step_name, index, total: self.event_queue.put(
                ("step", (step_name, index, total))
            ),
            on_finished=lambda success: self.event_queue.put(("finished", success)),
        )

    def _drain_worker_events(self) -> None:
        while True:
            try:
                kind, payload = self.event_queue.get_nowait()
            except queue.Empty:
                return

            if kind == "log":
                self._append_log(str(payload))
            elif kind == "step":
                step_name, index, total = payload
                self._set_status(f"Running {step_name} ({index}/{total})")
            elif kind == "finished":
                success = bool(payload)
                self._set_status("Completed" if success else "Stopped / Failed")
                if success:
                    self.push_screen(MessageScreen("Finished", "Batch pipeline finished."))


def main() -> None:
    ArenaApp().run()
