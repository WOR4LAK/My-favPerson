# app.py — Flask URL shortener + SQLite + QR (Google Chart)
import os, re, sqlite3, urllib.parse
from datetime import datetime
from flask import Flask, request, redirect, render_template_string, jsonify, abort

APP_PORT = int(os.environ.get("PORT", 8080))
DB_PATH = os.environ.get("DB_PATH", "data.db")
app = Flask(__name__)

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS links(
          alias TEXT PRIMARY KEY,
          long_url TEXT NOT NULL,
          clicks INTEGER DEFAULT 0,
          created_at TEXT NOT NULL
        )
        """)

ALIAS_RE = re.compile(r"^[a-z0-9\-_]{1,64}$")
def is_valid_alias(a: str) -> bool:
    return bool(ALIAS_RE.match(a)) and a not in {"qr", "api", "static"}

PAGE = """
<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<title>My Shortener</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Inter,Arial;margin:24px;max-width:800px}
 input,button{font-size:16px;padding:8px} table{border-collapse:collapse;width:100%}
 th,td{padding:8px;border-bottom:1px solid #eee} .msg{margin:12px 0}
</style>
<h2>สร้างลิงก์สั้นของคุณ</h2>
<form method="post">
  <div>URL ต้นฉบับ</div>
  <input type="url" name="long_url" size="50" required placeholder="https://open.spotify.com/…">
  <div style="margin-top:8px">alias (เช่น imissusm-atmm)</div>
  <input name="alias" required pattern="[a-z0-9\\-_]{1,64}" title="ตัวเล็ก a-z, 0-9, -, _">
  <div style="margin-top:12px"><button type="submit">สร้างลิงก์สั้น</button></div>
</form>
{% if msg %}<div class="msg">{{msg}}</div>{% endif %}
{% if short_full %}
  <p><b>ลิงก์สั้น:</b> <a href="{{short_full}}" target="_blank">{{short_full}}</a></p>
  <p>QR:</p><img src="{{qr_src}}" alt="QR">
{% endif %}
<hr><h3>ลิงก์ทั้งหมด</h3>
<table><tr><th>Alias</th><th>ปลายทาง</th><th>คลิก</th><th>สร้างเมื่อ</th></tr>
{% for r in rows %}
  <tr><td><a href="/{{r['alias']}}" target="_blank">/{{r['alias']}}</a></td>
      <td style="word-break:break-all">{{r['long_url']}}</td>
      <td>{{r['clicks']}}</td>
      <td>{{r['created_at']}}</td></tr>
{% endfor %}</table>
"""

@app.route("/", methods=["GET","POST"])
def index():
    msg = short_full = qr_src = None
    if request.method == "POST":
        long_url = request.form["long_url"].strip()
        alias = request.form["alias"].strip().lower()
        if not is_valid_alias(alias):
            msg = "❌ alias ใช้ได้เฉพาะ a-z 0-9 '-' '_' (≤64 ตัว)"
        else:
            with db() as conn:
                if conn.execute("SELECT 1 FROM links WHERE alias=?", (alias,)).fetchone():
                    msg = "❌ alias นี้ถูกใช้แล้ว"
                else:
                    from datetime import datetime
                    conn.execute("INSERT INTO links(alias,long_url,clicks,created_at) VALUES (?,?,0,?)",
                                 (alias, long_url, datetime.utcnow().isoformat()))
                    base = request.host_url.rstrip("/")
                    short_full = f"{base}/{alias}"
                    qr_src = "https://chart.googleapis.com/chart?chs=220x220&cht=qr&choe=UTF-8&chl=" + urllib.parse.quote(short_full, safe="")
                    msg = "✅ สร้างสำเร็จ!"
    with db() as conn:
        rows = conn.execute("SELECT alias,long_url,clicks,created_at FROM links ORDER BY created_at DESC").fetchall()
    return render_template_string(PAGE, msg=msg, short_full=short_full, qr_src=qr_src, rows=rows)

@app.route("/<alias>")
def go(alias):
    alias = alias.lower()
    with db() as conn:
        row = conn.execute("SELECT long_url FROM links WHERE alias=?", (alias,)).fetchone()
        if not row: abort(404)
        conn.execute("UPDATE links SET clicks = clicks + 1 WHERE alias=?", (alias,))
        return redirect(row["long_url"])

@app.route("/api/shorten", methods=["POST"])
def api_shorten():
    data = request.get_json(force=True, silent=True) or {}
    long_url = (data.get("url") or "").strip()
    alias = (data.get("alias") or "").strip().lower()
    if not long_url or not is_valid_alias(alias):
        return jsonify(error="bad_request"), 400
    with db() as conn:
        if conn.execute("SELECT 1 FROM links WHERE alias=?", (alias,)).fetchone():
            return jsonify(error="alias_taken"), 409
        conn.execute("INSERT INTO links(alias,long_url,clicks,created_at) VALUES (?,?,0,?)",
                     (alias, long_url, datetime.utcnow().isoformat()))
    base = request.host_url.rstrip("/")
    return jsonify(short=f"{base}/{alias}")

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=APP_PORT)
else:
    init_db()
