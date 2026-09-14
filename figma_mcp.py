# -*- coding: utf-8 -*-
"""
figma_mcp.py — прямий доступ бота до Figma MCP (https://mcp.figma.com/mcp).

Одноразово:   python3 figma_mcp.py auth      → відкриється браузер, увійти у Figma, дозволити.
Перевірка:    python3 figma_mcp.py test      → викликає whoami.
Токени зберігаються у figma_tokens.json (access + refresh), оновлюються автоматично.
"""
import os, sys, json, time, base64, hashlib, secrets, threading, webbrowser, urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
TOKENS = os.path.join(HERE, "figma_tokens.json")
MCP_URL = "https://mcp.figma.com/mcp"
AUTH_META = "https://api.figma.com/.well-known/oauth-authorization-server"
REDIRECT = "http://127.0.0.1:8765/callback"
FILE_KEY = os.getenv("FIGMA_FILE_KEY", "CvY4dgmOevd9ehxk9Xsaqd")

# ----------------------------------------------------------------------------- OAuth
def _meta():
    return requests.get(AUTH_META, timeout=20).json()

def _load():
    return json.load(open(TOKENS)) if os.path.exists(TOKENS) else {}

def _save(d):
    json.dump(d, open(TOKENS, "w"), indent=2)

def register_client(meta):
    r = requests.post(meta["registration_endpoint"], json={
        "client_name": "PROPHOTO Telegram bot", "redirect_uris": [REDIRECT],
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post", "scope": "mcp:connect"}, timeout=30)
    r.raise_for_status(); return r.json()

def auth():
    meta = _meta(); d = _load()
    if not d.get("client_id"):
        c = register_client(meta); d.update(client_id=c["client_id"], client_secret=c.get("client_secret", "")); _save(d)
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    url = meta["authorization_endpoint"] + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": d["client_id"], "redirect_uri": REDIRECT, "scope": "mcp:connect",
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "resource": MCP_URL})
    got = {}
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200); self.send_headers = None
            self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
            self.wfile.write("<h2>Готово — можна закрити вкладку і повернутись у термінал.</h2>".encode())
        def log_message(self, *a): pass
    srv = HTTPServer(("127.0.0.1", 8765), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    print("Відкриваю браузер для входу у Figma…\nЯкщо не відкрився, перейдіть за адресою:\n" + url)
    webbrowser.open(url)
    for _ in range(600):
        if got: break
        time.sleep(0.5)
    if not got or got.get("state") != state or "code" not in got:
        raise SystemExit("Авторизацію не завершено: " + json.dumps(got))
    r = requests.post(meta["token_endpoint"], data={
        "grant_type": "authorization_code", "code": got["code"], "redirect_uri": REDIRECT,
        "client_id": d["client_id"], "client_secret": d["client_secret"], "code_verifier": verifier, "resource": MCP_URL}, timeout=30)
    r.raise_for_status(); t = r.json()
    d.update(access_token=t["access_token"], refresh_token=t.get("refresh_token"), expires_at=time.time() + t.get("expires_in", 3600) - 60)
    _save(d); print("Токени збережено у figma_tokens.json")

def token():
    d = _load()
    if not d.get("access_token"): raise RuntimeError("Figma не авторизовано: python3 figma_mcp.py auth")
    if time.time() > d.get("expires_at", 0) and d.get("refresh_token"):
        meta = _meta()
        r = requests.post(meta["token_endpoint"], data={"grant_type": "refresh_token", "refresh_token": d["refresh_token"],
                                                        "client_id": d["client_id"], "client_secret": d["client_secret"]}, timeout=30)
        r.raise_for_status(); t = r.json()
        d.update(access_token=t["access_token"], refresh_token=t.get("refresh_token", d["refresh_token"]),
                 expires_at=time.time() + t.get("expires_in", 3600) - 60); _save(d)
    return d["access_token"]

# ----------------------------------------------------------------------------- MCP (streamable HTTP)
class Figma:
    def __init__(self):
        self.s = requests.Session(); self.sid = None; self._id = 0
        self._init()

    def _hdr(self):
        h = {"Authorization": "Bearer " + token(), "Content-Type": "application/json",
             "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}
        if self.sid: h["Mcp-Session-Id"] = self.sid
        return h

    def _rpc(self, method, params=None, notify=False):
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None: body["params"] = params
        if not notify:
            self._id += 1; body["id"] = self._id
        r = self.s.post(MCP_URL, headers=self._hdr(), data=json.dumps(body), timeout=300, stream=True)
        if r.headers.get("Mcp-Session-Id"): self.sid = r.headers["Mcp-Session-Id"]
        if r.status_code >= 400: raise RuntimeError(f"MCP {method} → {r.status_code}: {r.text[:300]}")
        if notify: return None
        ct = r.headers.get("Content-Type", "")
        if "text/event-stream" in ct:
            result = None
            for raw in r.iter_lines(decode_unicode=True):
                if raw and raw.startswith("data:"):
                    try: msg = json.loads(raw[5:].strip())
                    except Exception: continue
                    if msg.get("id") == self._id: result = msg; break
            if result is None: raise RuntimeError("no response in stream")
            msg = result
        else:
            msg = r.json()
        if "error" in msg: raise RuntimeError(f"MCP error: {msg['error']}")
        return msg["result"]

    def _init(self):
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "prophoto-bot", "version": "1.0"}})
        self._rpc("notifications/initialized", {}, notify=True)

    def call(self, name, args):
        res = self._rpc("tools/call", {"name": name, "arguments": args})
        if res.get("isError"): raise RuntimeError(f"{name} failed: {res}")
        texts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
        return "\n".join(texts)

    # ---- helpers
    def use_figma(self, code, description="bot"):
        return self.call("use_figma", {"fileKey": FILE_KEY, "code": code, "description": description})

    def upload_assets(self, node_ids, scale_mode="FILL"):
        out = self.call("upload_assets", {"fileKey": FILE_KEY, "count": len(node_ids), "nodeIds": node_ids, "scaleMode": scale_mode})
        j = json.loads(out[out.index("{"):out.rindex("}") + 1])
        return [u["submitUrl"] for u in j["uploads"]]

    def put_photo(self, submit_url, path):
        with open(path, "rb") as f:
            r = requests.post(submit_url, files={"file": (os.path.basename(path), f, "image/jpeg")}, timeout=120)
        r.raise_for_status(); return r.json()

    def screenshot_url(self, node_id, max_dim=4050):
        out = self.call("get_screenshot", {"fileKey": FILE_KEY, "nodeId": node_id, "maxDimension": max_dim})
        j = json.loads(out[out.index("{"):out.index("}") + 1])
        return j["image_url"]

    def whoami(self):
        return self.call("whoami", {})

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "auth": auth()
    elif cmd == "test": print(Figma().whoami())
    else: print(__doc__)
