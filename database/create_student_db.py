"""Create student_performance.db — synthetic demo data for the PDF mini-project.

Schema matches PDF slide 06 (Dataset):
  attendance (0-100 %), internal_marks (0-50), assignment_marks (0-20),
  prev_gpa (0-10), practical_marks (0-50), study_pattern (categorical),
  final_marks (0-100, TARGET VARIABLE).

First 4 rows are the exact illustrative examples from the PDF.
Remaining rows are clearly SYNTHETIC demo records (not real students),
generated with a deterministic seed so Internal/GPA correlate HIGH
and Attendance MODERATE with Final — matching slide 11 (Novelty).
"""
import os
import random
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "student_performance.db")

# Start fresh so re-runs are deterministic.
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""
CREATE TABLE students (
    student_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    attendance REAL NOT NULL,
    internal_marks REAL NOT NULL,
    assignment_marks REAL NOT NULL,
    prev_gpa REAL NOT NULL,
    practical_marks REAL NOT NULL,
    study_pattern TEXT NOT NULL,
    final_marks REAL NOT NULL
)
""")
cur.execute("CREATE INDEX idx_students_final ON students(final_marks)")
cur.execute("CREATE INDEX idx_students_attendance ON students(attendance)")

STUDY_PATTERNS = ["Regular", "Consistent", "Group-study", "Last-minute"]
STUDY_BONUS = {"Regular": 3.0, "Consistent": 2.0, "Group-study": 1.0, "Last-minute": -1.5}

FIRST_NAMES = ["Aarav", "Priya", "Rahul", "Anitha", "Karthik", "Divya", "Vijay", "Sneha",
               "Arun", "Meera", "Kavin", "Lakshmi", "Surya", "Nisha", "Deepak", "Kavya"]
LAST_NAMES = ["Kumar", "Sharma", "Menon", "Raj", "S", "Krishnan", "R", "Nair", "Iyer", "Das"]

# Exact illustrative rows from PDF slide 06 (+ study_pattern from slide 05 example).
pdf_rows = [
    (1, "Aarav Kumar", 88, 43, 18, 8.1, 45, "Last-minute", 82),
    (2, "Priya Sharma", 72, 36, 15, 7.2, 39, "Last-minute", 69),
    (3, "Rahul Menon", 94, 47, 19, 8.8, 48, "Regular", 91),
    (4, "Anitha Raj", 65, 31, 14, 6.8, 35, "Last-minute", 61),
]
cur.executemany("""
INSERT INTO students
(student_id, name, attendance, internal_marks, assignment_marks, prev_gpa, practical_marks, study_pattern, final_marks)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", pdf_rows)


def clip(v, lo, hi):
    return max(lo, min(hi, v))


random.seed(42)
N_SYNTHETIC = 160
rows = []
for i in range(5, 5 + N_SYNTHETIC):
    base = random.uniform(55, 95)  # latent ability -> creates realistic correlations
    attendance = clip(base + random.gauss(0, 7), 50, 100)
    internal = clip(base / 2 + random.gauss(0, 2.5), 15, 50)
    practical = clip(base / 2 + random.gauss(0, 3.0), 15, 50)
    assignment = clip(base / 5 + random.gauss(0, 1.2), 8, 20)
    gpa = clip(base / 10 + random.gauss(0, 0.4), 5.0, 10.0)
    pattern = random.choice(STUDY_PATTERNS)

    internal_scaled = internal / 50 * 100
    practical_scaled = practical / 50 * 100
    assignment_scaled = assignment / 20 * 100
    gpa_scaled = gpa * 10
    final = (
        0.38 * internal_scaled
        + 0.22 * practical_scaled
        + 0.10 * assignment_scaled
        + 0.12 * attendance
        + 0.18 * gpa_scaled
        + STUDY_BONUS[pattern]
        - 5.0
        + random.gauss(0, 2.8)
    )
    final = round(clip(final, 35, 98), 1)
    name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
    rows.append((
        i, name, round(attendance, 1), round(internal, 1), round(assignment, 1),
        round(gpa, 2), round(practical, 1), pattern, final,
    ))

cur.executemany("""
INSERT INTO students
(student_id, name, attendance, internal_marks, assignment_marks, prev_gpa, practical_marks, study_pattern, final_marks)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", rows)

conn.commit()

# Quick sanity stats for the console (mirrors EDA slide 08 questions).
cur.execute("SELECT COUNT(*), ROUND(AVG(final_marks),1), ROUND(MIN(final_marks),1), ROUND(MAX(final_marks),1) FROM students")
n, avg, mn, mx = cur.fetchone()
cur.execute("SELECT ROUND(AVG(attendance),1), ROUND(AVG(internal_marks),1), ROUND(AVG(prev_gpa),2) FROM students")
avg_att, avg_int, avg_gpa = cur.fetchone()
conn.close()

print("======================================")
print("STUDENT PERFORMANCE DATABASE CREATED!")
print("======================================")
print(f"Path                : {DB_PATH}")
print(f"Students            : {n} (4 PDF examples + {N_SYNTHETIC} synthetic demo)")
print(f"Final marks         : avg {avg}, min {mn}, max {mx}")
print(f"Avg attendance      : {avg_att}")
print(f"Avg internal (/50)   : {avg_int}")
print(f"Avg prev GPA         : {avg_gpa}")
print("NOTE: synthetic rows are non-real demo records.")
print("======================================")
