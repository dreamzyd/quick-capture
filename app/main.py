from datetime import datetime
from pathlib import Path
import csv
import hashlib
import hmac
import io
import json
import os
import sqlite3
import uuid

from flask import Flask, render_template, request, make_response, Response, redirect, url_for

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("QUICK_CAPTURE_DB", str(BASE_DIR / "quick_capture.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
ADMIN_PASSWORD = os.environ.get("QUICK_CAPTURE_ADMIN_PASSWORD", "")
ADMIN_COOKIE = "qc_admin"

app = Flask(__name__, template_folder=str(BASE_DIR / "app" / "templates"), static_folder=str(BASE_DIR / "app" / "static"))


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn, table_name, column_name, alter_sql):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(alter_sql)


def init_db():
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inbox_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inbox',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT 'default',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            device_id TEXT NOT NULL,
            device_name TEXT,
            token_hash TEXT,
            trusted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_seen_at TEXT
        )
        """
    )
    ensure_column(conn, "inbox_items", "user_id", "ALTER TABLE inbox_items ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "inbox_items", "source_device_id", "ALTER TABLE inbox_items ADD COLUMN source_device_id TEXT")
    ensure_column(conn, "users", "approval_status", "ALTER TABLE users ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'approved'")
    ensure_column(conn, "users", "join_code", "ALTER TABLE users ADD COLUMN join_code TEXT")
    ensure_column(conn, "users", "approved_at", "ALTER TABLE users ADD COLUMN approved_at TEXT")
    ensure_column(conn, "devices", "provision_source", "ALTER TABLE devices ADD COLUMN provision_source TEXT NOT NULL DEFAULT 'direct'")
    conn.execute("UPDATE inbox_items SET user_id = 1 WHERE user_id IS NULL")
    conn.execute("UPDATE users SET approved_at = COALESCE(approved_at, created_at) WHERE approval_status = 'approved'")
    conn.commit()
    conn.close()


def admin_cookie_value():
    if not ADMIN_PASSWORD:
        return None
    return hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()


def is_admin_authenticated():
    expected = admin_cookie_value()
    if not expected:
        return True
    actual = request.cookies.get(ADMIN_COOKIE, "")
    return hmac.compare_digest(actual, expected)


def admin_guard():
    if is_admin_authenticated():
        return None
    next_path = request.path
    if request.query_string:
        next_path += "?" + request.query_string.decode()
    return redirect(url_for("admin_login_page", next=next_path))


def generate_join_code():
    return uuid.uuid4().hex[:12]


def create_pending_user(conn):
    name = f"user-{uuid.uuid4().hex[:6]}"
    join_code = generate_join_code()
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO users (name, approval_status, join_code, created_at) VALUES (?, 'pending', ?, ?)",
        (name, join_code, now),
    )
    user_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return user_id


def ensure_user_join_code(conn, user_id):
    row = conn.execute("SELECT join_code FROM users WHERE id = ?", (user_id,)).fetchone()
    if row and not row["join_code"]:
        conn.execute("UPDATE users SET join_code = ? WHERE id = ?", (generate_join_code(), user_id))


def get_or_create_device(device_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT d.id, d.user_id, d.device_id, d.device_name, d.trusted, d.provision_source, u.approval_status, u.join_code FROM devices d JOIN users u ON u.id = d.user_id WHERE d.device_id = ?",
        (device_id,)
    ).fetchone()
    if not row:
        user_id = create_pending_user(conn)
        provision_source = "first-visit"
        trusted = 0
        conn.execute(
            "INSERT INTO devices (user_id, device_id, device_name, trusted, provision_source) VALUES (?, ?, 'Unknown', ?, ?)",
            (user_id, device_id, trusted, provision_source)
        )
        conn.commit()
        row = conn.execute(
            "SELECT d.id, d.user_id, d.device_id, d.device_name, d.trusted, d.provision_source, u.approval_status, u.join_code FROM devices d JOIN users u ON u.id = d.user_id WHERE d.device_id = ?",
            (device_id,)
        ).fetchone()
    conn.execute(
        "UPDATE devices SET last_seen_at = ? WHERE device_id = ?",
        (datetime.now().isoformat(timespec="seconds"), device_id),
    )
    conn.commit()
    conn.close()
    return dict(row)


def get_items(user_id=None, q=None):
    conn = get_conn()
    if user_id:
        if q:
            rows = conn.execute(
                "SELECT id, user_id, source_device_id, content, status, created_at, updated_at FROM inbox_items WHERE user_id = ? AND content LIKE ? ORDER BY created_at DESC, id DESC",
                (user_id, f"%{q}%")
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, user_id, source_device_id, content, status, created_at, updated_at FROM inbox_items WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                (user_id,)
            ).fetchall()
    else:
        if q:
            rows = conn.execute(
                "SELECT id, user_id, source_device_id, content, status, created_at, updated_at FROM inbox_items WHERE content LIKE ? ORDER BY created_at DESC, id DESC",
                (f"%{q}%",)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, user_id, source_device_id, content, status, created_at, updated_at FROM inbox_items ORDER BY created_at DESC, id DESC"
            ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_account_items(user_id, q=None):
    conn = get_conn()
    user = conn.execute('SELECT id, name, created_at, approval_status, join_code, approved_at FROM users WHERE id = ?', (user_id,)).fetchone()
    if q:
        rows = conn.execute(
            """
            SELECT i.id, i.user_id, i.source_device_id, i.content, i.status, i.created_at, i.updated_at,
                   COALESCE(d.device_name, 'Unknown') AS source_device_name
            FROM inbox_items i
            LEFT JOIN devices d ON d.device_id = i.source_device_id
            WHERE i.user_id = ? AND i.content LIKE ?
            ORDER BY i.created_at DESC, i.id DESC
            """,
            (user_id, f"%{q}%")
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT i.id, i.user_id, i.source_device_id, i.content, i.status, i.created_at, i.updated_at,
                   COALESCE(d.device_name, 'Unknown') AS source_device_name
            FROM inbox_items i
            LEFT JOIN devices d ON d.device_id = i.source_device_id
            WHERE i.user_id = ?
            ORDER BY i.created_at DESC, i.id DESC
            """,
            (user_id,)
        ).fetchall()
    conn.close()
    return (dict(user) if user else {"id": user_id, "name": f"user-{user_id}", "created_at": None}, [dict(r) for r in rows])


def get_device_items(device_id):
    conn = get_conn()
    device = conn.execute(
        "SELECT d.id, d.user_id, d.device_id, d.device_name, d.trusted, d.provision_source, d.created_at, d.last_seen_at, u.approval_status FROM devices d JOIN users u ON u.id = d.user_id WHERE d.device_id = ?",
        (device_id,)
    ).fetchone()
    rows = conn.execute(
        "SELECT id, user_id, source_device_id, content, status, created_at, updated_at FROM inbox_items WHERE source_device_id = ? ORDER BY created_at DESC, id DESC",
        (device_id,)
    ).fetchall()
    conn.close()
    return (dict(device) if device else None, [dict(r) for r in rows])


def get_devices(user_id=None):
    conn = get_conn()
    query = """
        SELECT
            d.id,
            d.user_id,
            d.device_id,
            d.device_name,
            d.trusted,
            d.provision_source,
            d.created_at,
            d.last_seen_at,
            u.approval_status,
            COUNT(i.id) AS item_count
        FROM devices d
        JOIN users u ON u.id = d.user_id
        LEFT JOIN inbox_items i ON i.source_device_id = d.device_id
        WHERE 1 = 1
    """
    params = []
    if user_id is not None:
        query += " AND d.user_id = ?"
        params.append(user_id)
    query += " GROUP BY d.id, d.user_id, d.device_id, d.device_name, d.trusted, d.provision_source, d.created_at, d.last_seen_at, u.approval_status ORDER BY COALESCE(d.last_seen_at, d.created_at) DESC, d.id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_users(approval_status=None):
    conn = get_conn()
    query = """
        SELECT u.id, u.name, u.approval_status, u.join_code, u.created_at, u.approved_at,
               COUNT(DISTINCT d.id) AS device_count,
               COUNT(i.id) AS item_count
        FROM users u
        LEFT JOIN devices d ON d.user_id = u.id
        LEFT JOIN inbox_items i ON i.user_id = u.id
        WHERE 1 = 1
    """
    params = []
    if approval_status is not None:
        query += " AND u.approval_status = ?"
        params.append(approval_status)
    query += " GROUP BY u.id, u.name, u.approval_status, u.join_code, u.created_at, u.approved_at ORDER BY u.created_at DESC, u.id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def approve_user(user_id):
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "UPDATE users SET approval_status = 'approved', approved_at = COALESCE(approved_at, ?), join_code = COALESCE(join_code, ?) WHERE id = ?",
        (now, generate_join_code(), user_id),
    )
    conn.commit()
    conn.close()


def join_account_by_code(device_id, join_code):
    clean_code = (join_code or "").strip()
    if not clean_code:
        return False, "请输入加入码。"
    conn = get_conn()
    user = conn.execute(
        "SELECT id, approval_status FROM users WHERE join_code = ?",
        (clean_code,),
    ).fetchone()
    if not user:
        conn.close()
        return False, "加入码无效。"
    if user["approval_status"] != "approved":
        conn.close()
        return False, "这个账号还没开通。"
    conn.execute(
        "UPDATE devices SET user_id = ?, provision_source = 'join-code', last_seen_at = ? WHERE device_id = ?",
        (user["id"], datetime.now().isoformat(timespec="seconds"), device_id),
    )
    conn.execute(
        "UPDATE inbox_items SET user_id = ? WHERE source_device_id = ?",
        (user["id"], device_id),
    )
    conn.commit()
    conn.close()
    return True, None


def get_account_summary(user_id):
    conn = get_conn()
    user = conn.execute('SELECT id, name, created_at, approval_status, join_code, approved_at FROM users WHERE id = ?', (user_id,)).fetchone()
    device_count = conn.execute('SELECT COUNT(*) AS c FROM devices WHERE user_id = ?', (user_id,)).fetchone()["c"]
    item_count = conn.execute('SELECT COUNT(*) AS c FROM inbox_items WHERE user_id = ?', (user_id,)).fetchone()["c"]
    trusted_device_count = conn.execute('SELECT COUNT(*) AS c FROM devices WHERE user_id = ? AND trusted = 1', (user_id,)).fetchone()["c"]
    conn.close()
    return {
        "user": dict(user) if user else {"id": user_id, "name": f"user-{user_id}", "created_at": None},
        "device_count": device_count,
        "item_count": item_count,
        "trusted_device_count": trusted_device_count,
    }


def update_device_name(device_id, device_name):
    clean_name = (device_name or "").strip()[:80]
    if not clean_name:
        clean_name = "Unknown"
    conn = get_conn()
    conn.execute(
        "UPDATE devices SET device_name = ?, last_seen_at = ? WHERE device_id = ?",
        (clean_name, datetime.now().isoformat(timespec="seconds"), device_id),
    )
    conn.commit()
    conn.close()


def toggle_device_trusted(device_id):
    conn = get_conn()
    row = conn.execute("SELECT trusted FROM devices WHERE device_id = ?", (device_id,)).fetchone()
    if row:
        next_trusted = 0 if row["trusted"] else 1
        conn.execute(
            "UPDATE devices SET trusted = ?, last_seen_at = ? WHERE device_id = ?",
            (next_trusted, datetime.now().isoformat(timespec="seconds"), device_id),
        )
        conn.commit()
    conn.close()


def build_export_filename(ext):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"quick-capture-export-{timestamp}.{ext}"


init_db()


@app.route("/")
def index():
    device_id = request.cookies.get("qc_device_id")
    if not device_id:
        device_id = str(uuid.uuid4())
    device = get_or_create_device(device_id)
    items = get_items(device["user_id"]) if device.get("approval_status") == "approved" else []
    resp = make_response(render_template("index.html", device=device, items=items))
    resp.set_cookie("qc_device_id", device_id, max_age=31536000, httponly=True)
    return resp


@app.route("/admin/login", methods=["GET"])
def admin_login_page():
    return render_template("admin_login.html", error=None)


@app.route("/admin/login", methods=["POST"])
def admin_login_submit():
    next_url = request.args.get("next") or request.form.get("next") or "/admin/accounts"
    password = request.form.get("password", "")
    if ADMIN_PASSWORD and password == ADMIN_PASSWORD:
        resp = make_response(redirect(next_url))
        resp.set_cookie(ADMIN_COOKIE, admin_cookie_value(), max_age=604800, httponly=True)
        return resp
    return render_template("admin_login.html", error="密码不对，请再试一次。")


@app.route("/admin/logout", methods=["GET", "POST"])
def admin_logout():
    resp = make_response(redirect("/"))
    resp.set_cookie(ADMIN_COOKIE, "", expires=0)
    return resp


@app.route("/join", methods=["GET"])
def join_page():
    device_id = request.cookies.get("qc_device_id")
    if not device_id:
        device_id = str(uuid.uuid4())
    device = get_or_create_device(device_id)
    resp = make_response(render_template("join.html", device=device, error=None, success=None))
    resp.set_cookie("qc_device_id", device_id, max_age=31536000, httponly=True)
    return resp


@app.route("/join", methods=["POST"])
def join_submit():
    device_id = request.cookies.get("qc_device_id")
    if not device_id:
        device_id = str(uuid.uuid4())
    device = get_or_create_device(device_id)
    ok, error = join_account_by_code(device_id, request.form.get("join_code", ""))
    joined_device = get_or_create_device(device_id)
    resp = make_response(render_template("join.html", device=joined_device, error=error, success="加入成功，这台设备现在归到同一个账号了。" if ok else None))
    resp.set_cookie("qc_device_id", device_id, max_age=31536000, httponly=True)
    return resp


@app.route("/admin/accounts")
def admin_accounts_page():
    guard = admin_guard()
    if guard:
        return guard
    pending_users = get_users("pending")
    approved_users = get_users("approved")
    return render_template("admin_accounts.html", pending_users=pending_users, approved_users=approved_users)


@app.route("/admin/accounts/approve/<int:user_id>", methods=["POST"])
def approve_user_route(user_id):
    guard = admin_guard()
    if guard:
        return guard
    approve_user(user_id)
    return redirect(url_for("admin_accounts_page"))


@app.route("/me")
def me_page():
    device_id = request.cookies.get("qc_device_id")
    if not device_id:
        return redirect(url_for("index"))
    device = get_or_create_device(device_id)
    summary = get_account_summary(device["user_id"])
    devices = get_devices(user_id=device["user_id"])
    return render_template("me.html", summary=summary, devices=devices, current_device_id=device_id, is_admin=is_admin_authenticated())


@app.route("/account")
def account_page():
    return redirect(url_for("me_page"))


@app.route("/devices")
def devices_page():
    return redirect(url_for("me_page"))


@app.route("/account/items")
def account_items_page():
    guard = admin_guard()
    if guard:
        return guard
    raw_user_id = request.args.get("user_id")
    if raw_user_id:
        user_id = int(raw_user_id)
    else:
        approved_users = get_users("approved")
        if not approved_users:
            return redirect(url_for("admin_accounts_page"))
        user_id = approved_users[0]["id"]
    q = request.args.get("q", "").strip()
    user, items = get_account_items(user_id, q if q else None)
    return render_template("account_items.html", user=user, items=items, q=q)


@app.route("/devices/<device_id>/items")
def device_items_page(device_id):
    guard = admin_guard()
    if guard:
        return guard
    device, items = get_device_items(device_id)
    return render_template("device_items.html", device=device, items=items)


@app.route("/devices/rename/<device_id>", methods=["POST"])
def rename_device(device_id):
    current_device_id = request.cookies.get("qc_device_id")
    if current_device_id == device_id:
        update_device_name(device_id, request.form.get("device_name", ""))
        return redirect(url_for("index"))
    guard = admin_guard()
    if guard:
        return guard
    update_device_name(device_id, request.form.get("device_name", ""))
    return redirect(url_for("devices_page"))


@app.route("/devices/toggle-trusted/<device_id>", methods=["POST"])
def toggle_device(device_id):
    guard = admin_guard()
    if guard:
        return guard
    toggle_device_trusted(device_id)
    return redirect(url_for("devices_page"))


@app.route("/add", methods=["POST"])
def add_item():
    raw = request.form.get("content", "")
    device_id = request.cookies.get("qc_device_id")
    device = get_or_create_device(device_id) if device_id else None
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    added_count = 0
    if lines:
        now = datetime.now().isoformat(timespec="seconds")
        conn = get_conn()
        for content in lines:
            conn.execute(
                "INSERT INTO inbox_items (user_id, source_device_id, content, status, created_at, updated_at) VALUES (?, ?, ?, 'inbox', ?, ?)",
                (device["user_id"] if device else 1, device_id, content, now, now),
            )
            added_count += 1
        conn.commit()
        conn.close()
    if device and device.get("approval_status") == "approved":
        return render_template("_list.html", items=get_items(device["user_id"]))
    return render_template("_capture_result.html", added_count=added_count)


@app.route("/export.csv")
def export_csv():
    guard = admin_guard()
    if guard:
        return guard
    items = get_items()
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "user_id", "source_device_id", "content", "status", "created_at", "updated_at"])
    writer.writeheader()
    writer.writerows(items)
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={build_export_filename('csv')}"},
    )


@app.route("/export.json")
def export_json():
    guard = admin_guard()
    if guard:
        return guard
    payload = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "items": get_items(),
    }
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={build_export_filename('json')}"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=18901, debug=False)
