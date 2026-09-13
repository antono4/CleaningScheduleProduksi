"""Cleaning Schedule Produksi - Aplikasi manajemen jadwal pembersihan mesin/area produksi."""
import csv
import io
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import (Flask, flash, g, redirect, render_template, request,
                   send_file, url_for)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "cleaning_schedule.db"

app = Flask(__name__)
app.secret_key = "cleaning-schedule-produksi-dev-key"

SHIFTS = {
    "Shift 1": {"label": "Shift 1 (06:00-14:00)", "start": "06:00", "end": "14:00"},
    "Shift 2": {"label": "Shift 2 (14:00-22:00)", "start": "14:00", "end": "22:00"},
    "Shift 3": {"label": "Shift 3 (22:00-06:00)", "start": "22:00", "end": "06:00"},
}
STATUS_LABELS = {
    "scheduled": "Terjadwal",
    "in_progress": "Dalam Proses",
    "done": "Selesai",
    "overdue": "Terlambat",
}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS machines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            area TEXT NOT NULL DEFAULT '',
            cleaning_type TEXT NOT NULL DEFAULT 'Rutin',
            frequency_days INTEGER NOT NULL DEFAULT 1,
            standard_time_minutes INTEGER NOT NULL DEFAULT 30,
            is_active INTEGER NOT NULL DEFAULT 1,
            notes TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id INTEGER NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
            cleaning_date TEXT NOT NULL,
            shift TEXT NOT NULL DEFAULT 'Shift 1',
            time_start TEXT NOT NULL DEFAULT '',
            time_end TEXT NOT NULL DEFAULT '',
            assigned_to TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'scheduled',
            notes TEXT NOT NULL DEFAULT '',
            last_done_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_sched_date ON schedules(cleaning_date);
        CREATE INDEX IF NOT EXISTS idx_sched_machine ON schedules(machine_id);
        """
    )
    # PGDATA base data jika database baru kosong
    machines = db.execute("SELECT COUNT(*) AS c FROM machines").fetchone()[0]
    if machines == 0:
        sample = [
            ("Mesin Injection A", "Area Produksi 1", "Rutin", 1, 30, 1, ""),
            ("Mesin Injection B", "Area Produksi 1", "Rutin", 1, 45, 1, ""),
            ("Mesin Blow Mold C", "Area Produksi 2", "Rutin", 2, 60, 1, ""),
            ("Mesin Cutting D", "Area Produksi 2", "Rutin", 2, 30, 1, ""),
            ("Mesin Packing E", "Area Packing", "Rutin", 3, 20, 1, ""),
            ("Area Warehouse", "Gudang", "Deep Clean", 7, 120, 1, "Pembersihan menyeluruh tiap 7 hari"),
        ]
        db.executemany(
            """INSERT INTO machines
               (name, area, cleaning_type, frequency_days, standard_time_minutes, is_active, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            sample,
        )
    db.commit()
    db.close()


def status_of(row):
    """Status efektif sebuah jadwal (overdue jika belum selesai & waktunya lewat)."""
    status = row["status"]
    if status in ("scheduled", "in_progress"):
        d = row["cleaning_date"]
        if d == date.today().isoformat():
            time_up = (row["time_end"] or SHIFTS[row["shift"]]["end"] or "23:59")
            if time_up and time_up < datetime.now().strftime("%H:%M"):
                return "overdue"
        elif d < date.today().isoformat():
            return "overdue"
    return status


def load_machine_options():
    db = get_db()
    rows = db.execute(
        "SELECT id, name, area FROM machines WHERE is_active = 1 ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def dictify(row, effective_status=None):
    d = dict(row)
    d["status_effective"] = effective_status or status_of(row)
    d["status_label"] = STATUS_LABELS[d["status_effective"]]
    return d


def validate_dates(start, end):
    start_d, end_d = None, None
    if start:
        try:
            start_d = datetime.strptime(start, "%Y-%m-%d").date()
        except ValueError:
            flash("Format tanggal mulai tidak valid.", "error")
    if end:
        try:
            end_d = datetime.strptime(end, "%Y-%m-%d").date()
        except ValueError:
            flash("Format tanggal selesai tidak valid.", "error")
    if start_d and end_d and start_d > end_d:
        flash("Tanggal mulai tidak boleh setelah tanggal selesai.", "error")
        return None, None
    return start_d, end_d


@app.template_filter("shift_time")
def shift_time(shift):
    return SHIFTS.get(shift, {}).get("start", "")


# ---------------------------- Halaman ----------------------------

@app.route("/")
def index():
    db = get_db()
    today = date.today().isoformat()
    now_hm = datetime.now().strftime("%H:%M")

    total_machines = db.execute(
        "SELECT COUNT(*) c FROM machines WHERE is_active = 1"
    ).fetchone()["c"]

    def status_query(clause, params):
        return db.execute(
            f"""SELECT s.*, m.name AS machine_name, m.area, m.cleaning_type,
                       m.standard_time_minutes, m.notes AS machine_notes
                FROM schedules s JOIN machines m ON s.machine_id = m.id
                WHERE s.cleaning_date = ? AND {clause}""",
            [today] + params,
        ).fetchall()

    today_rows = db.execute(
        """SELECT s.*, m.name AS machine_name, m.area, m.cleaning_type,
                  m.standard_time_minutes, m.notes AS machine_notes
           FROM schedules s JOIN machines m ON s.machine_id = m.id
           WHERE s.cleaning_date = ? AND m.is_active = 1
           ORDER BY s.time_start, s.shift, m.name""",
        [today],
    ).fetchall()
    today_rows = [dictify(r) for r in today_rows]

    count_done = sum(1 for r in today_rows if r["status_effective"] == "done")
    count_overdue = sum(1 for r in today_rows if r["status_effective"] == "overdue")
    count_progress = sum(1 for r in today_rows if r["status_effective"] == "in_progress")
    count_pending = sum(1 for r in today_rows if r["status_effective"] == "scheduled")

    # Perhatian: jadwal terlambat hari ini + kemarin yang belum selesai
    attention = db.execute(
        """SELECT s.*, m.name AS machine_name, m.area, m.cleaning_type
           FROM schedules s JOIN machines m ON s.machine_id = m.id
           WHERE s.cleaning_date < ? AND s.status != 'done'
           ORDER BY s.cleaning_date DESC, s.time_start LIMIT 8""",
        [today],
    ).fetchall()
    attention = [dictify(r) for r in attention]

    # Aktifitas terakhir
    recent = db.execute(
        """SELECT s.*, m.name AS machine_name, m.area
           FROM schedules s JOIN machines m ON s.machine_id = m.id
           WHERE s.last_done_at != ''
           ORDER BY s.last_done_at DESC LIMIT 6""",
    ).fetchall()

    # Statistik 7 hari
    week_stats, labels, done_counts = [], [], []
    for i in range(6, -1, -1):
        d = (date.today() - timedelta(days=i)).isoformat()
        rows = db.execute(
            """SELECT cleaning_date, status, time_end, shift
               FROM schedules WHERE cleaning_date = ?""", [d]
        ).fetchall()
        total = len(rows)
        done = sum(1 for r in rows if status_of(r) == "done")
        labels.append((date.today() - timedelta(days=i)).strftime("%a %d/%m"))
        done_counts.append(done)
        week_stats.append(
            {"date": d, "label": labels[-1], "total": total, "done": done,
             "today": d == today}
        )

    overdue_history = db.execute(
        """SELECT s.*, m.name AS machine_name, m.area FROM schedules s
           JOIN machines m ON s.machine_id = m.id
           WHERE s.cleaning_date < ? AND s.status != 'done'""",
        [today],
    ).fetchall()

    return render_template(
        "dashboard.html",
        active="dashboard",
        today=today,
        today_rows=today_rows,
        total_machines=total_machines,
        count_done=count_done,
        count_overdue=count_overdue,
        count_progress=count_progress,
        count_pending=count_pending,
        attention=attention,
        recent=recent,
        week_stats=week_stats,
        labels=labels,
        done_counts=done_counts,
        overdue_history=overdue_history,
        now_hm=now_hm,
        shift_time=shift_time,
    )


@app.route("/jadwal")
def list_schedules():
    db = get_db()
    q_date = request.args.get("date", date.today().isoformat())
    q_machine = request.args.get("machine", "")
    q_status = request.args.get("status", "")
    q_done_all = request.args.get("done", "")  # '1' = tampil semua history done

    where = ["1=1"]
    params = []
    if q_date:
        where.append("s.cleaning_date = ?")
        params.append(q_date)
    if q_machine:
        where.append("s.machine_id = ?")
        params.append(q_machine)
    if q_status:
        where.append("s.status = ?")
        params.append(q_status)
    if not q_done_all:
        where.append("(s.status != 'done' OR s.cleaning_date >= ?)")
        params.append(q_date)

    rows = db.execute(
        f"""SELECT s.*, m.name AS machine_name, m.area, m.cleaning_type,
                   m.standard_time_minutes
            FROM schedules s JOIN machines m ON s.machine_id = m.id
            WHERE {' AND '.join(where)}
            ORDER BY s.cleaning_date DESC, s.time_start, m.name""",
        params,
    ).fetchall()
    schedules = [dictify(r) for r in rows]

    machines = load_machine_options()
    return render_template(
        "jadwal.html", active="jadwal", schedules=schedules, machines=machines,
        q_date=q_date, q_machine=q_machine, q_status=q_status, q_done_all=q_done_all,
        now_hm=datetime.now().strftime("%H:%M"),
    )


@app.route("/mesin")
def list_machines():
    db = get_db()
    q = request.args.get("q", "").strip()
    q_area = request.args.get("area", "").strip()
    q_status = request.args.get("status", "").strip()

    where = ["1=1"]
    params = []
    if q:
        where.append("name LIKE ?")
        params.append(f"%{q}%")
    if q_area:
        where.append("area = ?")
        params.append(q_area)
    if q_status in ("1", "0"):
        where.append("is_active = ?")
        params.append(q_status)

    rows = db.execute(
        f"""SELECT m.*,
                (SELECT COUNT(*) FROM schedules s
                 WHERE s.machine_id = m.id AND s.status != 'done') AS pending_jobs
            FROM machines m
            WHERE {' AND '.join(where)}
            ORDER BY m.is_active DESC, m.name""",
        params,
    ).fetchall()

    areas = [r["area"] for r in db.execute(
        "SELECT DISTINCT area FROM machines WHERE area != '' ORDER BY area"
    ).fetchall()]
    return render_template("mesin.html", active="mesin", machines=rows,
                           areas=areas, q=q, q_area=q_area, q_status=q_status)


@app.route("/kalender")
def kalender():
    db = get_db()
    try:
        y = int(request.args.get("y", date.today().year))
        m = int(request.args.get("m", date.today().month))
    except ValueError:
        y, m = date.today().year, date.today().month

    first = date(y, m, 1)
    start = first - timedelta(days=first.weekday())
    last = first.replace(month=m + 1, day=1) - timedelta(days=1)
    end = last + timedelta(days=6 - last.weekday())

    rows = db.execute(
        """SELECT s.*, m.name AS machine_name, m.area
           FROM schedules s JOIN machines m ON s.machine_id = m.id
           WHERE s.cleaning_date BETWEEN ? AND ?
           ORDER BY s.cleaning_date, s.time_start""",
        [start.isoformat(), end.isoformat()],
    ).fetchall()

    by_date = {}
    for r in rows:
        by_date.setdefault(r["cleaning_date"], []).append(dictify(r))

    cells, d = [], start
    while d <= end:
        day = {
            "date": d.isoformat(),
            "num": d.day,
            "other": d.month != m,
            "today": d == date.today(),
            "jobs": by_date.get(d.isoformat(), []),
            "value": d.strftime("%d/%m"),
        }
        cells.append(day)
        d += timedelta(days=1)

    prev = first - timedelta(days=1)
    nxt = last + timedelta(days=1)
    return render_template(
        "kalender.html", active="kalender", cells=cells,
        month_name=first.strftime("%B %Y"), y=y, m=m,
        prev_y=prev.year, prev_m=prev.month, next_y=nxt.year, next_m=nxt.month,
    )


@app.route("/laporan")
def laporan():
    db = get_db()
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    q_status = request.args.get("status", "")

    start_d, end_d = validate_dates(start, end)
    where = ["1=1"]
    params = []
    if start_d:
        where.append("s.cleaning_date >= ?")
        params.append(start)
    if end_d:
        where.append("s.cleaning_date <= ?")
        params.append(end)
    if q_status:
        where.append("s.status = ?")
        params.append(q_status)

    rows = db.execute(
        f"""SELECT s.*, m.name AS machine_name, m.area, m.cleaning_type
            FROM schedules s JOIN machines m ON s.machine_id = m.id
            WHERE {' AND '.join(where)}
            ORDER BY s.cleaning_date, s.time_start""",
        params,
    ).fetchall()
    schedules = [dictify(r) for r in rows]

    # Ringkasan per mesin (reuse klausa WHERE yang sudah memakai alias s.)
    summary = db.execute(
        f"""SELECT m.id, m.name, m.area,
                   COUNT(s.id) AS total,
                   SUM(CASE WHEN s.status = 'done' THEN 1 ELSE 0 END) AS selesai
            FROM machines m LEFT JOIN schedules s ON s.machine_id = m.id
            WHERE {' AND '.join(where)}
            GROUP BY m.id, m.name, m.area
            ORDER BY total DESC, m.name""",
        params,
    ).fetchall()

    completed = sum(1 for r in schedules if r["status_effective"] == "done")
    total = len(schedules)
    pct = round(completed * 100 / total, 1) if total else 0

    return render_template(
        "laporan.html", active="laporan", schedules=schedules, summary=summary,
        start=start, end=end, q_status=q_status, total=total, completed=completed, pct=pct,
    )


# ---------------------------- Mutasi mesin ----------------------------

@app.route("/mesin/tambah", methods=["GET", "POST"])
def machine_add():
    if request.method == "POST":
        data = machine_form_data()
        if data is None:
            return redirect(url_for("machine_add"))
        db = get_db()
        db.execute(
            """INSERT INTO machines
               (name, area, cleaning_type, frequency_days, standard_time_minutes, is_active, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            data,
        )
        db.commit()
        flash(f"Mesin '{data[0]}' berhasil ditambahkan.", "success")
        return redirect(url_for("list_machines"))
    return render_template("machine_form.html", active="mesin", machine=None)


@app.route("/mesin/<int:machine_id>/edit", methods=["GET", "POST"])
def machine_edit(machine_id):
    db = get_db()
    machine = db.execute("SELECT * FROM machines WHERE id = ?", [machine_id]).fetchone()
    if machine is None:
        flash("Mesin tidak ditemukan.", "error")
        return redirect(url_for("list_machines"))
    if request.method == "POST":
        data = machine_form_data()
        if data is None:
            return redirect(url_for("machine_edit", machine_id=machine_id))
        db.execute(
            """UPDATE machines SET name=?, area=?, cleaning_type=?, frequency_days=?,
               standard_time_minutes=?, is_active=?, notes=? WHERE id=?""",
            list(data) + [machine_id],
        )
        db.commit()
        flash(f"Data mesin '{data[0]}' berhasil diperbarui.", "success")
        return redirect(url_for("list_machines"))
    return render_template("machine_form.html", active="mesin", machine=machine)


@app.route("/mesin/<int:machine_id>/delete", methods=["POST"])
def machine_delete(machine_id):
    db = get_db()
    machine = db.execute("SELECT name FROM machines WHERE id = ?", [machine_id]).fetchone()
    if machine:
        db.execute("DELETE FROM machines WHERE id = ?", [machine_id])
        db.commit()
        flash(f"Mesin '{machine['name']}' beserta jadwalnya telah dihapus.", "success")
    return redirect(url_for("list_machines"))


@app.route("/mesin/<int:machine_id>/toggle", methods=["POST"])
def machine_toggle(machine_id):
    db = get_db()
    db.execute(
        "UPDATE machines SET is_active = 1 - is_active WHERE id = ?", [machine_id]
    )
    db.commit()
    return redirect(url_for("list_machines"))


def machine_form_data():
    """Ambil & validasi data form mesin. Return None jika tidak valid."""
    name = request.form.get("name", "").strip()
    area = request.form.get("area", "").strip()
    cleaning_type = request.form.get("cleaning_type", "").strip()
    freq = request.form.get("frequency_days", "1")
    std_min = request.form.get("standard_time_minutes", "30")
    is_active = 1 if request.form.get("is_active") else 0
    notes = request.form.get("notes", "").strip()

    if not name:
        flash("Nama mesin/area wajib diisi.", "error")
        return None
    try:
        freq = int(freq)
        std_min = int(std_min)
        assert freq >= 0 and std_min > 0
    except (ValueError, AssertionError):
        flash("Frekuensi/standar waktu tidak valid.", "error")
        return None
    return name, area or name, cleaning_type or "Rutin", freq, std_min, is_active, notes


# ---------------------------- Mutasi jadwal ----------------------------

@app.route("/jadwal/tambah", methods=["GET", "POST"])
def schedule_add():
    machines = load_machine_options()
    if request.method == "POST":
        id_, errors = schedule_form_data()
        if errors:
            for e in errors:
                flash(e, "error")
            return redirect(url_for("schedule_add"))
        db = get_db()
        db.execute(
            """INSERT INTO schedules
               (machine_id, cleaning_date, shift, time_start, time_end, assigned_to, status, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            id_,
        )
        db.commit()
        flash("Jadwal cleaning berhasil dibuat.", "success")
        return redirect(url_for("list_schedules"))
    machine_id = request.args.get("machine_id", "")
    return render_template("schedule_form.html", active="jadwal", schedule=None,
                           machines=machines, machine_id=machine_id)


@app.route("/jadwal/<int:schedule_id>/edit", methods=["GET", "POST"])
def schedule_edit(schedule_id):
    db = get_db()
    schedule = db.execute("SELECT * FROM schedules WHERE id = ?", [schedule_id]).fetchone()
    if schedule is None:
        flash("Jadwal tidak ditemukan.", "error")
        return redirect(url_for("list_schedules"))
    machines = load_machine_options()
    if request.method == "POST":
        id_, errors = schedule_form_data()
        if errors:
            for e in errors:
                flash(e, "error")
            return redirect(url_for("schedule_edit", schedule_id=schedule_id))
        db.execute(
            """UPDATE schedules SET machine_id=?, cleaning_date=?, shift=?, time_start=?,
               time_end=?, assigned_to=?, status=?, notes=? WHERE id=?""",
            list(id_) + [schedule_id],
        )
        db.commit()
        flash("Jadwal berhasil diperbarui.", "success")
        return redirect(url_for("list_schedules"))
    return render_template("schedule_form.html", active="jadwal", schedule=schedule,
                           machines=machines, machine_id=schedule["machine_id"])


@app.route("/jadwal/<int:schedule_id>/delete", methods=["POST"])
def schedule_delete(schedule_id):
    db = get_db()
    db.execute("DELETE FROM schedules WHERE id = ?", [schedule_id])
    db.commit()
    flash("Jadwal dihapus.", "success")
    return redirect(url_for("list_schedules"))


@app.route("/jadwal/<int:schedule_id>/status", methods=["POST"])
def schedule_status(schedule_id):
    db = get_db()
    sched = db.execute("SELECT * FROM schedules WHERE id = ?", [schedule_id]).fetchone()
    if sched is None:
        flash("Jadwal tidak ditemukan.", "error")
        return redirect(url_for("list_schedules"))
    target = request.form.get("status")
    if target not in STATUS_LABELS:
        flash("Status tidak valid.", "error")
        return redirect(url_for("list_schedules"))

    last_done = ""
    if target == "done":
        last_done = datetime.now().strftime("%Y-%m-%d %H:%M")
    elif target == "in_progress" and sched["status"] == "scheduled" and not sched["last_done_at"]:
        pass

    db.execute(
        "UPDATE schedules SET status=?, last_done_at=? WHERE id=?",
        [target, last_done, schedule_id],
    )
    db.commit()
    flash(f"Status jadwal berubah menjadi '{STATUS_LABELS[target]}'.", "success")
    return redirect(url_for("list_schedules"))


def schedule_form_data():
    """Validasi form jadwal. Return (tuple_data, errors)."""
    errors = []
    machine_id = request.form.get("machine_id", "")
    cleaning_date = request.form.get("cleaning_date", "")
    shift = request.form.get("shift", "Shift 1")
    time_start = request.form.get("time_start", "")
    time_end = request.form.get("time_end", "")
    assigned_to = request.form.get("assigned_to", "").strip()
    status = request.form.get("status", "scheduled")
    notes = request.form.get("notes", "").strip()

    try:
        machine_id = int(machine_id)
    except (TypeError, ValueError):
        errors.append("Pilih mesin yang valid.")
    if not cleaning_date:
        errors.append("Tanggal cleaning wajib diisi.")
    else:
        try:
            datetime.strptime(cleaning_date, "%Y-%m-%d")
        except ValueError:
            errors.append("Format tanggal tidak valid.")
    if shift not in SHIFTS:
        errors.append("Shift tidak valid.")
    if status not in STATUS_LABELS:
        status = "scheduled"

    if errors:
        return None, errors
    return (machine_id, cleaning_date, shift, time_start, time_end,
            assigned_to, status, notes), errors


# ---------------------------- Generate otomatis ----------------------------

@app.route("/generate", methods=["GET", "POST"])
def generate():
    db = get_db()
    machines = load_machine_options()
    if request.method == "POST":
        machine_id = request.form.get("machine_id", "")
        start = request.form.get("start", "")
        end = request.form.get("end", "")
        shift_default = request.form.get("shift_default", "Shift 1")

        start_d, end_d = validate_dates(start, end)
        if not start_d:
            if not start:
                flash("Tanggal mulai wajib diisi.", "error")
            return render_template("generate.html", active="jadwal",
                                   machines=machines, machine_id=machine_id,
                                   start=start, end=end, shift_default=shift_default)

        end_d = end_d or start_d
        selected = db.execute(
            "SELECT * FROM machines WHERE is_active = 1 ORDER BY name"
        ).fetchall()
        if machine_id:
            selected = [m for m in selected if m["id"] == int(machine_id)]

        total_created = 0
        d = start_d
        while d <= end_d:
            for m in selected:
                freq = m["frequency_days"] or 1
                if freq > 0 and (d - start_d).days % freq == 0:
                    # Hindari duplikat (mesin+tanggal+shift)
                    exists = db.execute(
                        """SELECT id FROM schedules
                           WHERE machine_id=? AND cleaning_date=? AND shift=?""",
                        [m["id"], d.isoformat(), shift_default],
                    ).fetchone()
                    if not exists:
                        start_t = SHIFTS[shift_default]["start"]
                        end_t = SHIFTS[shift_default]["end"]
                        db.execute(
                            """INSERT INTO schedules
                               (machine_id, cleaning_date, shift, time_start, time_end,
                                assigned_to, status, notes)
                               VALUES (?, ?, ?, ?, ?, '', 'scheduled', ?)""",
                            [m["id"], d.isoformat(), shift_default, start_t, end_t, m["notes"]],
                        )
                        total_created += 1
            d += timedelta(days=1)
        db.commit()
        if total_created > 0:
            flash(f"Berhasil membuat {total_created} jadwal baru.", "success")
        else:
            flash("Tidak ada jadwal baru yang dibuat (duplikat).", "warning")
        return redirect(url_for("list_schedules"))

    return render_template("generate.html", active="jadwal", machines=machines,
                           machine_id="", start="", end="", shift_default="Shift 1")


# ---------------------------- Ekspor ----------------------------

@app.route("/laporan/export")
def export_csv():
    db = get_db()
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    q_status = request.args.get("status", "")

    start_d, end_d = validate_dates(start, end)
    where = ["1=1"]
    params = []
    if start_d:
        where.append("s.cleaning_date >= ?")
        params.append(start)
    if end_d:
        where.append("s.cleaning_date <= ?")
        params.append(end)
    if q_status:
        where.append("s.status = ?")
        params.append(q_status)

    rows = db.execute(
        f"""SELECT s.*, m.name AS machine_name, m.area, m.cleaning_type
            FROM schedules s JOIN machines m ON s.machine_id = m.id
            WHERE {' AND '.join(where)}
            ORDER BY s.cleaning_date, s.time_start""",
        params,
    ).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ID", "Tanggal", "Shift", "Mesin/Area", "Lokasi", "Tipe Cleaning",
                     "Mulai", "Selesai", "Petugas", "Status", "Selesai Pada", "Catatan"])
    for r in rows:
        writer.writerow([
            r["id"], r["cleaning_date"], r["shift"], r["machine_name"], r["area"],
            r["cleaning_type"], r["time_start"] or SHIFTS.get(r["shift"], {}).get("start", ""),
            r["time_end"] or SHIFTS.get(r["shift"], {}).get("end", ""),
            r["assigned_to"], STATUS_LABELS[status_of(r)], r["last_done_at"], r["notes"],
        ])
    buf.seek(0)
    filename = f"laporan_cleaning_{date.today().isoformat()}.csv"
    return send_file(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


init_db()

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)