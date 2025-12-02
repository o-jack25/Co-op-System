# app.py
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, IntegerField, BooleanField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Email, NumberRange, Optional
from config import Config
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
login = LoginManager(app)
login.login_view = "login"

# ------------- MODELS -------------
class User(UserMixin, db.Model):
    # A unified user model with role to keep example compact: 'student', 'employer', 'faculty'
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    phone = db.Column(db.String(30), nullable=True)

    # student-specific fields
    department = db.Column(db.String(80), nullable=True)
    major = db.Column(db.String(80), nullable=True)
    credit_hours_completed = db.Column(db.Integer, nullable=True)
    gpa = db.Column(db.Float, nullable=True)
    start_semester = db.Column(db.String(20), nullable=True)
    is_transfer = db.Column(db.Boolean, default=False)
    semesters_completed = db.Column(db.Integer, nullable=True)  # useful for eligibility
    resume_text = db.Column(db.Text, nullable=True)

    # employer-specific fields
    company_name = db.Column(db.String(120), nullable=True)
    company_location = db.Column(db.String(120), nullable=True)
    company_website = db.Column(db.String(200), nullable=True)
    contact_name = db.Column(db.String(120), nullable=True)
    contact_phone = db.Column(db.String(50), nullable=True)

    # faculty-specific fields
    home_department = db.Column(db.String(80), nullable=True)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    def get_id(self):
        return str(self.id)

@login.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class Position(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    weeks = db.Column(db.Integer, nullable=False)
    hours_per_week = db.Column(db.Integer, nullable=False)
    location = db.Column(db.String(120))
    majors_of_interest = db.Column(db.String(200))
    required_skills = db.Column(db.String(300))
    preferred_skills = db.Column(db.String(300))
    salary = db.Column(db.String(100))
    status = db.Column(db.String(20), default='open')  # open, pending, closed

    employer = db.relationship('User', backref='positions', foreign_keys=[employer_id])

class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    position_id = db.Column(db.Integer, db.ForeignKey('position.id'), nullable=False)
    status = db.Column(db.String(20), default='applied')  # applied, interviewed, selected, rejected, pending
    offer_letter = db.Column(db.Text, nullable=True)

    student = db.relationship('User', foreign_keys=[student_id])
    position = db.relationship('Position', foreign_keys=[position_id])

class CoOpSummary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    position_id = db.Column(db.Integer, db.ForeignKey('position.id'), nullable=False)
    summary_text = db.Column(db.Text, nullable=False)
    grade = db.Column(db.String(5), nullable=True)  # entered by faculty

    student = db.relationship('User', foreign_keys=[student_id])
    position = db.relationship('Position', foreign_keys=[position_id])

# ------------- FORMS -------------
class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class RegisterForm(FlaskForm):
    role = SelectField('Role', choices=[('student','Student'),('employer','Employer'),('faculty','Faculty')], validators=[DataRequired()])
    full_name = StringField('Full name', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Register')

class PositionForm(FlaskForm):
    title = StringField('Job Title', validators=[DataRequired()])
    description = TextAreaField('Description', validators=[DataRequired()])
    weeks = IntegerField('Number of weeks', validators=[DataRequired(), NumberRange(min=1)])
    hours_per_week = IntegerField('Hours per week', validators=[DataRequired(), NumberRange(min=1)])
    location = StringField('Location', validators=[Optional()])
    majors_of_interest = StringField('Majors of interest', validators=[Optional()])
    required_skills = StringField('Required skills', validators=[Optional()])
    preferred_skills = StringField('Preferred skills', validators=[Optional()])
    salary = StringField('Salary info', validators=[Optional()])
    submit = SubmitField('Create Position')

class ApplyForm(FlaskForm):
    submit = SubmitField('Apply')

class SelectForm(FlaskForm):
    selected_student_id = IntegerField('Selected student ID', validators=[DataRequired()])
    offer_letter = TextAreaField('Offer letter', validators=[Optional()])
    submit = SubmitField('Mark Selected')

class CoOpInterestForm(FlaskForm):
    interested = BooleanField('I want course credit (co-op)?')
    submit = SubmitField('Submit Interest')

class SummaryForm(FlaskForm):
    summary_text = TextAreaField('Co-op summary', validators=[DataRequired()])
    submit = SubmitField('Submit Summary')

class GradeForm(FlaskForm):
    grade = StringField('Grade (e.g., A, B+)', validators=[DataRequired()])
    submit = SubmitField('Enter Grade')

# ------------- BUSINESS LOGIC -------------
def check_coop_eligibility(student: User, position: Position):
    """
    Per spec:
    - student must have minimum 2.0 GPA
    - internship must be at least 7 weeks and a total of at least 140 hours (weeks * hours_per_week >= 140)
    - if transfer: completed at least 1 semester; otherwise completed at least 2 semesters
    Returns: (is_eligible: bool, reasons: list)
    """
    reasons = []
    eligible = True

    # GPA check
    if student.gpa is None or student.gpa < 2.0:
        eligible = False
        reasons.append("GPA below 2.0")

    # weeks & hours
    if position.weeks < 7:
        eligible = False
        reasons.append(f"Position weeks {position.weeks} < 7")
    total_hours = position.weeks * position.hours_per_week
    if total_hours < 140:
        eligible = False
        reasons.append(f"Total hours {total_hours} < 140")

    # semesters check
    sc = student.semesters_completed or 0
    if student.is_transfer:
        if sc < 1:
            eligible = False
            reasons.append("Transfer student must have completed at least 1 semester")
    else:
        if sc < 2:
            eligible = False
            reasons.append("Non-transfer student must have completed at least 2 semesters")

    return eligible, reasons

# ------------- ROUTES -------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register", methods=['GET','POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data).first():
            flash("Email already registered.", "danger")
            return redirect(url_for('register'))
        u = User(role=form.role.data, full_name=form.full_name.data, email=form.email.data)
        u.set_password(form.password.data)
        # default blank values for others
        db.session.add(u)
        db.session.commit()
        flash("Registered! Please login.", "success")
        return redirect(url_for('login'))
    return render_template("register.html", form=form)

@app.route("/login", methods=['GET','POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        u = User.query.filter_by(email=form.email.data).first()
        if u and u.check_password(form.password.data):
            login_user(u)
            flash("Logged in", "success")
            if u.role == 'employer':
                return redirect(url_for('employer_dashboard'))
            elif u.role == 'student':
                return redirect(url_for('student_dashboard'))
            else:
                return redirect(url_for('faculty_dashboard'))
        else:
            flash("Invalid credentials", "danger")
    return render_template("login.html", form=form)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out", "info")
    return redirect(url_for('index'))

# Employer: create positions and view applicants
@app.route("/employer")
@login_required
def employer_dashboard():
    if current_user.role != 'employer':
        flash("Not authorized", "danger")
        return redirect(url_for('index'))
    positions = Position.query.filter_by(employer_id=current_user.id).all()
    return render_template("employer_dashboard.html", positions=positions)

@app.route("/employer/create", methods=['GET','POST'])
@login_required
def create_position():
    if current_user.role != 'employer':
        flash("Not authorized", "danger")
        return redirect(url_for('index'))
    form = PositionForm()
    if form.validate_on_submit():
        p = Position(
            employer_id=current_user.id,
            title=form.title.data,
            description=form.description.data,
            weeks=form.weeks.data,
            hours_per_week=form.hours_per_week.data,
            location=form.location.data,
            majors_of_interest=form.majors_of_interest.data,
            required_skills=form.required_skills.data,
            preferred_skills=form.preferred_skills.data,
            salary=form.salary.data
        )
        db.session.add(p)
        db.session.commit()
        flash("Position created", "success")
        return redirect(url_for('employer_dashboard'))
    return render_template("create_position.html", form=form)

@app.route("/positions")
def position_list():
    positions = Position.query.filter_by(status='open').all()
    return render_template("position_list.html", positions=positions)

@app.route("/position/<int:pid>", methods=['GET','POST'])
def position_detail(pid):
    position = Position.query.get_or_404(pid)
    form = ApplyForm()
    if form.validate_on_submit():
        if not current_user.is_authenticated or current_user.role != 'student':
            flash("You must be logged in as a student to apply", "danger")
            return redirect(url_for('login'))
        # create application
        existing = Application.query.filter_by(student_id=current_user.id, position_id=position.id).first()
        if existing:
            flash("Already applied", "info")
        else:
            a = Application(student_id=current_user.id, position_id=position.id)
            db.session.add(a)
            db.session.commit()
            flash("Application submitted", "success")
            return render_template("apply_confirm.html", position=position)
    return render_template("position_detail.html", position=position, form=form)

# View applicants (employer)
@app.route("/position/<int:pid>/applicants", methods=['GET','POST'])
@login_required
def view_applicants(pid):
    position = Position.query.get_or_404(pid)
    if current_user.role != 'employer' or position.employer_id != current_user.id:
        flash("Not authorized", "danger")
        return redirect(url_for('index'))
    apps = Application.query.filter_by(position_id=pid).all()
    select_form = SelectForm()
    if select_form.validate_on_submit():
        sid = select_form.selected_student_id.data
        offer = select_form.offer_letter.data or ""
        # mark selected
        app_selected = Application.query.filter_by(student_id=sid, position_id=pid).first()
        if not app_selected:
            flash("Application not found for that student", "danger")
        else:
            app_selected.status = 'selected'
            app_selected.offer_letter = offer
            position.status = 'pending'
            db.session.commit()

            # check eligibility
            student = User.query.get(sid)
            eligible, reasons = check_coop_eligibility(student, position)

            # Simulate sending email (print to console); in production, send real email.
            if eligible:
                # create a message that would be emailed
                msg = f"To: {student.email}\nSubject: Co-op eligibility\n\nYou have been selected for {position.title}. You are eligible for co-op. Please indicate interest in portal."
                print("--- EMAIL (simulated) ---")
                print(msg)
                print("-------------------------")
                flash("Student marked as selected. Eligibility: Eligible. Email sent (simulated).", "success")
            else:
                msg = f"To: {student.email}\nSubject: Co-op eligibility\n\nYou have been selected for {position.title}. However, you are NOT eligible for co-op for these reasons: " + "; ".join(reasons)
                print("--- EMAIL (simulated) ---")
                print(msg)
                print("-------------------------")
                flash(f"Student marked as selected. Not eligible: {', '.join(reasons)}. Email sent (simulated).", "warning")
            db.session.commit()
            return redirect(url_for('view_applicants', pid=pid))
    return render_template("view_applicants.html", position=position, apps=apps, form=select_form)

# Student dashboard
@app.route("/student")
@login_required
def student_dashboard():
    if current_user.role != 'student':
        flash("Not authorized", "danger")
        return redirect(url_for('index'))
    my_apps = Application.query.filter_by(student_id=current_user.id).all()
    # positions that are pending for them
    pending = [a for a in my_apps if a.status == 'selected']
    return render_template("student_dashboard.html", my_apps=my_apps, pending=pending)

# Student indicates interest in co-op
@app.route("/application/<int:aid>/interest", methods=['GET','POST'])
@login_required
def indicate_interest(aid):
    application = Application.query.get_or_404(aid)
    if current_user.role != 'student' or application.student_id != current_user.id:
        flash("Not authorized", "danger")
        return redirect(url_for('index'))
    form = CoOpInterestForm()
    if form.validate_on_submit():
        if form.interested.data:
            flash("Interest recorded. Please, after the internship, submit a short summary to receive a grade.", "success")
            # optional: create a placeholder CoOpSummary or mark flag; we'll rely on summary submission next
        else:
            flash("You chose not to get credit. Good luck with your internship!", "info")
        return redirect(url_for('student_dashboard'))
    return render_template("co_op_interest.html", form=form, application=application)

# Submit summary
@app.route("/coops/submit/<int:pid>", methods=['GET','POST'])
@login_required
def submit_summary(pid):
    if current_user.role != 'student':
        flash("Only students can submit co-op summaries", "danger")
        return redirect(url_for('index'))
    position = Position.query.get_or_404(pid)
    form = SummaryForm()
    if form.validate_on_submit():
        s = CoOpSummary(student_id=current_user.id, position_id=pid, summary_text=form.summary_text.data)
        db.session.add(s)
        db.session.commit()
        flash("Summary submitted. Your faculty will grade it.", "success")
        return redirect(url_for('student_dashboard'))
    return render_template("submit_summary.html", form=form, position=position)

# Faculty dashboard & grade entry
@app.route("/faculty")
@login_required
def faculty_dashboard():
    if current_user.role != 'faculty':
        flash("Not authorized", "danger")
        return redirect(url_for('index'))
    # show co-op summaries for students in their department (naive filter)
    summaries = CoOpSummary.query.all()
    return render_template("faculty_dashboard.html", summaries=summaries)

@app.route("/grade/<int:summary_id>", methods=['GET','POST'])
@login_required
def enter_grade(summary_id):
    if current_user.role != 'faculty':
        flash("Not authorized", "danger")
        return redirect(url_for('index'))
    summary = CoOpSummary.query.get_or_404(summary_id)
    form = GradeForm()
    if form.validate_on_submit():
        summary.grade = form.grade.data
        db.session.commit()
        flash("Grade entered", "success")
        return redirect(url_for('faculty_dashboard'))
    return render_template("grade_entry.html", form=form, summary=summary)

# Utility: simple search: by employer name, title, location
@app.route("/search")
def search():
    q = request.args.get('q','').strip()
    by = request.args.get('by','title')  # title, employer, location
    if not q:
        results = Position.query.filter_by(status='open').all()
    else:
        if by == 'title':
            results = Position.query.filter(Position.title.ilike(f"%{q}%"), Position.status=='open').all()
        elif by == 'employer':
            results = Position.query.join(User).filter(User.company_name.ilike(f"%{q}%"), Position.status=='open').all()
        else:
            results = Position.query.filter(Position.location.ilike(f"%{q}%"), Position.status=='open').all()
    return render_template("position_list.html", positions=results)

# ------------- DB INIT & SAMPLE DATA -------------
def init_db():
    db.drop_all()
    db.create_all()
    # create sample users
    # Employer
    emp = User(role='employer', full_name='Acme HR', email='employer@acme.com', company_name='Acme Inc', company_location='Ann Arbor, MI', contact_name='Alice HR', contact_phone='555-001')
    emp.set_password('password')
    # Student eligible
    stud1 = User(role='student', full_name='Jack Student', email='jack@student.com', gpa=3.1, semesters_completed=2, is_transfer=False)
    stud1.set_password('password')
    # Student not eligible
    stud2 = User(role='student', full_name='Sam LowGPA', email='sam@student.com', gpa=1.8, semesters_completed=3, is_transfer=False)
    stud2.set_password('password')
    # Faculty
    fac = User(role='faculty', full_name='Dr. Faculty', email='faculty@umich.edu', home_department='CECS')
    fac.set_password('password')
    db.session.add_all([emp, stud1, stud2, fac])
    db.session.commit()

    # create a position that qualifies for coop (8 weeks, 20 hrs -> 160)
    p1 = Position(employer_id=emp.id, title='Software Intern', description='Internship for backend dev', weeks=8, hours_per_week=20, location='Remote', majors_of_interest='CS', required_skills='Python', salary='$3000')
    # create a non-qualifying (6 weeks, 20 hrs -> 120)
    p2 = Position(employer_id=emp.id, title='Short Internship', description='Short term', weeks=6, hours_per_week=20, location='Ann Arbor', majors_of_interest='CS', required_skills='Java', salary='$1200')
    db.session.add_all([p1,p2])
    db.session.commit()
    print("Database initialized with sample data. logins: employer@acme.com / jack@student.com / sam@student.com / faculty@umich.edu (password: password)")

if __name__ == "__main__":
    import os
    with app.app_context():
        if not os.path.exists('coop.db'):
            init_db()
    app.run(debug=True)
