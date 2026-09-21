
import psycopg2
import openpyxl
from datetime import date, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, send_file
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import csv
import io
from flask import Response



app = Flask(__name__)
app.secret_key = "any-random-string-here"


# PostgreSQL Database Connection
def get_db_connection():
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        database="Attendance",
        user="postgres",
        password="post"
    )
    return conn


# Home Page

@app.route("/")
def index():
    return render_template("index.html")


# teacher registration
@app.route("/register_teacher", methods=["GET", "POST"])
def register_teacher():
 
    if request.method == "POST":
        name = request.form["t_name"]
        email = request.form["email"]
        department = request.form["department"]

        conn = get_db_connection()
        cur = conn.cursor()

        # Server-side duplicate check (source of truth)
        cur.execute(
            "SELECT id FROM teachers WHERE email = %s",
            (email,)
        )

        existing = cur.fetchone()

        if existing:
            cur.close()
            conn.close()
            return render_template(
                "register_teacher.html",
                error="email already exists",
                name=name,
                email=email,
                department=department
            )

        cur.execute("""
            INSERT INTO teachers (name, email, department)
            VALUES (%s, %s, %s)
        """, (name, email, department))

        conn.commit()

        cur.close()
        conn.close()

        return render_template("register_success.html", name=name)

    return render_template("register_teacher.html")
  
# Teacher Login with session 
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            "SELECT id, name, email, department FROM teachers WHERE email = %s",
            (email,)
        )
        teacher = cur.fetchone()

        cur.close()
        conn.close()

        if teacher:
            session["teacher_id"] = teacher[0]
            session["teacher_name"] = teacher[1]
            session["department"] = teacher[3]

            return redirect("/dashboard")
        else:
            return "  this email has not registered" " " + email 

    return render_template("login.html")


# Dashboard Teacher
@app.route("/dashboard")
def dashboard():
    if "teacher_id" not in session:
        return redirect("/login")

    department = session["department"]
    today = date.today()
    month_start = (today - timedelta(days=30)).isoformat()

    conn = get_db_connection()
    cur = conn.cursor()

    # Fetch the LAST present date and LAST absent date for each student
    cur.execute("""
        SELECT s.id, s.name, s.roll, s.semester, s.department,
               MAX(CASE WHEN a.status = 'Present' THEN a.date END) AS last_present,
               MAX(CASE WHEN a.status = 'Absent' THEN a.date END) AS last_absent
        FROM students s
        LEFT JOIN attendance a ON a.student_id = s.id
        WHERE s.department = %(department)s
        GROUP BY s.id, s.name, s.roll, s.semester, s.department
        ORDER BY s.semester, s.name
    """, {"department": department})

    students = []
    for row in cur.fetchall():
        student_id, name, roll, semester, dept, last_present, last_absent = row
        students.append({
            "id": student_id, 
            "name": name, 
            "roll": roll,
            "semester": semester, 
            "department": dept,
            "last_present": last_present,
            "last_absent": last_absent
        })

    # Chart: Daily Present vs Absent over the last 30 days
    cur.execute("""
        SELECT a.date,
               COUNT(a.id) FILTER (WHERE a.status = 'Present') AS present_count,
               COUNT(a.id) FILTER (WHERE a.status = 'Absent') AS absent_count
        FROM attendance a
        JOIN students s ON a.student_id = s.id
        WHERE s.department = %(department)s AND a.date >= %(month_start)s
        GROUP BY a.date
        ORDER BY a.date
    """, {"month_start": month_start, "department": department})

    chart_rows = cur.fetchall()
    # Format date to string (YYYY-MM-DD) for the chart labels
    chart_labels = [str(r[0]) for r in chart_rows]
    chart_present = [r[1] for r in chart_rows]
    chart_absent = [r[2] for r in chart_rows]

    cur.close()
    conn.close()

    return render_template(
        "dashboard.html",
        students=students,
        chart_labels=chart_labels,
        chart_present=chart_present,
        chart_absent=chart_absent,
    )
# download student attendance 
@app.route("/download_student_record2")
def download_student_record2():
    if "teacher_id" not in session:
        return redirect("/login")
    
    department = session["department"]
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Fetch the exact data shown on the dashboard table
    cur.execute("""
        SELECT s.id, s.name, s.roll, s.semester, s.department,
               MAX(CASE WHEN a.status = 'Present' THEN a.date END) AS last_present,
               MAX(CASE WHEN a.status = 'Absent' THEN a.date END) AS last_absent
        FROM students s
        LEFT JOIN attendance a ON a.student_id = s.id
        WHERE s.department = %s
        GROUP BY s.id, s.name, s.roll, s.semester, s.department
        ORDER BY s.semester, s.name
    """, (department,))
    students = cur.fetchall()
    cur.close()
    conn.close()

    # Create a new Excel workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Student Attendance"

    # Define styles
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'), 
        top=Side(style='thin'), bottom=Side(style='thin')
    )
    center_alignment = Alignment(horizontal='center', vertical='center')
    header_font = Font(bold=True, size=12)

    # 1. Add and format Title
    ws.merge_cells('A1:G1') # Merges 7 columns
    title_cell = ws['A1']
    title_cell.value = "Student Attendance"
    title_cell.font = Font(bold=True, size=16)
    title_cell.alignment = center_alignment
    ws.row_dimensions[1].height = 30

    # 2. Add Headers
    headers = ["Sl No.", "Student Name", "Student Roll Number", "Semester", "Department", "Last Present Date", "Last Absent Date"]
    ws.append(headers)
    
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=2, column=col_num)
        cell.font = header_font
        cell.alignment = center_alignment
        cell.border = thin_border
    ws.row_dimensions[2].height = 25

    # 3. Add Data
    semester_map = {
        1: 'Semester-I', 2: 'Semester-II', 3: 'Semester-III', 
        4: 'Semester-IV', 5: 'Semester-V', 6: 'Semester-VI'
    }
    
    for index, student in enumerate(students, start=1):
        s_id, name, roll, semester, dept, last_present, last_absent = student
        
        sem_text = semester_map.get(semester, f"Semester-{semester}")
        present_str = str(last_present) if last_present else "No record"
        absent_str = str(last_absent) if last_absent else "No record"
        
        row_data = [index, name, roll, sem_text, dept, present_str, absent_str]
        ws.append(row_data)

    # 4. Apply borders, alignment, and auto-height to data rows
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=7):
        for cell in row:
            cell.border = thin_border
            if cell.row > 2:
                cell.alignment = center_alignment
                ws.row_dimensions[cell.row].height = 20

    # 5. Auto-width for all columns
    for col in ws.columns:
        max_length = 0
        column_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except:
                pass
        ws.column_dimensions[column_letter].width = max_length + 3

    # 6. Save to memory and send
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output, 
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, 
        download_name=f"Student_Attendance_{department}.xlsx"
    )
# Register Student
@app.route("/register", methods=["GET", "POST"])
def register():
    if "teacher_id" not in session:
        return redirect("/login")

    department = session["department"]

    if request.method == "POST":

        name = request.form["name"]
        roll = request.form["roll"]
        semester = request.form["semester"]

        conn = get_db_connection()
        cur = conn.cursor()

        # Server-side duplicate check (source of truth)
        cur.execute(
            "SELECT id FROM students WHERE roll = %s",
            (roll,)
        )

        existing = cur.fetchone()

        if existing:
            cur.close()
            conn.close()
            return render_template(
                "register.html",
                error="Roll number already exists, enter a new student",
                name=name,
                roll=roll,
                semester=semester,
                department=department
            )

        cur.execute("""
            INSERT INTO students (name, roll, semester, department)
            VALUES (%s, %s, %s, %s)
        """, (name, roll, semester, department))

        conn.commit()

        cur.close()
        conn.close()

        return render_template("register_succStu.html", name=name)

    return render_template("register.html", department=department)

#display the student record


#display the student record
@app.route("/student_record")
def student_record():
    if "teacher_id" not in session:
        return redirect("/login")

    department = session["department"]

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, roll, semester, department
        FROM students
        WHERE department = %s
        ORDER BY semester, name
    """, (department,))

    students = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("student_record.html", students=students)

# student record download 
@app.route("/download_student_record")
def download_student_record():
    if "teacher_id" not in session:
        return redirect("/login")
    
    department = session["department"]
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, roll, semester, department 
        FROM students 
        WHERE department = %s 
        ORDER BY semester, name
    """, (department,))
    students = cur.fetchall()
    cur.close()
    conn.close()

    # Create Excel Workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Student Record"

    # Styles
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'), 
        top=Side(style='thin'), bottom=Side(style='thin')
    )
    center_alignment = Alignment(horizontal='center', vertical='center')
    header_font = Font(bold=True, size=12)

    # Title
    ws.merge_cells('A1:E1')
    title_cell = ws['A1']
    title_cell.value = "Student Record"
    title_cell.font = Font(bold=True, size=16)
    title_cell.alignment = center_alignment
    ws.row_dimensions[1].height = 30

    # Headers
    headers = ["Sl No.", "Student Name", "Student Roll Number", "Semester", "Department"]
    ws.append(headers)
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=2, column=col_num)
        cell.font = header_font
        cell.alignment = center_alignment
        cell.border = thin_border
    ws.row_dimensions[2].height = 25

    # Data
    semester_map = {1: 'Semester-I', 2: 'Semester-II', 3: 'Semester-III', 4: 'Semester-IV', 5: 'Semester-V', 6: 'Semester-VI'}
    for index, student in enumerate(students, start=1):
        sem_text = semester_map.get(student[3], f"Semester-{student[3]}")
        row_data = [index, student[1], student[2], sem_text, student[4]]
        ws.append(row_data)

    # Apply borders and auto-height
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=5):
        for cell in row:
            cell.border = thin_border
            if cell.row > 2:
                cell.alignment = center_alignment
                ws.row_dimensions[cell.row].height = 20

    # Auto-width
    for col in ws.columns:
        max_length = 0
        column_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except:
                pass
        ws.column_dimensions[column_letter].width = max_length + 3

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output, 
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, 
        download_name=f"Student_Record_{department}.xlsx"
    )

#teacher logout
@app.route("/logout")
def logout():
    session.clear()
    return render_template("logout.html")

# the attendance
@app.route("/attendance", methods=["GET", "POST"])
def attendance():
    if "teacher_id" not in session:
        return redirect("/login")

    department = session["department"]
    today = date.today().isoformat()

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        semester = request.form.get("semester")
        # Falls back to today only if the field is somehow empty — the
        # hidden field always carries whatever date was selected on the page.
        selected_date = request.form.get("date") or today

        cur.execute("""
            SELECT id, roll FROM students
            WHERE department = %s AND semester = %s
        """, (department, semester))
        student_rows = cur.fetchall()

        any_checked = any(
            request.form.get(f"present_{student_id}") or request.form.get(f"absent_{student_id}")
            for student_id, roll in student_rows
        )

        if not any_checked:
            cur.close()
            conn.close()
            return redirect(f"/attendance?semester={semester}&date={selected_date}&error=1")

        for student_id, roll in student_rows:
            present_checked = request.form.get(f"present_{student_id}")
            absent_checked = request.form.get(f"absent_{student_id}")

            if present_checked:
                status = "Present"
            elif absent_checked:
                status = "Absent"
            else:
                continue  # left unmarked — skip, don't record anything for this date

            cur.execute("""
                SELECT id FROM attendance
                WHERE student_id = %s AND date = %s
            """, (student_id, selected_date))
            existing = cur.fetchone()

            if existing:
                cur.execute("""
                    UPDATE attendance SET status = %s
                    WHERE student_id = %s AND date = %s
                """, (status, student_id, selected_date))
            else:
                cur.execute("""
                    INSERT INTO attendance (student_id, roll, date, status)
                    VALUES (%s, %s, %s, %s)
                """, (student_id, roll, selected_date, status))

        conn.commit()
        cur.close()
        conn.close()
        return render_template("attendance_success.html", marked_date=selected_date)

    # GET: which semesters exist in this teacher's department, for the dropdown
    cur.execute("""
        SELECT DISTINCT semester FROM students
        WHERE department = %s
        ORDER BY semester
    """, (department,))
    semesters = [row[0] for row in cur.fetchall()]

    selected_semester = request.args.get("semester")
    # Default to today if no date was picked yet — this is the "default to
    # current date, but changeable" behavior.
    selected_date = request.args.get("date") or today
    show_error = request.args.get("error") == "1"
    students = []

    if selected_semester:
        cur.execute("""
            SELECT s.id, s.name, s.roll, s.semester, s.department, a.status
            FROM students s
            LEFT JOIN attendance a ON a.student_id = s.id AND a.date = %s
            WHERE s.department = %s AND s.semester = %s
            ORDER BY s.name
        """, (selected_date, department, selected_semester))

        for student_id, name, roll, semester, dept, status in cur.fetchall():
            students.append({
                "id": student_id, "name": name, "roll": roll,
                "semester": semester, "department": dept,
                "present": status == "Present",
                "absent": status == "Absent"
            })

    cur.close()
    conn.close()

    return render_template(
        "attendance.html",
        semesters=semesters,
        selected_semester=selected_semester,
        selected_date=selected_date,
        today=today,
        show_error=show_error,
        students=students)


# Delete Student
@app.route("/delete_student/<int:student_id>", methods=["POST"])
def delete_student(student_id):

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Delete ONLY the selected student
        cur.execute("""
            DELETE FROM students
            WHERE id = %s
        """, (student_id,))

        conn.commit()

    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()

        return f"Error deleting student: {e}", 500

    cur.close()
    conn.close()

    return redirect(url_for("student_record"))

# Edit Student
@app.route("/edit_student/<int:student_id>", methods=["GET", "POST"])
def edit_student(student_id):

    conn = get_db_connection()
    cur = conn.cursor()

    # When the Update button is pressed
    if request.method == "POST":

        name = request.form["name"]
        roll = request.form["roll"]
        semester = request.form["semester"]
        department = request.form["department"]

        cur.execute("""
            UPDATE Students
            SET name = %s,
                roll = %s,
                semester = %s,
                department = %s
            WHERE id = %s
        """, (
            name,
            roll,
            semester,
            department,
            student_id
        ))

        conn.commit()

        cur.close()
        conn.close()

        return redirect(url_for("dashboard"))

    # Get the existing student from the database
    cur.execute("""
        SELECT id, name, roll, semester, department
        FROM Students
        WHERE id = %s
    """, (student_id,))

    student = cur.fetchone()

    cur.close()
    conn.close()

    # Check whether student exists
    if student is None:
        return "Student not found", 404

    # Send student data to edit_student.html
    return render_template(
        "student_record.html",
        student=student
    )

# Run Application
if __name__ == "__main__":
    app.run(debug=True)