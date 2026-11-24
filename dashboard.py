"""Local dashboard server. Run: python dashboard.py -> http://127.0.0.1:8765"""
import json
import os
import sqlite3
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE = Path(__file__).resolve().parent
DB_URI = (BASE / "bot.db").as_uri() + "?mode=ro"      # read-only
MODE = os.getenv("MODE", "shadow")

def q(sql, args=()):
    try:
        c = sqlite3.connect(DB_URI, uri=True, timeout=5)
        c.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in c.execute(sql, args).fetchall()]
        finally:
            c.close()
    except sqlite3.Error:
        return []

def read_state():
    try:
        with open(BASE / "state.json", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"pos": {}, "cool": {}}

def summary():
    e = q("select bar, eq from equity order by bar desc, rowid desc limit 1")
    meta = {r["k"]: r["v"] for r in q("select k, v from meta")}
    st = read_state()
    f = lambda k: float(meta[k]) if k in meta else None
    return {"mode": MODE, "now": int(time.time()),
            "equity": e[0]["eq"] if e else None, "last_bar": e[0]["bar"] if e else None,
            "day_eq": f("day_eq"), "week_eq": f("week_eq"), "peak": f("peak"),
            "paused": meta.get("paused") == "1", "n_pos": len(st.get("pos", {})),
            "cooldowns": {k: v for k, v in st.get("cool", {}).items() if v > time.time()}}

def trades(limit):
    return q("select rowid id, symbol, coalesce(side,'long') side, entry, exit, qty, why, pnl, ts "
             "from trades order by ts desc limit ?", (limit,))

def equity(limit):
    rows = q("select bar, eq from (select bar, eq, rowid r from equity order by bar desc, r desc limit ?) "
             "order by bar asc", (limit,))
    return rows

def scan():
    m = q("select max(bar) m from scans where side is not null")
    if not m or m[0]["m"] is None:
        return []
    rows = q("select symbol, side, ok, soft, hard, softd, vals from scans where bar=? and side is not null",
             (m[0]["m"],))
    return [{"symbol": r["symbol"], "side": r["side"], "ok": bool(r["ok"]), "soft_n": r["soft"],
             "hard": json.loads(r["hard"]), "soft": json.loads(r["softd"]),
             "vals": json.loads(r["vals"])} for r in rows]

def gates(side, days):
    since = int(time.time()) - days * 86400
    rows = q("select hard, softd, ok from scans where side=? and bar>=?", (side, since))
    n, cnt, allhard, sig = len(rows), {}, 0, 0
    for r in rows:
        h, s = json.loads(r["hard"]), json.loads(r["softd"])
        for k, v in {**h, **s}.items():
            cnt[k] = cnt.get(k, 0) + (1 if v else 0)
        allhard += all(h.values())
        sig += r["ok"]
    return {"n": n, "all_hard": allhard, "signals": sig,
            "rates": {k: round(v / n * 100, 1) for k, v in cnt.items()} if n else {}}

def logtail(n):
    try:
        with open(BASE / "bot.log", "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 65536))
            data = f.read().decode("utf-8", "replace")
        return data.splitlines()[-n:]
    except OSError:
        return []

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u, qs = urlparse(self.path), parse_qs(urlparse(self.path).query)
        arg = lambda k, d: qs.get(k, [d])[0]
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, (BASE / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path.startswith("/api/"):
                ep = u.path[5:]
                if   ep == "summary":   out = summary()
                elif ep == "positions": out = read_state().get("pos", {})
                elif ep == "trades":    out = trades(int(arg("limit", 200)))
                elif ep == "equity":    out = equity(int(arg("limit", 2000)))
                elif ep == "scan":      out = scan()
                elif ep == "gates":     out = gates(arg("side", "long"), int(arg("days", 7)))
                elif ep == "log":       out = logtail(int(arg("n", 60)))
                else: return self._send(404, b"{}", "application/json")
                return self._send(200, json.dumps(out).encode(), "application/json")
            self._send(404, b"not found", "text/plain")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try: self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")
            except Exception: pass

class OneServer(ThreadingHTTPServer):
    allow_reuse_address = False          # Windows par dusra process same port nahi pakad payega
    daemon_threads = True

if __name__ == "__main__":
    import threading
    import webbrowser
    PORT = int(os.getenv("DASH_PORT", "8790"))
    URL = f"http://127.0.0.1:{PORT}"

    def open_edge():
        try:
            if os.name == "nt":
                os.startfile("microsoft-edge:" + URL)
                return
        except OSError:
            pass
        webbrowser.open(URL)

    try:
        srv = OneServer(("127.0.0.1", PORT), H)
    except OSError:
        raise SystemExit(f"Port {PORT} busy hai, dashboard shayad pehle se chal raha hai. "
                         f"Doosre port ke liye: set DASH_PORT=8801")

    print(f"Dashboard: {URL}  (band karne ke liye Ctrl+C)")
    threading.Timer(1.0, open_edge).start()
    srv.serve_forever()