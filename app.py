# app.py — URL Shortener + Daily Stats + Managed with Key + Configurable alias length
import os, re, sqlite3, urllib.parse, secrets, string, csv, io
from datetime import datetime, date
from flask import Flask, request, redirect, render_template_string, jsonify, abort, send_file

APP_PORT  = int(os.environ.get("PORT", 8080))
DB_PATH   = os.environ.get("DB_PATH", "data.db")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")     # ต้องตั้ง ถึงจะเข้าหน้า /manage และ /stats ได้
ALIAS_LEN = int(os.environ.get("ALIAS_LEN", 7)) # กำหนดความยาว alias ที่สุ่ม (ว่าง = 7)

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
        # เก็บยอดคลิก “รายวัน” ต่อ alias
        conn.execute("""
        CREATE TABLE IF NOT EXISTS clicks_daily(
          alias TEXT NOT NULL,
          day   TEXT NOT NULL,  -- YYYY-MM-DD
          count INTEGER DEFAULT 0,
          PRIMARY KEY(alias, day),
          FOREIGN KEY(alias) REFERENCES links(alias) ON DELETE CASCADE
        )
        """)

# ---------- Utils ----------
SAFE_ALIASES = {"qr", "api", "static", "manage", "delete", "update", "stats", "export_csv"}
ALIAS_RE = re.compile(r"^[a-z0-9\-_]{1,64}$")

def is_valid_alias(a: str) -> bool:
    return bool(ALIAS_RE.match(a)) and a not in SAFE_ALIASES

def gen_alias(n: int) -> str:
    n = max(4, min(n, 32))  # กันพลาด
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))

def unique_alias(n: int) -> str:
    with db() as conn:
        while True:
            a = gen_alias(n)
            row = conn.execute("SELECT 1 FROM links WHERE alias=?", (a,)).fetchone()
            if not row:
                return a

def admin_ok(req) -> bool:
    key = req.args.get("key") or req.form.get("key")
    return bool(ADMIN_KEY) and key == ADMIN_KEY  # ต้องตั้ง ADMIN_KEY และต้องใส่ key ให้ตรงเสมอ

def short_url_for(alias: str) -> str:
    return f"{request.host_url.rstrip('/')}/{alias}"

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
 .msg{margin:12px 0} .row{margin:8px 0} .hint{color:#666;font-size:13px}
</style>
<h2>สร้างลิงก์สั้นของคุณ</h2>
<form method="post">
  <div class="row">URL ต้นฉบับ<br>
    <input type="url" name="long_url" size="60" required placeholder="https://open.spotify.com/...">
  </div>
  <div class="row">alias (ปล่อยว่างเพื่อสุ่ม {{alias_len}} ตัว; ใช้ a-z,0-9,-,_)<br>
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

<p class="hint">
  ไปหน้า <a href="/manage?key={{admin_key}}">จัดการ</a> |
  <a href="/stats?key={{admin_key}}">สถิติ</a>
</p>
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
<p class="muted">แก้ปลายทางแล้วกด Update หรือกด Delete เพื่อถอนการใช้งาน</p>
<table>
<tr><th>Alias</th><th>ปลายทาง (แก้ไขได้)</th><th>คลิก</th><th>สร้างเมื่อ</th><th>ดำเนินการ</th></tr>
{% for r in rows %}
<tr>
  <td><a href="/{{r['alias']}}" target="_blank">/{{r['alias']}}</a></td>
  <td style="word-break:break-all">
    <form method="post" action="/update" class="row">
      <input type="hidden" name="alias" value="{{r['alias']}}">
      <input type="url" name="long_url" value="{{r['long_url']}}" size="50" required>
      <input name="key" value="{{admin_key}}" hidden>
      <button type="submit">Update</button>
    </form>
  </td>
  <td>{{r['clicks']}}</td>
  <td>{{r['created_at']}}</td>
  <td>
    <form method="post" action="/delete" onsubmit="return confirm('ลบ {{r['alias']}} ?')">
      <input type="hidden" name="alias" value="{{r['alias']}}">
      <input name="key" value="{{admin_key}}" hidden>
      <button type="submit">Delete</button>
    </form>
  </td>
</tr>
{% endfor %}
</table>

<p><a href="/?key={{admin_key}}">← กลับหน้าหลัก</a> | <a href="/stats?key={{admin_key}}">ดูสถิติ</a></p>
"""

PAGE_STATS = """
<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stats</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Inter,Arial;margin:24px;max-width:1000px}
 table{border-collapse:collapse;width:100%} th,td{padding:8px;border-bottom:1px solid #eee}
 .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
</style>
<h2>สถิติคลิกรายวัน</h2>
<form class="row" method="get" action="/stats">
  <input type="hidden" name="key" value="{{admin_key}}">
  <label>Alias: <input name="alias" value="{{q_alias or ''}}" placeholder="ว่าง = ทั้งหมด"></label>
  <button type="submit">ค้นหา</button>
  <a href="/export_csv?key={{admin_key}}{% if q_alias %}&alias={{q_alias}}{% endif %}">ดาวน์โหลด CSV</a>
</form>

<table>
<tr><th>วัน (YYYY-MM-DD)</th><th>Alias</th><th>จำนวนคลิก</th></tr>
{% for r in rows %}
<tr><td>{{r['day']}}</td><td>{{r['alias']}}</td><td>{{r['count']}}</td></tr>
{% endfor %}
</table>

<p><a href="/manage?key={{admin_key}}">← กลับจัดการ</a></p>
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
                alias = alias_in
            else:
                alias = unique_alias(ALIAS_LEN)

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
    return render_template_string(PAGE_HOME, msg=msg, short_full=short_full, qr_src=qr_src,
                                  rows=rows, admin_key=ADMIN_KEY, alias_len=ALIAS_LEN)

@app.route("/manage")
def manage():
    if not admin_ok(request):
        return "Unauthorized (ต้องตั้ง ADMIN_KEY และเปิดด้วย ?key=...)", 401
    with db() as conn:
        rows = conn.execute("SELECT alias,long_url,clicks,created_at FROM links ORDER BY created_at DESC").fetchall()
    return render_template_string(PAGE_MANAGE, rows=rows, admin_key=ADMIN_KEY)

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
    return redirect(f"/manage?key={ADMIN_KEY}")

@app.route("/delete", methods=["POST"])
def delete():
    if not admin_ok(request):
        return "Unauthorized", 401
    alias = (request.form.get("alias") or "").lower()
    if not alias:
        return "bad request", 400
    with db() as conn:
        conn.execute("DELETE FROM links WHERE alias=?", (alias,))
    return redirect(f"/manage?key={ADMIN_KEY}")

@app.route("/stats")
def stats():
    if not admin_ok(request):
        return "Unauthorized", 401
    q_alias = (request.args.get("alias") or "").strip().lower()
    with db() as conn:
        if q_alias:
            rows = conn.execute("SELECT day, alias, count FROM clicks_daily WHERE alias=? ORDER BY day DESC",
                                (q_alias,)).fetchall()
        else:
            rows = conn.execute("SELECT day, alias, count FROM clicks_daily ORDER BY day DESC").fetchall()
    return render_template_string(PAGE_STATS, rows=rows, admin_key=ADMIN_KEY, q_alias=q_alias)

@app.route("/export_csv")
def export_csv():
    if not admin_ok(request):
        return "Unauthorized", 401
    q_alias = (request.args.get("alias") or "").strip().lower()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["day", "alias", "count"])
    with db() as conn:
        if q_alias:
            rows = conn.execute("SELECT day, alias, count FROM clicks_daily WHERE alias=? ORDER BY day DESC",
                                (q_alias,)).fetchall()
        else:
            rows = conn.execute("SELECT day, alias, count FROM clicks_daily ORDER BY day DESC").fetchall()
    for r in rows:
        writer.writerow([r["day"], r["alias"], r["count"]])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode("utf-8")),
                     mimetype="text/csv",
                     as_attachment=True,
                     download_name=f"stats_{q_alias or 'all'}.csv")

@app.route("/<alias>")
def go(alias):
    alias = alias.lower()
    with db() as conn:
        row = conn.execute("SELECT long_url FROM links WHERE alias=?", (alias,)).fetchone()
        if not row: abort(404)
        # นับรวม
        conn.execute("UPDATE links SET clicks = clicks + 1 WHERE alias=?", (alias,))
        # นับรายวัน
        today = date.today().isoformat()
        cur = conn.execute("UPDATE clicks_daily SET count = count + 1 WHERE alias=? AND day=?", (alias, today))
        if cur.rowcount == 0:
            conn.execute("INSERT INTO clicks_daily(alias, day, count) VALUES(?,?,1)", (alias, today))
        return redirect(row["long_url"])

# API: POST /api/shorten { "url": "...", "alias": "optional" }
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
        alias = unique_alias(ALIAS_LEN)
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
