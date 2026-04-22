from flask import Flask, render_template, request, redirect, session, flash, send_file
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch
from io import BytesIO

app = Flask(__name__)
app.secret_key = "secretkey"
DATABASE = "database.db"

# ========================
# KONFIGURASI EMAIL (HARDCODE)
# ========================
SMTP_EMAIL = "skybooking04@gmail.com"  # GANTI DENGAN EMAIL ANDA
SMTP_PASSWORD = "geio paig xqot zfsf"  # GANTI DENGAN APP PASSWORD ANDA
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# ========================
# DATABASE CONNECTION
# ========================
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.set_trace_callback(print) # Baris ini akan mencetak setiap query SQL yg dijalankan ke terminal
    return conn

# ========================
# INIT DATABASE
# ========================
def init_db():
    conn = get_db()
    c = conn.cursor()

    # Tabel Users
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            email TEXT,
            password TEXT,
            role TEXT,
            is_active INTEGER DEFAULT 0
        )
    """)

    # Tabel Gate Status
    c.execute("""
        CREATE TABLE IF NOT EXISTS gate_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT,
            updated_at TEXT
        )
    """)

    # Tabel Activity Logs
    c.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            action TEXT,
            timestamp TEXT
        )
    """)

    # Tabel Settings
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notification_limit INTEGER,
            email_recipient TEXT
        )
    """)

    # Default Settings
    c.execute("SELECT * FROM settings")
    if not c.fetchone():
        c.execute("INSERT INTO settings (notification_limit, email_recipient) VALUES (1, '')")

    # Default Gate Status
    c.execute("SELECT * FROM gate_status")
    if not c.fetchone():
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO gate_status (status, updated_at) VALUES (?, ?)", ("Tertutup", now))

    # Default Admin
    c.execute("SELECT * FROM users WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, email, password, role, is_active) VALUES (?, ?, ?, ?, ?)",
                  ("admin", "admin@garasi.com", generate_password_hash("123"), "admin", 1))

    conn.commit()
    conn.close()

init_db()

# ========================
# FUNGSI EMAIL NOTIFIKASI
# ========================
def send_email(to_email, subject, html_content):
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True, "Email berhasil dikirim!"
    except Exception as e:
        print(f"Email Error: {e}")
        return False, f"Gagal: {str(e)}"

# ========================
# FUNGSI GENERATE PDF
# ========================
def generate_pdf_report(logs):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()
    
    title = Paragraph("Laporan Aktivitas Garasi Smart", styles['Title'])
    elements.append(title)
    elements.append(Spacer(1, 0.2*inch))
    
    data = [['No', 'Username', 'Aksi', 'Waktu']]
    for idx, log in enumerate(logs, 1):
        data.append([str(idx), log['username'], log['action'], log['timestamp']])
    
    table = Table(data, colWidths=[0.5*inch, 2*inch, 2*inch, 2.5*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return buffer

# ========================
# ROUTES: AUTH
# ========================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            if user["is_active"] == 0:
                return render_template("login.html", error="Akun menunggu persetujuan Admin.")
            
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect("/dashboard")

        return render_template("login.html", error="Username atau Password salah")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]
        
        conn = get_db()
        try:
            conn.execute("INSERT INTO users (username, email, password, role, is_active) VALUES (?, ?, ?, ?, ?)",
                         (username, email, generate_password_hash(password), "user", 0))
            conn.commit()
            flash("Registrasi Berhasil! Tunggu admin menyetujui akun Anda.", "success")
            return redirect("/")
        except sqlite3.IntegrityError:
            flash("Username sudah digunakan!", "error")
        finally:
            conn.close()
            
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ========================
# ROUTES: DASHBOARD
# ========================
@app.route("/dashboard")
def dashboard():
    if "username" not in session:
        return redirect("/")

    conn = get_db()
    
    # Data Pagar & Setting
    gate = conn.execute("SELECT * FROM gate_status ORDER BY id DESC LIMIT 1").fetchone()
    setting = conn.execute("SELECT * FROM settings").fetchone()
    setting_val = setting["notification_limit"] if setting else 1
    
    # Hitung Durasi & Alert
    alert_status = False
    duration_str = ""
    duration_minutes = 0
    if gate:
        last_update = datetime.strptime(gate['updated_at'], "%Y-%m-%d %H:%M:%S")
        diff = datetime.now() - last_update
        if gate['status'] == 'Terbuka' and diff.total_seconds() > (setting_val * 60):
            alert_status = True
            duration_minutes = int(diff.total_seconds() // 60)
            duration_str = f"{duration_minutes} Menit"

    if session["role"] == "admin":
        # ... (kode ambil user pending & active tetap sama) ...
        pending_users = conn.execute("SELECT * FROM users WHERE is_active = 0").fetchall()
        active_users = conn.execute("SELECT * FROM users WHERE is_active = 1").fetchall()
        logs = conn.execute("SELECT * FROM activity_logs ORDER BY id DESC LIMIT 5").fetchall()
        
        # === PERBAIKAN LOGIKA CHART DENGAN FILTER ===
        chart_filter = request.args.get('filter', 'harian')
        labels = []
        data_buka = []
        data_tutup = []
        
        if chart_filter == 'bulanan':
            for i in range(5, -1, -1):
                d = datetime.now()
                month = d.month - i
                year = d.year
                while month <= 0:
                    month += 12
                    year -= 1
                month_str = f"{year}-{month:02d}"
                month_names = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Ags", "Sep", "Okt", "Nov", "Des"]
                labels.append(f"{month_names[month-1]} {year}")
                
                count_buka = conn.execute("SELECT COUNT(*) FROM activity_logs WHERE action='Buka Pagar' AND timestamp LIKE ?", (f"{month_str}%",)).fetchone()[0]
                count_tutup = conn.execute("SELECT COUNT(*) FROM activity_logs WHERE action='Tutup Pagar' AND timestamp LIKE ?", (f"{month_str}%",)).fetchone()[0]
                data_buka.append(count_buka)
                data_tutup.append(count_tutup)
        elif chart_filter == 'mingguan':
            for i in range(3, -1, -1):
                end_date = datetime.now() - timedelta(days=i*7)
                start_date = end_date - timedelta(days=6)
                
                lbl = f"{start_date.strftime('%d %b')} - {end_date.strftime('%d %b')}"
                labels.append(lbl)
                
                sd_str = start_date.strftime("%Y-%m-%d 00:00:00")
                ed_str = end_date.strftime("%Y-%m-%d 23:59:59")
                
                count_buka = conn.execute("SELECT COUNT(*) FROM activity_logs WHERE action='Buka Pagar' AND timestamp BETWEEN ? AND ?", (sd_str, ed_str)).fetchone()[0]
                count_tutup = conn.execute("SELECT COUNT(*) FROM activity_logs WHERE action='Tutup Pagar' AND timestamp BETWEEN ? AND ?", (sd_str, ed_str)).fetchone()[0]
                data_buka.append(count_buka)
                data_tutup.append(count_tutup)
        else: # harian (7 hari terakhir)
            for i in range(6, -1, -1):
                date_check = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                day_name = (datetime.now() - timedelta(days=i)).strftime("%A") 
                days_map = {'Monday':'Senin', 'Tuesday':'Selasa', 'Wednesday':'Rabu', 'Thursday':'Kamis', 'Friday':'Jumat', 'Saturday':'Sabtu', 'Sunday':'Minggu'}
                labels.append(days_map.get(day_name, day_name))
                
                count_buka = conn.execute("SELECT COUNT(*) FROM activity_logs WHERE action='Buka Pagar' AND timestamp LIKE ?", (f"{date_check}%",)).fetchone()[0]
                count_tutup = conn.execute("SELECT COUNT(*) FROM activity_logs WHERE action='Tutup Pagar' AND timestamp LIKE ?", (f"{date_check}%",)).fetchone()[0]
                data_buka.append(count_buka)
                data_tutup.append(count_tutup)

        # Hitung Total Hari Ini
        today = datetime.now().strftime("%Y-%m-%d")
        stats_today = conn.execute("SELECT COUNT(*) FROM activity_logs WHERE timestamp LIKE ?", (f"{today}%",)).fetchone()[0]

        conn.close()
        return render_template("admin_dashboard.html",
                               username=session["username"],
                               status=gate["status"],
                               logs=logs,
                               setting=setting_val,
                               alert=alert_status,
                               duration=duration_str,
                               stats_today=stats_today,
                               pending_users=pending_users,
                               active_users=active_users,
                               chart_labels=json.dumps(labels),
                               chart_buka=json.dumps(data_buka),
                               chart_tutup=json.dumps(data_tutup),
                               current_filter=chart_filter)
    else:
        conn.close()
        return render_template("user_dashboard.html",
                               username=session["username"],
                               status=gate["status"],
                               alert=alert_status,
                               duration=duration_str)

# ========================
# ROUTES: APPROVAL ACTION
# ========================
@app.route("/approve/<int:user_id>")
def approve_user(user_id):
    if session.get("role") != "admin": return redirect("/")
    
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    
    if user:
        conn.execute("UPDATE users SET is_active=1 WHERE id=?", (user_id,))
        conn.commit()
        
        if user["email"]:
            html = f"<h2>Halo {user['username']}!</h2><p>Akun Anda telah <b>DISETUJUI</b> oleh Admin. Silakan login sekarang.</p>"
            send_email(user["email"], "Akun Garasi Smart Disetujui ✅", html)
            
        flash(f"User {user['username']} berhasil disetujui!", "success")
    
    conn.close()
    return redirect("/dashboard")

@app.route("/reject/<int:user_id>")
def reject_user(user_id):
    if session.get("role") != "admin": return redirect("/")
    
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    flash("Permintaan user ditolak.", "warning")
    return redirect("/dashboard")

# ========================
# ROUTES: LAINNYA
# ========================
@app.route("/open")
def open_gate():
    if "username" not in session: return redirect("/")
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT INTO gate_status (status, updated_at) VALUES (?, ?)", ("Terbuka", now))
    conn.execute("INSERT INTO activity_logs (username, action, timestamp) VALUES (?, ?, ?)", (session["username"], "Buka Pagar", now))
    conn.commit()
    conn.close()
    return redirect("/dashboard")

@app.route("/close")
def close_gate():
    if "username" not in session: return redirect("/")
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT INTO gate_status (status, updated_at) VALUES (?, ?)", ("Tertutup", now))
    conn.execute("INSERT INTO activity_logs (username, action, timestamp) VALUES (?, ?, ?)", (session["username"], "Tutup Pagar", now))
    conn.commit()
    conn.close()
    return redirect("/dashboard")

@app.route("/send_alert")
def send_alert():
    if "username" not in session: return redirect("/")
    conn = get_db()
    setting = conn.execute("SELECT * FROM settings").fetchone()
    conn.close()
    
    if setting and setting['email_recipient']:
        html = "<h2>PERINGATAN!</h2><p>Pagar terbuka terlalu lama.</p>"
        send_email(setting['email_recipient'], "⚠️ Peringatan Garasi", html)
        flash("Alert terkirim!", "success")
    return redirect("/dashboard")

@app.route("/update_setting", methods=["POST"])
def update_setting():
    if "role" not in session or session["role"] != "admin": 
        return redirect("/dashboard")
    
    limit = request.form["limit"]
    # Email recipient dihapus dari form, jadi kita tidak update kolom itu
    # Atau jika ingin dikosongkan, bisa di-set string kosong
    
    conn = get_db()
    # Hanya update notification_limit
    conn.execute("UPDATE settings SET notification_limit=?", (limit,))
    conn.commit()
    conn.close()
    
    flash("Pengaturan berhasil disimpan!", "success")
    return redirect("/settings")

@app.route("/settings")
def settings():
    if session.get("role") != "admin": return redirect("/")
    conn = get_db()
    setting = conn.execute("SELECT * FROM settings").fetchone()
    conn.close()
    return render_template("settings.html", username=session["username"], setting=setting)

def get_filtered_logs(filter_type):
    conn = get_db()
    if filter_type == 'harian':
        today = datetime.now().strftime("%Y-%m-%d")
        logs = conn.execute("SELECT * FROM activity_logs WHERE timestamp LIKE ? ORDER BY id DESC", (f"{today}%",)).fetchall()
    elif filter_type == 'mingguan':
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
        logs = conn.execute("SELECT * FROM activity_logs WHERE timestamp >= ? ORDER BY id DESC", (start_date,)).fetchall()
    elif filter_type == 'bulanan':
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")
        logs = conn.execute("SELECT * FROM activity_logs WHERE timestamp >= ? ORDER BY id DESC", (start_date,)).fetchall()
    else:
        logs = conn.execute("SELECT * FROM activity_logs ORDER BY id DESC").fetchall()
    conn.close()
    return logs

@app.route("/laporan")
def laporan():
    if session.get("role") != "admin": return redirect("/")
    filter_type = request.args.get('filter', 'semua')
    logs = get_filtered_logs(filter_type)
    return render_template("laporan.html", logs=logs, username=session["username"], current_filter=filter_type)

@app.route("/download_pdf")
def download_pdf():
    if session.get("role") != "admin": return redirect("/")
    filter_type = request.args.get('filter', 'semua')
    logs = get_filtered_logs(filter_type)
    return send_file(generate_pdf_report(logs), mimetype='application/pdf', as_attachment=True, download_name=f'laporan_{filter_type}.pdf')

if __name__ == "__main__":
    app.run(debug=True)