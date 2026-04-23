from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .scanner import ScanResult
from .thumbnail import thumbnail_src_for_html
from .utils import html_escape, path_to_file_uri


def export_index_html(results: list[ScanResult], output_path: str | Path, title: str = "MSL Render QC Viewer") -> Path:
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    ok_count = sum(1 for result in results if result.status == "OK")
    warn_count = sum(1 for result in results if result.status == "WARN")
    fail_count = sum(1 for result in results if result.status == "FAIL")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cards = []
    for result in results:
        latest_version = str(result.latest_version_dir) if result.latest_version_dir else "-"
        image_link = path_to_file_uri(result.representative_image) if result.representative_image else ""
        folder_link = path_to_file_uri(result.latest_version_dir or result.lighting_dir)
        thumbnail_src = thumbnail_src_for_html(result.thumbnail_source, result.status, result.shotcode)

        action_links = []
        if folder_link:
            action_links.append(f"<a href='{html_escape(folder_link)}'>Open Folder</a>")
        if image_link:
            action_links.append(f"<a href='{html_escape(image_link)}'>Open Image</a>")

        cards.append(
            f"""
            <article class="card status-{result.status.lower()}">
              <div class="thumb-wrap">
                <img src="{html_escape(thumbnail_src)}" alt="{html_escape(result.shotcode)} thumbnail" loading="lazy">
              </div>
              <div class="content">
                <div class="topline">
                  <h2>{html_escape(result.shotcode)}</h2>
                  <span class="badge">{html_escape(result.status)}</span>
                </div>
                <p class="message">{html_escape(result.message)}</p>
                <p><strong>Latest Version</strong><br>{html_escape(latest_version)}</p>
                <p><strong>QC</strong><br>Beauty: {"Yes" if result.beauty_found else "No"} | Crypto: {"Yes" if result.crypto_found else "No"}</p>
                <div class="actions">{' '.join(action_links) if action_links else '<span class="muted">No actions available</span>'}</div>
              </div>
            </article>
            """
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)}</title>
  <style>
    :root {{
      --bg: #0f1216;
      --panel: #171c22;
      --line: #27303a;
      --text: #edf1f5;
      --muted: #9aa7b5;
      --ok: #2d8f5b;
      --warn: #b8871f;
      --fail: #b94a48;
      --link: #7fc4ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 24px;
      background: radial-gradient(circle at top, #1b2530 0%, var(--bg) 40%);
      color: var(--text);
      font: 14px/1.5 "Segoe UI", Arial, sans-serif;
    }}
    h1, h2, p {{ margin: 0; }}
    .header {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 20px;
    }}
    .summary {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .pill {{
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.08);
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      gap: 16px;
    }}
    .card {{
      display: grid;
      grid-template-columns: 240px 1fr;
      gap: 16px;
      background: rgba(23, 28, 34, 0.92);
      border: 1px solid var(--line);
      border-left: 6px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      box-shadow: 0 12px 32px rgba(0,0,0,0.22);
    }}
    .status-ok {{ border-left-color: var(--ok); }}
    .status-warn {{ border-left-color: var(--warn); }}
    .status-fail {{ border-left-color: var(--fail); }}
    .thumb-wrap {{
      background: #10151a;
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: hidden;
      min-height: 135px;
    }}
    img {{
      width: 100%;
      height: 100%;
      display: block;
      object-fit: cover;
      background: #0b0f14;
    }}
    .content {{
      display: grid;
      gap: 10px;
      min-width: 0;
    }}
    .topline {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
    }}
    .badge {{
      padding: 4px 10px;
      border-radius: 999px;
      font-weight: 700;
      letter-spacing: 0.04em;
      background: rgba(255,255,255,0.08);
    }}
    .message {{
      color: var(--muted);
    }}
    .actions {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }}
    a {{
      color: var(--link);
      text-decoration: none;
    }}
    a:hover {{
      text-decoration: underline;
    }}
    .muted {{
      color: var(--muted);
    }}
    @media (max-width: 840px) {{
      body {{
        padding: 16px;
      }}
      .card {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <header class="header">
    <div>
      <h1>{html_escape(title)}</h1>
      <p class="muted">Generated at {html_escape(generated_at)}</p>
    </div>
    <div class="summary">
      <span class="pill">Total: {len(results)}</span>
      <span class="pill">OK: {ok_count}</span>
      <span class="pill">WARN: {warn_count}</span>
      <span class="pill">FAIL: {fail_count}</span>
    </div>
  </header>
  <section class="grid">
    {''.join(cards)}
  </section>
</body>
</html>
"""

    output_file.write_text(html, encoding="utf-8")
    return output_file
