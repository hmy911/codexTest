import shlex
import subprocess
from dataclasses import dataclass

from .config import AppConfig


def parse_shotcodes(raw_text: str) -> list[str]:
    tokens = []
    for line in raw_text.replace(",", " ").splitlines():
        tokens.extend(piece.strip() for piece in line.split())
    return [token for token in tokens if token]


def parse_extra_args(raw_text: str) -> list[str]:
    if not raw_text.strip():
        return []
    return shlex.split(raw_text, posix=False)


@dataclass
class CommandSpec:
    step_name: str
    command: list[str]


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

    def build_commands(self) -> list[CommandSpec]:
        commands: list[CommandSpec] = []
        step_map = {
            "step1": (self.config.step1_path, parse_extra_args(self.config.extra_step1_args)),
            "step2": (self.config.step2_path, parse_extra_args(self.config.extra_step2_args)),
            "step3": (self.config.step3_path, parse_extra_args(self.config.extra_step3_args)),
        }

        for step_name in ["step1", "step2", "step3"]:
            if step_name not in self.enabled_steps:
                continue

            script_path, extra_args = step_map[step_name]
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
            commands.append(CommandSpec(step_name=step_name, command=command))

        return commands

    def stop(self) -> None:
        self.stop_requested = True
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def run(self, on_log, on_step_changed, on_finished) -> None:
        try:
            commands = self.build_commands()
            total = len(commands)
            for index, spec in enumerate(commands, start=1):
                if self.stop_requested:
                    on_log("Run stopped before next step.\n")
                    on_finished(False)
                    return

                on_step_changed(spec.step_name, index, total)
                on_log(f"\n[{spec.step_name}] {subprocess.list2cmdline(spec.command)}\n")
                self.process = subprocess.Popen(
                    spec.command,
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
                    on_log(f"[{spec.step_name}] Stopped by user.\n")
                    on_finished(False)
                    return

                if return_code != 0:
                    on_log(f"[{spec.step_name}] Failed with exit code {return_code}.\n")
                    on_finished(False)
                    return

                on_log(f"[{spec.step_name}] Completed.\n")

            on_finished(True)
        except Exception as exc:
            on_log(f"\n[ERROR] {exc}\n")
            on_finished(False)
