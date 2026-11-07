"""Dashboard: a static HTML report and a live loopback page.

No build step, no JS framework. The live page refreshes itself and always reads
the same ``ledger.json`` the TUI reads.
"""

from __future__ import annotations

import html
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .models import Task
from .state import RunPaths, RunState, latest_run, read_json


def kick_history(paths: RunPaths) -> list[dict[str, Any]]:
    if not paths.events.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in paths.events.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("t") == "diagnose":
            rows.append(record)
    return rows


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _bar(done: int, total: int, width: int = 320) -> str:
    if total <= 0:
        percent = 0
    else:
        percent = int(round(100 * done / total))
    color = "#3fb950" if percent == 100 else ("#d29922" if percent else "#f85149")
    return (
        f'<div class="bar"><div class="fill" style="width:{percent}%;background:{color}"></div></div>'
        f'<div class="pct">{percent}%</div>'
    )


def render_html(
    state: RunState,
    ledger: dict[str, Any],
    tasks: list[Task],
    history: list[dict[str, Any]] | None = None,
    refresh: int = 0,
) -> str:
    records = ledger.get("tasks", {})
    done = sum(1 for record in records.values() if record.get("status") == "done")
    total = len(tasks)
    test = ledger.get("test", {})
    test_exit = test.get("exit_code")
    test_label = "SKIPPED" if test.get("skipped") else ("PASS" if test_exit == 0 else ("FAIL" if test_exit is not None else "—"))
    test_class = "ok" if test_exit == 0 else ("bad" if test_exit is not None else "muted")

    rows = []
    for task in tasks:
        record = records.get(task.id, {})
        status = record.get("status", "pending")
        evidence = record.get("evidence") or {}
        files = ", ".join((evidence.get("files") or [])[:3]) or "—"
        gate = evidence.get("gate") or "—"
        message = evidence.get("message") or ""
        badge = {"done": "DONE", "failed": "FAIL", "pending": "PENDING", "blocked": "BLOCKED"}.get(status, "PENDING")
        rows.append(
            "<tr>"
            f'<td><span class="badge {status}">{badge}</span></td>'
            f"<td><b>{_esc(task.id)}</b></td>"
            f"<td>{_esc(task.desc)}</td>"
            f"<td class=mono>{_esc(files)}</td>"
            f"<td class=mono>{_esc(gate)}</td>"
            f"<td class=muted>{_esc(message)}</td>"
            "</tr>"
        )

    history_rows = "".join(
        f"<tr><td>{_esc(item.get('kick'))}</td><td><b>{_esc(item.get('label'))}</b></td>"
        f"<td>{_esc(item.get('task_done', '—'))}/{_esc(item.get('total', '—'))}</td>"
        f"<td>{_esc(item.get('test_exit', '—'))}</td></tr>"
        for item in (history or [])[-12:][::-1]
    )

    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">{meta}
<title>waker · {_esc(state.run_id)}</title>
<style>
:root{{color-scheme:dark}}
body{{font:14px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;background:#0d1117;color:#c9d1d9;margin:0;padding:28px}}
h1{{font-size:20px;margin:0 0 4px}}
.sub{{color:#8b949e;margin-bottom:20px}}
.card{{border:1px solid #30363d;border-radius:10px;padding:18px;margin-bottom:16px;background:#161b22}}
.bar{{height:14px;background:#21262d;border-radius:7px;overflow:hidden;flex:1}}
.fill{{height:100%;transition:width .4s ease}}
.pct{{font-weight:700;margin-left:12px}}
.row{{display:flex;align-items:center;gap:8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-top:14px}}
.kpi{{color:#8b949e}}.kpi b{{display:block;color:#c9d1d9;font-size:18px}}
table{{width:100%;border-collapse:collapse}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #21262d;vertical-align:top}}
th{{color:#8b949e;font-weight:600}}
.badge{{padding:2px 8px;border-radius:20px;font-size:11px;font-weight:700}}
.badge.done{{background:#12261a;color:#3fb950}}.badge.failed{{background:#2d1418;color:#f85149}}
.badge.pending{{background:#1c2128;color:#8b949e}}.badge.blocked{{background:#2b2410;color:#d29922}}
.ok{{color:#3fb950}}.bad{{color:#f85149}}.muted{{color:#8b949e}}
.mono{{font-family:inherit}}
h2{{font-size:14px;color:#8b949e;margin:22px 0 6px;text-transform:uppercase;letter-spacing:.6px}}
</style></head><body>
<h1>waker · run {_esc(state.run_id)}</h1>
<div class="sub">{_esc(state.status)} · {_esc(state.diagnosis or '')} · {_esc(state.agent_session_id or state.session_id)}</div>

<div class="card">
  <div class="row"><div style="min-width:64px">{done}/{total}</div>{_bar(done, total)}</div>
  <div class="grid">
    <div class="kpi">kicks<b>{_esc(state.kicks)}/{_esc(state.max_kicks)}</b></div>
    <div class="kpi">test<b class="{test_class}">{test_label}</b></div>
    <div class="kpi">cost<b>${state.cost_usd:.4f}</b></div>
    <div class="kpi">elapsed<b>{int(state.elapsed)}s</b></div>
    <div class="kpi">unscoped<b>{_esc(len(ledger.get('unscoped') or []))}</b></div>
  </div>
</div>

<div class="card">
<table>
<thead><tr><th></th><th>Task</th><th>Work</th><th>Evidence</th><th>Gate</th><th>Note</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan=6 class=muted>no tasks</td></tr>'}</tbody>
</table>
</div>

<h2>Kick history</h2>
<div class="card">
<table>
<thead><tr><th>#</th><th>Diagnosis</th><th>Done</th><th>Test</th></tr></thead>
<tbody>{history_rows or '<tr><td colspan=4 class=muted>no kicks yet</td></tr>'}</tbody>
</table>
</div>
</body></html>"""


def write_static(repo: str | Path, out: str | Path, run_id: str | None = None) -> Path:
    root = Path(repo).resolve()
    run_id = run_id or latest_run(root)
    if not run_id:
        raise FileNotFoundError("no run found")
    paths = RunPaths(root, run_id)
    state = RunState.load(paths.state)
    ledger = read_json(paths.ledger) if paths.ledger.exists() else {"tasks": {}}
    html_text = render_html(state, ledger, state.task_objects(), kick_history(paths))
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html_text, encoding="utf-8")
    return target


def make_dashboard_server(
    repo: str | Path,
    run_id: str | None = None,
    host: str = "127.0.0.1",
    port: int = 47822,
) -> ThreadingHTTPServer:
    root = Path(repo).resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # noqa: A003
            return

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            current = run_id or latest_run(root)
            if not current:
                self._send(404, b"no run found", "text/plain; charset=utf-8")
                return
            paths = RunPaths(root, current)
            if self.path.startswith("/api/status"):
                state = RunState.load(paths.state)
                ledger = read_json(paths.ledger) if paths.ledger.exists() else {"tasks": {}}
                payload = {
                    "run_id": state.run_id,
                    "status": state.status,
                    "diagnosis": state.diagnosis,
                    "kicks": state.kicks,
                    "cost_usd": state.cost_usd,
                    "tasks": ledger.get("tasks", {}),
                    "test": ledger.get("test", {}),
                }
                self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
                return
            state = RunState.load(paths.state)
            ledger = read_json(paths.ledger) if paths.ledger.exists() else {"tasks": {}}
            body = render_html(
                state,
                ledger,
                state.task_objects(),
                kick_history(paths),
                refresh=2 if state.status == "running" else 0,
            ).encode("utf-8")
            self._send(200, body, "text/html; charset=utf-8")

    return ThreadingHTTPServer((host, port), Handler)


def serve_dashboard(
    repo: str | Path,
    run_id: str | None = None,
    host: str = "127.0.0.1",
    port: int = 47822,
    open_browser: bool = False,
) -> None:
    server = make_dashboard_server(repo, run_id, host, port)
    url = f"http://{host}:{server.server_address[1]}/"
    print(f"waker dashboard: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
