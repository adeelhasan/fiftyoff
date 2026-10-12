"""Review the built site with live data while beta is behind the preview password.

Serves web/out on http://127.0.0.1:3200 the way FastAPI does (/shelf/* and /sold/* fall back to their one page) and
forwards /api/v1/* to beta.fiftyoff.app, adding Basic Auth here so the browser never needs the password. /d/ is
not followed, so reviewing logs no clicks. Cloudflare rejects urllib's default User-Agent (403, error 1010).
    (cd web && npm run build) && python3 -I scripts/web-review.py
"""
import base64, http.server, pathlib, sys, urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = str(ROOT / "web" / "out")
env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if "=" in l and not l.startswith("#"))
PW = env["PREVIEW_PASSWORD"].strip().strip("'\"")
AUTH = "Basic " + base64.b64encode(f"fiftyoff:{PW}".encode()).decode()
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(s, *a, **k): super().__init__(*a, directory=OUT, **k)
    def log_message(s, *a): pass
    def do_GET(s):
        p = s.path.split("?")[0]
        if p.startswith("/api/v1/"):
            req = urllib.request.Request("https://beta.fiftyoff.app" + s.path, headers={"Authorization": AUTH, "User-Agent": "fiftyoff-local-review/1"})
            try: r = urllib.request.urlopen(req, timeout=20); body, code = r.read(), r.status
            except urllib.error.HTTPError as e: body, code = e.read(), e.code
            s.send_response(code); s.send_header("Content-Type", "application/json"); s.send_header("Content-Length", str(len(body))); s.end_headers(); s.wfile.write(body); return
        if p.startswith("/d/"):
            s.send_response(200); s.end_headers(); s.wfile.write(b"(local proxy: /d/ not followed)"); return
        if p.startswith("/shelf/"): s.path = "/shelf/_/index.html"
        elif p.startswith("/sold/"): s.path = "/sold/index.html"
        super().do_GET()
print("serving web/out with live /api/v1 on http://127.0.0.1:3200", file=sys.stderr)
http.server.ThreadingHTTPServer(("127.0.0.1", 3200), H).serve_forever()
