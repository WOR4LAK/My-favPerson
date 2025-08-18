# app.py — URL Shortener + Manage (edit/delete) + Auto alias + QR (Google Chart)
import os, re, sqlite3, urllib.parse, secrets, string
from datetime import datetime
from flask import Flask, request, redirect, render_template_string, jsonify, abort

APP_PORT = int(os.environ.get("PORT", 8080))
DB_PATH   = os.environ.get("DB_PATH", "data.db")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")  # ตั้งใน Render → Environment Variables

app = Flask(__name__)

# ---------- DB ----------
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

# ---------- Utils ----------
ALIAS_RE = re.compile(r"^[a-z0-9\-_]{1,64}$")
SAFE_ALIASES = {"qr", "api", "static", "manage", "delete", "update"}

def is_valid_alias(a: str) -> bool:
    return bool(ALIAS_RE.match(a)) and a not in SAFE_ALIASES

def gen_alias(n: int = 7) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))

def unique_alias(n: int = 7) -> str:
    with db() as conn:
        while True:
            a = gen_alias(n)
            row = conn.execute("SELECT 1 FROM links WHERE alias=?", (a,)).fetchone()
            if not row:
                return a

def admin_ok(req) -> bool:
    if not ADMIN_KEY:   # ถ้าไม่ตั้ง ADMIN_KEY ไว้ ถือว่าผ่าน (สะดวกทดสอบ)
        return True
    key = req.args.get("key") or req.form.get("key")
    return key == ADMIN_KEY

def short_url_for(alias: str) -> str:
    base = request.host_url.rstrip("/")
    return f"{base}/{alias}"

def qr_src_for(short_full: str) -> str:
    return "https://chart.googleapis.com/chart?chs=220x220&cht=qr&choe=UTF-8&chl=" + urllib.parse.quote(short_full, safe="")

# ---------- Templates ----------
PAGE_HOME = """
<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<title>My Shortener</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Inter,Arial;margin:24px;max-width:900px}
 input,button{font-size:16px;padding:8px}
 table{border-collapse:collapse;width:100%} th,td{padding:8px;border-bottom:1px solid #eee}
 .msg{margin:12px 0} .row{margin:8px 0}
 .hint{color:#666;font-size:13px}
</style>
<h2>สร้างลิงก์สั้นของคุณ</h2>
<form method="post">
  <div class="row">URL ต้นฉบับ<br>
    <input type="url" name="long_url" size="60" required placeholder="https://open.spotify.com/...">
  </div>
  <div class="row">alias (เช่น imissusm-atmm) <span class="hint">*ปล่อยว่างได้ ระบบจะสุ่มให้</span><br>
    <input name="alias" pattern="[a-z0-9\\-_]{0,64}" title="ตัวเล็ก a-z, 0-9, -, _">
  </div>
  <div class="row"><button type="submit">สร้างลิงก์สั้น</button></div>
</form>

{% if msg %}<div class="msg">{{msg}}</div>{% endif %}

{% if short_full %}
  <p><b>ลิงก์สั้น:</b> <a href="{{short_full}}" target="_blank">{{short_full}}</a></p>
  <p>QR:</p><img src="{{qr_src}}" alt="QR">
{% endif %}

<hr>
<h3>ทั้งหมด</h3>
<table>
<tr><th>Alias</th><th>ปลายทาง</th><th>คลิก</th><th>สร้างเมื่อ</th></tr>
{% for r in rows %}
<tr>
  <td><a href="/{{r['alias']}}" target="_blank">/{{r['alias']}}</a></td>
  <td style="word-break:break-all">{{r['long_url']}}</td>
  <td>{{r['clicks']}}</td>
  <td>{{r['created_at']}}</td>
</tr>
{% endfor %}
</table>

<p class="hint">ไปหน้า <a href="/manage{% if admin_key %}?key={{admin_key}}{% endif %}">จัดการลิงก์</a></p>
"""

PAGE_MANAGE = """
<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Manage Links</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Inter,Arial;margin:24px;max-width:1000px}
 table{border-collapse:collapse;width:100%} th,td{padding:8px;border-bottom:1px solid #eee}
 input,button{font-size:14px;padding:6px}
 .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
 .muted{color:#666}
</style>
<h2>จัดการลิงก์</h2>
<p class="muted">ใส่ค่าใหม่แล้วกด Update หรือกด Delete เพื่อลบ (ต้องใช้ key ที่ตั้งไว้ ถ้ามี)</p>
<table>
<tr><th>Alias</th><th>ปลายทาง (แก้ไขได้)</th><th>คลิก</th><th>สร้างเมื่อ</th><th>ดำเนินการ</th></tr>
{% for r in rows %}
<tr>
  <td><a href="/{{r['alias']}}" target="_blank">/{{r['alias']}}</a></td>
  <td style="word-break:break-all">
    <form method="post" action="/update" class="row">
      <input type="hidden" name="alias" value="{{r['alias']}}">
      <input type="url" name="long_url" value="{{r['long_url']}}" size="50" required>
      {% if need_key %}<input name="key" placeholder="admin key" required>{% endif %}
      <button type="submit">Update</button>
    </form>
  </td>
  <td>{{r['clicks']}}</td>
  <td>{{r['created_at']}}</td>
  <td>
    <form method="post" action="/delete" onsubmit="return confirm('ลบ {{r['alias']}} ?')">
      <input type="hidden" name="alias" value="{{r['alias']}}">
      {% if need_key %}<input name="key" placeholder="admin key" required>{% endif %}
      <button type="submit">Delete</button>
    </form>
  </td>
</tr>
{% endfor %}
</table>
<p><a href="/{% if admin_key %}?key={{admin_key}}{% endif %}">← กลับหน้าหลัก</a></p>
"""

# ---------- Routes ----------
@app.route("/", methods=["GET","POST"])
def index():
    msg = short_full = qr_src = None
    if request.method == "POST":
        long_url = (request.form.get("long_url") or "").strip()
        alias_in = (request.form.get("alias") or "").strip().lower()
        if not long_url:
            msg = "❌ โปรดกรอก URL"
        else:
            if alias_in:
                if not is_valid_alias(alias_in):
                    msg = "❌ alias ใช้ได้เฉพาะ a-z 0-9 '-' '_' (≤64 ตัว)"
                else:
                    alias = alias_in
            else:
                alias = unique_alias(7)  # สุ่ม 7 ตัว

            if not msg:
                with db() as conn:
                    dup = conn.execute("SELECT 1 FROM links WHERE alias=?", (alias,)).fetchone()
                    if dup:
                        msg = "❌ alias นี้ถูกใช้แล้ว (สุ่มใหม่หรือเปลี่ยนชื่อ)"
                    else:
                        conn.execute(
                            "INSERT INTO links(alias,long_url,clicks,created_at) VALUES (?,?,0,?)",
                            (alias, long_url, datetime.utcnow().isoformat())
                        )
                        short_full = short_url_for(alias)
                        qr_src = qr_src_for(short_full)
                        msg = "✅ สร้างสำเร็จ!"

    with db() as conn:
        rows = conn.execute("SELECT alias,long_url,clicks,created_at FROM links ORDER BY created_at DESC").fetchall()
    return render_template_string(
        PAGE_HOME,
        msg=msg, short_full=short_full, qr_src=qr_src,
        rows=rows, admin_key=ADMIN_KEY
    )

@app.route("/manage")
def manage():
    if not admin_ok(request):
        return "Unauthorized (ต้องใส่ ?key=... หรือกำหนด ADMIN_KEY)", 401
    with db() as conn:
        rows = conn.execute("SELECT alias,long_url,clicks,created_at FROM links ORDER BY created_at DESC").fetchall()
    return render_template_string(PAGE_MANAGE, rows=rows, need_key=bool(ADMIN_KEY), admin_key=ADMIN_KEY)

@app.route("/update", methods=["POST"])
def update():
    if not admin_ok(request):
        return "Unauthorized", 401
    alias = (request.form.get("alias") or "").lower()
    long_url = (request.form.get("long_url") or "").strip()
    if not alias or not long_url:
        return "bad request", 400
    with db() as conn:
        cur = conn.execute("UPDATE links SET long_url=? WHERE alias=?", (long_url, alias))
        if cur.rowcount == 0:
            return "not found", 404
    return redirect("/manage" + (f"?key={ADMIN_KEY}" if ADMIN_KEY else ""))

@app.route("/delete", methods=["POST"])
def delete():
    if not admin_ok(request):
        return "Unauthorized", 401
    alias = (request.form.get("alias") or "").lower()
    if not alias:
        return "bad request", 400
    with db() as conn:
        conn.execute("DELETE FROM links WHERE alias=?", (alias,))
    return redirect("/manage" + (f"?key={ADMIN_KEY}" if ADMIN_KEY else ""))

@app.route("/<alias>")
def go(alias):
    alias = alias.lower()
    with db() as conn:
        row = conn.execute("SELECT long_url FROM links WHERE alias=?", (alias,)).fetchone()
        if not row: abort(404)
        conn.execute("UPDATE links SET clicks = clicks + 1 WHERE alias=?", (alias,))
        return redirect(row["long_url"])

# API: POST /api/shorten { "url": "https://...", "alias": "optional" }
@app.route("/api/shorten", methods=["POST"])
def api_shorten():
    data = request.get_json(force=True, silent=True) or {}
    long_url = (data.get("url") or "").strip()
    alias_in = (data.get("alias") or "").strip().lower()
    if not long_url:
        return jsonify(error="bad_request"), 400
    if alias_in:
        if not is_valid_alias(alias_in):
            return jsonify(error="bad_alias"), 400
        alias = alias_in
    else:
        alias = unique_alias(7)
    with db() as conn:
        if conn.execute("SELECT 1 FROM links WHERE alias=?", (alias,)).fetchone():
            return jsonify(error="alias_taken"), 409
        conn.execute("INSERT INTO links(alias,long_url,clicks,created_at) VALUES (?,?,0,?)",
                     (alias, long_url, datetime.utcnow().isoformat()))
    return jsonify(short=short_url_for(alias))

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=APP_PORT)
else:
    init_db()
