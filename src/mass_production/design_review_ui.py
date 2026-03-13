"""Browser UI for human review of generated design images."""

import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from logger_config import log_action


def _build_html(keyword: str) -> str:
    """Build the interactive review page HTML.

    Args:
        keyword: Current keyword label shown in the UI.

    Returns:
        Rendered HTML page as a string.
    """
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Design Review | {keyword}</title>
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
  <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
  <link
    href=\"https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap\"
    rel=\"stylesheet\"
  />
  <style>
    :root {{
      --bg: #f6f4ee;
      --ink: #10151f;
      --card: #ffffff;
      --line: #d2d7df;
      --accent: #0c7a6a;
      --warn: #b06a00;
      --danger: #9f2241;
      --muted: #5a6678;
      --radius: 14px;
      --shadow: 0 12px 30px rgba(16, 21, 31, 0.12);
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      font-family: "Space Grotesk", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 90% 12%, #ffe9b8 0%, transparent 36%),
        radial-gradient(circle at 10% 92%, #c6ece5 0%, transparent 34%),
        var(--bg);
      min-height: 100vh;
    }}

    header {{
      padding: 18px 24px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.72);
      backdrop-filter: blur(6px);
      position: sticky;
      top: 0;
      z-index: 20;
    }}

    h1 {{
      margin: 0;
      font-size: clamp(1.2rem, 1.8vw, 1.8rem);
      letter-spacing: 0.01em;
    }}

    .sub {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 0.95rem;
    }}

    main {{
      padding: 22px;
      max-width: 1400px;
      margin: 0 auto 120px;
    }}

    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 18px;
    }}

    .card {{
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--card);
      box-shadow: var(--shadow);
      overflow: hidden;
      transform: translateY(8px);
      opacity: 0;
      animation: reveal 420ms ease forwards;
    }}

    .card img {{
      width: 100%;
      aspect-ratio: 1 / 1;
      object-fit: cover;
      background: #f1f3f8;
      display: block;
    }}

    .meta {{
      padding: 12px;
    }}

    .title {{
      font-weight: 700;
      font-size: 0.98rem;
      line-height: 1.35;
      margin: 0;
    }}

    .hint {{
      margin: 8px 0 10px;
      color: var(--muted);
      font-size: 0.82rem;
      font-family: "IBM Plex Mono", monospace;
    }}

    .actions {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }}

    button.action {{
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #f9fafb;
      color: var(--ink);
      padding: 8px 6px;
      font-size: 0.85rem;
      font-family: "IBM Plex Mono", monospace;
      cursor: pointer;
      transition: transform 120ms ease, background-color 120ms ease, border-color 120ms ease;
    }}

    button.action:hover {{ transform: translateY(-1px); }}

    button.action.active.keep {{
      border-color: var(--accent);
      background: rgba(12, 122, 106, 0.12);
    }}

    button.action.active.retry {{
      border-color: var(--warn);
      background: rgba(176, 106, 0, 0.14);
    }}

    button.action.active.reject {{
      border-color: var(--danger);
      background: rgba(159, 34, 65, 0.12);
    }}

    .footer {{
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      border-top: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.9);
      backdrop-filter: blur(6px);
      padding: 12px 20px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      z-index: 30;
    }}

    .stats {{
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.88rem;
      color: #1f2a3a;
    }}

    #submit {{
      border: 0;
      border-radius: 12px;
      background: linear-gradient(135deg, #0c7a6a, #1455b3);
      color: #ffffff;
      font-weight: 700;
      padding: 10px 18px;
      cursor: pointer;
      min-width: 190px;
    }}

    #submit:disabled {{ opacity: 0.6; cursor: not-allowed; }}

    .toast {{
      margin-top: 10px;
      font-size: 0.9rem;
      color: #244f42;
      display: none;
    }}

    @keyframes reveal {{
      from {{ opacity: 0; transform: translateY(8px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    @media (max-width: 700px) {{
      .actions {{ grid-template-columns: 1fr; }}
      .footer {{ padding: 10px 12px; }}
      #submit {{ width: 100%; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Design Review: {keyword}</h1>
    <div class=\"sub\">Keep to continue, Retry to regenerate once, Reject to drop.</div>
  </header>

  <main>
    <div id=\"grid\" class=\"grid\"></div>
    <div id=\"toast\" class=\"toast\">Submitted. You can close this tab.</div>
  </main>

  <div class=\"footer\">
    <div class=\"stats\" id=\"stats\">Loading...</div>
    <button id=\"submit\">Submit Review Decisions</button>
  </div>

  <script>
    const decisions = new Map();
    let designs = [];

    function cardMarkup(item, idx) {{
      const delay = Math.min(idx * 40, 420);
      return `
        <article
          class=\"card\"
          style=\"animation-delay:${{delay}}ms\"
          data-index=\"${{item.index}}\"
        >
          <img alt=\"${{item.title}}\" src=\"/image/${{item.index}}?v=${{Date.now()}}\" />
          <div class=\"meta\">
            <p class=\"title\">${{item.title}}</p>
            <p class=\"hint\">
              idea_index=${{item.idea_index}} | retry_count=${{item.retry_count}}
            </p>
            <div class=\"actions\">
              <button class=\"action keep\" data-action=\"keep\">Keep</button>
              <button class=\"action retry\" data-action=\"retry\">Retry</button>
              <button class=\"action reject\" data-action=\"reject\">Reject</button>
            </div>
          </div>
        </article>`;
    }}

    function updateStats() {{
      const counts = {{ keep: 0, retry: 0, reject: 0 }};
      designs.forEach((item) => {{
        const action = decisions.get(item.index) || "keep";
        counts[action] += 1;
      }});
      const statsText = [
        `keep=${{counts.keep}}`,
        `retry=${{counts.retry}}`,
        `reject=${{counts.reject}}`,
        `total=${{designs.length}}`,
      ].join(" ");
      document.getElementById("stats").textContent = statsText;
    }}

    function activateButton(card, action) {{
      card.querySelectorAll("button.action").forEach((btn) => btn.classList.remove("active"));
      const btn = card.querySelector(`button.action.${{action}}`);
      if (btn) btn.classList.add("active");
    }}

    function wireCard(card, item) {{
      const defaultAction = "keep";
      decisions.set(item.index, defaultAction);
      activateButton(card, defaultAction);

      card.querySelectorAll("button.action").forEach((btn) => {{
        btn.addEventListener("click", () => {{
          const action = btn.dataset.action;
          decisions.set(item.index, action);
          activateButton(card, action);
          updateStats();
        }});
      }});
    }}

    async function loadDesigns() {{
      const response = await fetch("/api/designs");
      if (!response.ok) throw new Error("Failed to load designs");
      designs = await response.json();
      const grid = document.getElementById("grid");
      grid.innerHTML = designs.map((item, idx) => cardMarkup(item, idx)).join("");
      designs.forEach((item) => {{
        const card = document.querySelector(`.card[data-index='${{item.index}}']`);
        if (card) wireCard(card, item);
      }});
      updateStats();
    }}

    async function submitDecisions() {{
      const payload = {{
        decisions: designs.map((item) => ({{
          index: item.index,
          action: decisions.get(item.index) || "keep",
        }})),
      }};
      const btn = document.getElementById("submit");
      btn.disabled = true;
      try {{
        const response = await fetch("/api/submit", {{
          method: "POST",
          headers: {{ "content-type": "application/json" }},
          body: JSON.stringify(payload),
        }});
        if (!response.ok) throw new Error("Submit failed");
        document.getElementById("toast").style.display = "block";
      }} finally {{
        btn.disabled = false;
      }}
    }}

    document.getElementById("submit").addEventListener("click", submitDecisions);

    loadDesigns().catch((err) => {{
      document.getElementById("stats").textContent = err.message;
    }});
  </script>
</body>
</html>
"""


def review_generated_designs(
    keyword: str, designs: list[dict[str, Any]]
) -> dict[int, str]:
    """Collect keep/retry/reject decisions for generated designs in browser UI.

    Args:
        keyword: Current keyword being reviewed.
        designs: Review payload with indexes, titles, and image paths.

    Returns:
        Mapping from review index to selected action.

    Raises:
        RuntimeError: If the review submission payload is invalid.
    """
    if not designs:
        log_action(f"No generated designs to review for keyword '{keyword}'")
        return {}

    actions: set[str] = {"keep", "retry", "reject"}
    design_map: dict[int, dict[str, Any]] = {
        int(item["index"]): item for item in designs
    }
    state: dict[str, Any] = {"submitted": None}
    submitted_event = threading.Event()

    class DesignReviewHandler(BaseHTTPRequestHandler):
        """HTTP handler for the design review UI and JSON endpoints."""

        def _write_json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._write_html(_build_html(keyword))
                return
            if parsed.path == "/api/designs":
                payload = [
                    {
                        "index": int(item["index"]),
                        "idea_index": int(item["idea_index"]),
                        "title": str(item["title"]),
                        "retry_count": int(item.get("retry_count", 0)),
                    }
                    for item in designs
                ]
                self._write_json(HTTPStatus.OK, payload)
                return
            if parsed.path == "/image":
                query = parse_qs(parsed.query)
                index_values = query.get("index", [])
                if not index_values:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Missing image index")
                    return
                try:
                    image_index = int(index_values[0])
                except ValueError:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Invalid image index")
                    return
                image_item = design_map.get(image_index)
                if image_item is None:
                    self.send_error(HTTPStatus.NOT_FOUND, "Image not found")
                    return
                image_path = Path(str(image_item["image_path"]))
                if not image_path.exists():
                    self.send_error(HTTPStatus.NOT_FOUND, "Image file missing")
                    return
                body = image_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path.startswith("/image/"):
                image_index_raw = parsed.path.split("/image/", maxsplit=1)[1].strip()
                try:
                    image_index = int(image_index_raw)
                except ValueError:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Invalid image index")
                    return
                image_item = design_map.get(image_index)
                if image_item is None:
                    self.send_error(HTTPStatus.NOT_FOUND, "Image not found")
                    return
                image_path = Path(str(image_item["image_path"]))
                if not image_path.exists():
                    self.send_error(HTTPStatus.NOT_FOUND, "Image file missing")
                    return
                body = image_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/submit":
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length)
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except json.JSONDecodeError:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid-json"})
                return

            submitted_decisions = payload.get("decisions", [])
            if not isinstance(submitted_decisions, list):
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid-decisions"})
                return

            output: dict[int, str] = {}
            for decision in submitted_decisions:
                if not isinstance(decision, dict):
                    continue
                index_value = decision.get("index")
                action_value = decision.get("action")
                if not isinstance(index_value, int) or index_value not in design_map:
                    continue
                if not isinstance(action_value, str) or action_value not in actions:
                    continue
                output[index_value] = action_value

            if len(output) != len(design_map):
                self._write_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "missing-decisions", "expected": len(design_map)},
                )
                return

            state["submitted"] = output
            submitted_event.set()
            self._write_json(HTTPStatus.OK, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), DesignReviewHandler)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    log_action(f"Opening design review UI for keyword '{keyword}' at {url}")
    print(f"Review designs for '{keyword}' at: {url}")
    webbrowser.open(url, new=1)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    submitted_event.wait()
    server.server_close()

    submitted = state.get("submitted")
    if not isinstance(submitted, dict):
        raise RuntimeError("Design review did not return valid decisions.")
    return {int(key): str(value) for key, value in submitted.items()}
