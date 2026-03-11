from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from functools import wraps
import sqlite3
import bcrypt
import jwt
import os
import json
import requests
from datetime import datetime, timedelta

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app, supports_credentials=True, origins="*")

DATABASE = "database.db"
JWT_SECRET = os.environ.get("JWT_SECRET", "change-this-in-production-use-env-var")
JWT_EXPIRY_HOURS = 8
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# ================= AI SETUP =================

def analyze_complaint(complaint_text):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{
                "parts": [{
                    "text": f"""Analyze this complaint and return ONLY a JSON response:
Complaint: "{complaint_text}"

Return exactly this format:
{{
    "category": "one of: Technical/Billing/Service/General/Infrastructure",
    "priority": "one of: High/Medium/Low",
    "sentiment": "one of: Angry/Neutral/Satisfied",
    "summary": "one line summary under 15 words",
    "suggested_reply": "a professional reply under 30 words"
}}"""
                }]
            }]
        }
        response = requests.post(url, json=payload)
        result = response.json()
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        return {
            "category": "General",
            "priority": "Medium",
            "sentiment": "Neutral",
            "summary": complaint_text[:50],
            "suggested_reply": "Thank you for your complaint. We will resolve it shortly."
        }

# ================= DATABASE =================

def connect_db():
    conn = sqlite3.connect(DATABASE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db():
    conn = connect_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin','staff')),
        full_name TEXT DEFAULT '',
        email TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        created_at TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS complaints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        category TEXT DEFAULT 'General',
        priority TEXT DEFAULT 'Medium',
        complaint TEXT NOT NULL,
        status TEXT DEFAULT 'Pending',
        reply TEXT DEFAULT '',
        assigned_to TEXT DEFAULT 'Not Assigned',
        created_at TEXT,
        updated_at TEXT,
        resolved_at TEXT,
        sla_deadline TEXT,
        sentiment TEXT DEFAULT 'Neutral',
        ai_summary TEXT DEFAULT '',
        suggested_reply TEXT DEFAULT ''
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        complaint_id INTEGER,
        action TEXT,
        performed_by TEXT,
        details TEXT,
        timestamp TEXT,
        FOREIGN KEY(complaint_id) REFERENCES complaints(id) ON DELETE CASCADE
    )""")

    # Migration - add AI columns if not exists
    try:
        cur.execute("ALTER TABLE complaints ADD COLUMN sentiment TEXT DEFAULT 'Neutral'")
    except:
        pass
    try:
        cur.execute("ALTER TABLE complaints ADD COLUMN ai_summary TEXT DEFAULT ''")
    except:
        pass
    try:
        cur.execute("ALTER TABLE complaints ADD COLUMN suggested_reply TEXT DEFAULT ''")
    except:
        pass

    cur.execute("SELECT id FROM users WHERE username='admin'")
    if not cur.fetchone():
        hashed = bcrypt.hashpw(b"Admin@1234", bcrypt.gensalt()).decode()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO users (username,password_hash,role,full_name,email,created_at) VALUES (?,?,?,?,?,?)",
                    ("admin", hashed, "admin", "System Admin", "admin@system.com", now))

    for uname, fname in [("staff1","Alice Johnson"),("staff2","Bob Smith")]:
        cur.execute("SELECT id FROM users WHERE username=?", (uname,))
        if not cur.fetchone():
            hashed = bcrypt.hashpw(b"Staff@1234", bcrypt.gensalt()).decode()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("INSERT INTO users (username,password_hash,role,full_name,email,created_at) VALUES (?,?,?,?,?,?)",
                        (uname, hashed, "staff", fname, f"{uname}@system.com", now))

    conn.commit()
    conn.close()

init_db()

# ================= JWT HELPERS =================

def create_token(user_id, username, role):
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def decode_token(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def get_current_user():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return decode_token(auth[7:])
    return None

def require_auth(roles=None):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({"error": "Unauthorized - please login"}), 401
            if roles and user.get("role") not in roles:
                return jsonify({"error": "Forbidden - insufficient permissions"}), 403
            request.current_user = user
            return f(*args, **kwargs)
        return wrapper
    return decorator

def log_activity(conn, complaint_id, action, performed_by, details=""):
    conn.execute(
        "INSERT INTO activity_log (complaint_id,action,performed_by,details,timestamp) VALUES (?,?,?,?,?)",
        (complaint_id, action, performed_by, details, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )

def sla_deadline(priority):
    hours = {"High": 4, "Medium": 24, "Low": 72}.get(priority, 24)
    return (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

# ================= FRONTEND =================

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/<path:filename>")
def serve_frontend(filename):
    return send_from_directory(app.static_folder, filename)

# ================= AI ANALYSIS =================

@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    complaint_text = data.get("complaint", "")
    if not complaint_text:
        return jsonify({"error": "Complaint text required"}), 400
    result = analyze_complaint(complaint_text)
    return jsonify(result)

# ================= AUTH =================

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=? AND is_active=1", (username,))
    user = cur.fetchone()
    conn.close()

    if not user or not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return jsonify({"error": "Invalid credentials"}), 401

    token = create_token(user["id"], user["username"], user["role"])
    return jsonify({
        "token": token,
        "role": user["role"],
        "username": user["username"],
        "full_name": user["full_name"]
    })

@app.route("/api/me")
@require_auth()
def me():
    return jsonify(request.current_user)

# ================= COMPLAINTS (PUBLIC) =================

@app.route("/api/submit", methods=["POST"])
def submit():
    data = request.get_json()
    name = data.get("name", "").strip()
    complaint = data.get("complaint", "").strip()
    email = data.get("email", "").strip()
    phone = data.get("phone", "").strip()
    category = data.get("category", "General")
    priority = data.get("priority", "Medium")

    if not name or not complaint:
        return jsonify({"error": "Name and complaint are required"}), 400

    ai_result = analyze_complaint(complaint)
    category = ai_result.get("category", category)
    priority = ai_result.get("priority", priority)
    sentiment = ai_result.get("sentiment", "Neutral")
    summary = ai_result.get("summary", "")
    suggested_reply = ai_result.get("suggested_reply", "")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    deadline = sla_deadline(priority)

    conn = connect_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO complaints (name,email,phone,category,priority,complaint,status,reply,assigned_to,created_at,updated_at,sla_deadline,sentiment,ai_summary,suggested_reply)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (name, email, phone, category, priority, complaint, "Pending", "", "Not Assigned", now, now, deadline, sentiment, summary, suggested_reply))
    cid = cur.lastrowid
    log_activity(conn, cid, "SUBMITTED", name, f"Priority: {priority}, Category: {category}, Sentiment: {sentiment}")
    conn.commit()
    conn.close()
    return jsonify({
        "message": "Complaint submitted successfully",
        "id": cid,
        "sla_deadline": deadline,
        "ai_analysis": {
            "category": category,
            "priority": priority,
            "sentiment": sentiment,
            "summary": summary,
            "suggested_reply": suggested_reply
        }
    })

@app.route("/api/status/<int:cid>")
def status(cid):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT id,name,category,priority,complaint,status,reply,assigned_to,created_at,updated_at,resolved_at,sla_deadline,sentiment,ai_summary FROM complaints WHERE id=?", (cid,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Complaint not found"}), 404
    return jsonify(dict(row))

# ================= ADMIN =================

@app.route("/api/admin/complaints")
@require_auth(roles=["admin"])
def admin_complaints():
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM complaints ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/admin/stats")
@require_auth(roles=["admin"])
def admin_stats():
    conn = connect_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) as total FROM complaints")
    total = cur.fetchone()["total"]

    cur.execute("SELECT COUNT(*) as c FROM complaints WHERE status='Pending'")
    pending = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(*) as c FROM complaints WHERE status='In Progress'")
    in_progress = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(*) as c FROM complaints WHERE status='Resolved'")
    resolved = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(*) as c FROM complaints WHERE priority='High' AND status != 'Resolved'")
    high_priority = cur.fetchone()["c"]

    cur.execute("""
        SELECT assigned_to, COUNT(*) as count FROM complaints
        WHERE assigned_to != 'Not Assigned'
        GROUP BY assigned_to
    """)
    by_staff = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT category, COUNT(*) as count FROM complaints GROUP BY category")
    by_category = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT strftime('%Y-%m-%d', created_at) as day, COUNT(*) as count
        FROM complaints
        GROUP BY day ORDER BY day DESC LIMIT 7
    """)
    daily = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT sentiment, COUNT(*) as count FROM complaints GROUP BY sentiment")
    by_sentiment = [dict(r) for r in cur.fetchall()]

    conn.close()
    return jsonify({
        "total": total, "pending": pending,
        "in_progress": in_progress, "resolved": resolved,
        "high_priority": high_priority,
        "by_staff": by_staff, "by_category": by_category,
        "daily_trend": daily,
        "by_sentiment": by_sentiment
    })

@app.route("/api/admin/staff-list")
@require_auth(roles=["admin"])
def staff_list():
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT id,username,full_name,email,is_active FROM users WHERE role='staff'")
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/update/<int:cid>", methods=["PUT"])
@require_auth(roles=["admin","staff"])
def update_complaint(cid):
    user = request.current_user
    data = request.get_json()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM complaints WHERE id=?", (cid,))
    existing = cur.fetchone()
    if not existing:
        conn.close()
        return jsonify({"error": "Not found"}), 404

    if user["role"] == "admin":
        new_status = data.get("status", existing["status"])
        assigned_to = data.get("assigned_to", existing["assigned_to"]) or "Not Assigned"
        priority = data.get("priority", existing["priority"])
        old_resolved_at = existing["resolved_at"] if existing["resolved_at"] else None
        resolved_at = now if new_status == "Resolved" and existing["status"] != "Resolved" else old_resolved_at
        cur.execute("""
            UPDATE complaints SET status=?,assigned_to=?,priority=?,updated_at=?,resolved_at=? WHERE id=?
        """, (new_status, assigned_to, priority, now, resolved_at, cid))
        log_activity(conn, cid, "ADMIN_UPDATE", user["username"], f"Status→{new_status}, Assigned→{assigned_to}")
    else:
        if existing["assigned_to"] != user["username"]:
            conn.close()
            return jsonify({"error": "Not your complaint"}), 403
        new_status = data.get("status", existing["status"])
        reply = data.get("reply", existing["reply"]) or ""
        old_resolved_at = existing["resolved_at"] if existing["resolved_at"] else None
        resolved_at = now if new_status == "Resolved" and existing["status"] != "Resolved" else old_resolved_at
        cur.execute("""
            UPDATE complaints SET status=?,reply=?,updated_at=?,resolved_at=? WHERE id=? AND assigned_to=?
        """, (new_status, reply, now, resolved_at, cid, user["username"]))
        log_activity(conn, cid, "STAFF_UPDATE", user["username"], f"Status→{new_status}, Reply added")

    conn.commit()
    conn.close()
    return jsonify({"message": "Updated successfully"})

@app.route("/api/delete/<int:cid>", methods=["DELETE"])
@require_auth(roles=["admin"])
def delete_complaint(cid):
    conn = connect_db()
    conn.execute("DELETE FROM complaints WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted"})

@app.route("/api/complaints/<int:cid>/log")
@require_auth(roles=["admin","staff"])
def complaint_log(cid):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM activity_log WHERE complaint_id=? ORDER BY id DESC", (cid,))
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ================= STAFF =================

@app.route("/api/staff/complaints")
@require_auth(roles=["staff"])
def staff_complaints():
    user = request.current_user
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM complaints WHERE assigned_to=? ORDER BY id DESC", (user["username"],))
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/staff/stats")
@require_auth(roles=["staff"])
def staff_stats():
    user = request.current_user
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM complaints WHERE assigned_to=?", (user["username"],))
    total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM complaints WHERE assigned_to=? AND status='Resolved'", (user["username"],))
    resolved = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM complaints WHERE assigned_to=? AND status='Pending'", (user["username"],))
    pending = cur.fetchone()["c"]
    conn.close()
    return jsonify({"total": total, "resolved": resolved, "pending": pending})

# ================= RUN =================

if __name__ == "__main__":
    app.run(debug=False, port=5001)