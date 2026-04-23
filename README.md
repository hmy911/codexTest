# MSL_batch_Arena_GUI

`MSL_batch_Arena_GUI` is a Tkinter desktop GUI wrapper for the existing Arena batch pipeline:

- `step1_export_shot.py`
- `step2_build_arena.py`
- `step3_submit_deadline.py`

It keeps the original Maya logic intact and only adds a quicker desktop layer for filling paths, previewing commands, and debugging runs.

## Project target

This project is intended to live at:

```text
D:\codex\MSL_batch_Arena_GUI
```

## Install

```bash
pip install -e .
```

If you prefer isolated setup:

```bash
python -m venv venv
venv\Scripts\activate
pip install -e .[build]
```

For local setup, copy the example config files and adjust the paths for your machine:

```powershell
Copy-Item .\msl_batch_arena_gui_config.example.json .\msl_batch_arena_gui_config.json
Copy-Item .\msl_qc_viewer_config.example.json .\msl_qc_viewer_config.json
```

## Run

```bash
python app.py
```

or

```bash
python msl_batch_arena_gui_tk.py
```

## Build EXE

Build on a machine that has internet access once, then copy the finished output to the offline company machine.

1. Install build dependencies:

```bash
pip install -e .[build]
```

2. Build a single-file executable:

```powershell
.\build_exe.ps1
```

3. The output will be created at:

```text
dist\ArenaApp.exe
```

If you prefer a folder-style build instead of one single `.exe`:

```powershell
.\build_exe.ps1 -OneDir
```

That output will be created at:

```text
dist\ArenaApp\ArenaApp.exe
```

## Offline deployment notes

- This app is a Tk desktop GUI, so the packaged `.exe` can be launched directly.
- The Maya scripts and scene files are still read from the paths you enter in the app, so those assets must also exist on the offline machine or shared storage visible from that machine.
- The Tk version currently stores config in `msl_batch_arena_gui_config.json` next to the app.
- A safe template is provided in `msl_batch_arena_gui_config.example.json`.

## Features

- Tkinter GUI for quick local debugging
- Editable paths for `mayapy`, project root, step scripts, and arena scene
- Built-in file / folder browse buttons
- Multi-line shotcode input
- Step 1 / Step 2 / Step 3 toggles
- Command preview
- Live execution log
- Config persistence in `msl_batch_arena_gui_config.json`
- Example config files for Git-friendly setup

## Default assumptions

- Existing batch scripts live under `D:\codex\MSL_batch_Arena`
- Final GUI project folder is `D:\codex\MSL_batch_Arena_GUI`
- The tool calls your original scripts with CLI arguments and does not replace their internal Maya logic
