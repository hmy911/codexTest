from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..config import AppConfig, load_config, save_config
from ..core.html_export import export_index_html
from ..core.scanner import ScanResult, scan_shotcodes
from ..core.thumbnail import create_tk_thumbnail
from ..core.utils import open_in_file_browser, open_with_default_app, parse_shotcodes


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


class QCViewerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MSL Render QC Viewer")
        self.geometry("1460x860")
        self.minsize(1200, 720)
        self.configure(bg=ROOT_BG)

        self.config_data = load_config()
        self.results: list[ScanResult] = []
        self.result_map: dict[str, ScanResult] = {}
        self.thumbnail_refs: dict[str, tk.PhotoImage] = {}
        self.preview_image_ref: tk.PhotoImage | None = None
        self.control_buttons: list[ttk.Button] = []
        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None

        self.project_root_var = tk.StringVar(value=self.config_data.project_root)
        self.status_var = tk.StringVar(value="Ready.")
        self.summary_var = tk.StringVar(value="No scan results yet.")

        self._configure_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._handle_close)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=ROOT_BG, foreground=TEXT_FG, fieldbackground=TEXT_BG)
        style.configure("Panel.TFrame", background=PANEL_BG, borderwidth=1, relief="solid")
        style.configure("Panel.TLabel", background=PANEL_BG, foreground=LABEL_FG)
        style.configure("Muted.TLabel", background=PANEL_BG, foreground=MUTED_FG)
        style.configure("Title.TLabel", background=PANEL_BG, foreground=TEXT_FG, font=("Segoe UI", 14, "bold"))
        style.configure("Action.TButton", background=BUTTON_BG, foreground=BUTTON_FG, padding=(12, 8))
        style.map("Action.TButton", background=[("active", BUTTON_ACTIVE_BG)])
        style.configure("Accent.TButton", background=ACCENT_BG, foreground=BUTTON_FG, padding=(14, 9))
        style.map("Accent.TButton", background=[("active", ACCENT_ACTIVE_BG)])
        style.configure("Treeview", background=TEXT_BG, foreground=TEXT_FG, fieldbackground=TEXT_BG, rowheight=76)
        style.configure("Treeview.Heading", background=PANEL_BG, foreground=LABEL_FG)
        style.map("Treeview", background=[("selected", ACCENT_BG)])

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, style="Panel.TFrame", padding=14)
        top.grid(row=0, column=0, sticky="nsew", padx=14, pady=(14, 8))
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=0)
        top.rowconfigure(3, weight=1)

        ttk.Label(top, text="MSL Render QC Viewer", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            top,
            text="Scan latest lighting renders, check beauty/crypto presence, preview thumbnails, and export HTML.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))

        root_row = ttk.Frame(top, style="Panel.TFrame", padding=0)
        root_row.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        root_row.columnconfigure(1, weight=1)
        ttk.Label(root_row, text="Project Root", style="Panel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.project_root_entry = ttk.Entry(root_row, textvariable=self.project_root_var)
        self.project_root_entry.grid(row=0, column=1, sticky="ew")
        browse_button = ttk.Button(root_row, text="Browse", style="Action.TButton", command=self._browse_project_root)
        browse_button.grid(row=0, column=2, padx=(10, 0))
        self.control_buttons.append(browse_button)

        ttk.Label(top, text="Shotcodes", style="Panel.TLabel").grid(row=3, column=0, sticky="w")
        self.shotcodes_text = tk.Text(
            top,
            height=6,
            bg=TEXT_BG,
            fg=TEXT_FG,
            insertbackground=TEXT_FG,
            relief="flat",
            wrap="word",
        )
        self.shotcodes_text.grid(row=4, column=0, sticky="ew", pady=(4, 12))
        if self.config_data.shotcodes_text:
            self.shotcodes_text.insert("1.0", self.config_data.shotcodes_text)

        controls = ttk.Frame(top, style="Panel.TFrame", padding=0)
        controls.grid(row=5, column=0, sticky="ew")
        self.scan_button = ttk.Button(controls, text="Scan Latest Versions", style="Accent.TButton", command=self._start_scan)
        self.scan_button.pack(side="left")
        self.export_button = ttk.Button(controls, text="Export index.html", style="Action.TButton", command=self._export_html)
        self.export_button.pack(side="left", padx=8)
        open_folder_button = ttk.Button(controls, text="Open Selected Folder", style="Action.TButton", command=self._open_selected_folder)
        open_folder_button.pack(side="left")
        open_image_button = ttk.Button(controls, text="Open Selected Image", style="Action.TButton", command=self._open_selected_image)
        open_image_button.pack(side="left", padx=(8, 0))
        self.control_buttons.extend([self.scan_button, self.export_button, open_folder_button, open_image_button])

        ttk.Label(top, textvariable=self.status_var, style="Muted.TLabel").grid(row=6, column=0, sticky="w", pady=(10, 0))

        body = ttk.PanedWindow(self, orient="horizontal")
        body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))

        table_panel = ttk.Frame(body, style="Panel.TFrame", padding=10)
        table_panel.columnconfigure(0, weight=1)
        table_panel.rowconfigure(1, weight=1)
        ttk.Label(table_panel, text="Results", style="Title.TLabel").grid(row=0, column=0, sticky="w")

        columns = ("status", "message", "latest_version")
        self.tree = ttk.Treeview(table_panel, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Shotcode")
        self.tree.heading("status", text="Status")
        self.tree.heading("message", text="Message")
        self.tree.heading("latest_version", text="Latest Version Path")
        self.tree.column("#0", width=220, stretch=False)
        self.tree.column("status", width=90, stretch=False, anchor="center")
        self.tree.column("message", width=300, stretch=True)
        self.tree.column("latest_version", width=620, stretch=True)
        self.tree.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.tree.bind("<<TreeviewSelect>>", self._handle_tree_selection)
        self.tree.bind("<Double-1>", lambda _event: self._open_selected_image())

        table_scroll = ttk.Scrollbar(table_panel, orient="vertical", command=self.tree.yview)
        table_scroll.grid(row=1, column=1, sticky="ns", pady=(10, 0))
        self.tree.configure(yscrollcommand=table_scroll.set)

        detail_panel = ttk.Frame(body, style="Panel.TFrame", padding=14)
        detail_panel.columnconfigure(0, weight=1)
        detail_panel.rowconfigure(2, weight=1)
        ttk.Label(detail_panel, text="Preview", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(detail_panel, textvariable=self.summary_var, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 10))

        self.preview_label = ttk.Label(detail_panel, text="Select a result to preview.", style="Panel.TLabel", anchor="center")
        self.preview_label.grid(row=2, column=0, sticky="nsew")

        self.detail_text = tk.Text(
            detail_panel,
            height=12,
            bg=TEXT_BG,
            fg=TEXT_FG,
            insertbackground=TEXT_FG,
            relief="flat",
            wrap="word",
            state="disabled",
        )
        self.detail_text.grid(row=3, column=0, sticky="ew", pady=(12, 12))

        detail_actions = ttk.Frame(detail_panel, style="Panel.TFrame", padding=0)
        detail_actions.grid(row=4, column=0, sticky="ew")
        detail_open_folder = ttk.Button(detail_actions, text="Open Folder", style="Action.TButton", command=self._open_selected_folder)
        detail_open_folder.pack(side="left")
        detail_open_image = ttk.Button(detail_actions, text="Open Image", style="Action.TButton", command=self._open_selected_image)
        detail_open_image.pack(side="left", padx=(8, 0))
        self.control_buttons.extend([detail_open_folder, detail_open_image])

        body.add(table_panel, weight=3)
        body.add(detail_panel, weight=2)

    def _browse_project_root(self) -> None:
        selected = filedialog.askdirectory(title="Select Project Root", initialdir=self.project_root_var.get() or None)
        if selected:
            self.project_root_var.set(selected)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.shotcodes_text.configure(state="normal" if enabled else "disabled")
        self.project_root_entry.state(["!disabled"] if enabled else ["disabled"])
        for button in self.control_buttons:
            button.state(["!disabled"] if enabled else ["disabled"])

    def _start_scan(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return

        project_root = self.project_root_var.get().strip()
        shotcodes = parse_shotcodes(self.shotcodes_text.get("1.0", "end"))
        if not project_root:
            messagebox.showwarning("Missing Project Root", "Please choose a project root.")
            return
        if not shotcodes:
            messagebox.showwarning("Missing Shotcodes", "Please enter at least one shotcode.")
            return

        self._persist_config()
        self.status_var.set(f"Scanning {len(shotcodes)} shot(s)...")
        self.summary_var.set("Scanning in progress...")
        self._set_controls_enabled(False)
        self.worker = threading.Thread(target=self._scan_worker, args=(project_root, shotcodes), daemon=True)
        self.worker.start()
        self.after(120, self._poll_queue)

    def _scan_worker(self, project_root: str, shotcodes: list[str]) -> None:
        try:
            results = scan_shotcodes(project_root, shotcodes)
            self.queue.put(("scan_complete", results))
        except Exception as exc:  # pragma: no cover - UI safeguard
            self.queue.put(("scan_error", exc))

    def _poll_queue(self) -> None:
        try:
            kind, payload = self.queue.get_nowait()
        except queue.Empty:
            if self.worker is not None and self.worker.is_alive():
                self.after(120, self._poll_queue)
            return

        self._set_controls_enabled(True)
        if kind == "scan_error":
            self.status_var.set("Scan failed.")
            self.summary_var.set("Scan failed.")
            messagebox.showerror("Scan Failed", str(payload))
            return

        assert kind == "scan_complete"
        self.results = list(payload)  # type: ignore[arg-type]
        self.result_map = {result.shotcode: result for result in self.results}
        self._refresh_tree()
        self._update_summary()
        self.status_var.set(f"Scan finished. {len(self.results)} shot(s) processed.")

    def _refresh_tree(self) -> None:
        self.thumbnail_refs.clear()
        self.tree.delete(*self.tree.get_children())
        for result in self.results:
            thumbnail = create_tk_thumbnail(result.thumbnail_source, result.status, result.shotcode)
            self.thumbnail_refs[result.shotcode] = thumbnail
            latest_path = str(result.latest_version_dir) if result.latest_version_dir else "-"
            self.tree.insert(
                "",
                "end",
                iid=result.shotcode,
                text=result.shotcode,
                image=thumbnail,
                values=(result.status, result.message, latest_path),
                tags=(result.status.lower(),),
            )

        self.tree.tag_configure("ok", foreground="#b7ffd8")
        self.tree.tag_configure("warn", foreground="#ffe6a0")
        self.tree.tag_configure("fail", foreground="#ffb8b5")
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])
            self._show_result(self.result_map[children[0]])
        else:
            self._clear_detail()

    def _update_summary(self) -> None:
        ok_count = sum(1 for result in self.results if result.status == "OK")
        warn_count = sum(1 for result in self.results if result.status == "WARN")
        fail_count = sum(1 for result in self.results if result.status == "FAIL")
        self.summary_var.set(f"Total {len(self.results)} | OK {ok_count} | WARN {warn_count} | FAIL {fail_count}")

    def _handle_tree_selection(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        selected = self._selected_result()
        if selected is None:
            self._clear_detail()
            return
        self._show_result(selected)

    def _selected_result(self) -> ScanResult | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.result_map.get(selection[0])

    def _show_result(self, result: ScanResult) -> None:
        self.preview_image_ref = create_tk_thumbnail(result.thumbnail_source, result.status, result.shotcode, max_size=(420, 236))
        self.preview_label.configure(image=self.preview_image_ref, text="")

        details = [
            f"Shotcode: {result.shotcode}",
            f"Sequence: {result.sequence or '-'}",
            f"Status: {result.status}",
            f"Message: {result.message}",
            f"Lighting Dir: {result.lighting_dir or '-'}",
            f"Latest Version: {result.latest_version_dir or '-'}",
            f"Representative Image: {result.representative_image or '-'}",
            f"Beauty Found: {'Yes' if result.beauty_found else 'No'}",
            f"Crypto Found: {'Yes' if result.crypto_found else 'No'}",
            f"Image Count: {result.image_count}",
        ]
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", "\n".join(details))
        self.detail_text.configure(state="disabled")

    def _clear_detail(self) -> None:
        self.preview_image_ref = None
        self.preview_label.configure(image="", text="Select a result to preview.")
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.configure(state="disabled")

    def _open_selected_folder(self) -> None:
        result = self._selected_result()
        if result is None:
            return
        open_in_file_browser(result.latest_version_dir or result.lighting_dir)

    def _open_selected_image(self) -> None:
        result = self._selected_result()
        if result is None or result.representative_image is None:
            return
        open_with_default_app(result.representative_image)

    def _export_html(self) -> None:
        if not self.results:
            messagebox.showinfo("No Results", "Run a scan before exporting HTML.")
            return

        initial_dir = self.config_data.last_export_dir or self.project_root_var.get().strip() or str(Path.cwd())
        output_path = filedialog.asksaveasfilename(
            title="Export index.html",
            defaultextension=".html",
            filetypes=[("HTML", "*.html")],
            initialdir=initial_dir,
            initialfile="index.html",
        )
        if not output_path:
            return

        try:
            exported = export_index_html(self.results, output_path)
        except Exception as exc:
            messagebox.showerror("Export Failed", str(exc))
            return

        self.config_data.last_export_dir = str(Path(exported).parent)
        save_config(self.config_data)
        self.status_var.set(f"Exported HTML to {exported}")
        messagebox.showinfo("Export Complete", f"HTML exported to:\n{exported}")

    def _persist_config(self) -> None:
        self.config_data = AppConfig(
            project_root=self.project_root_var.get().strip(),
            shotcodes_text=self.shotcodes_text.get("1.0", "end").strip(),
            last_export_dir=self.config_data.last_export_dir,
        )
        save_config(self.config_data)

    def _handle_close(self) -> None:
        self._persist_config()
        self.destroy()


def main() -> None:
    app = QCViewerApp()
    app.mainloop()
