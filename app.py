import hmac
import os


from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, abort
)

from datetime import datetime

from functools import wraps

from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user,
    logout_user, login_required, current_user
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv


load_dotenv()

app = Flask(__name__, instance_relative_config=True)

# Environment configuration.
# Local development uses development settings.
# The hosting platform must explicitly set production.
APP_ENV = os.getenv("FLASK_ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"

if APP_ENV not in {"development", "production"}:
    raise RuntimeError(
        "FLASK_ENVIRONMENT must be either 'development' or 'production'."
    )

# Secret key configuration.
SECRET_KEY = os.getenv("SECRET_KEY")

if IS_PRODUCTION and not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY must be configured before running in production."
    )

if not IS_PRODUCTION and not SECRET_KEY:
    SECRET_KEY = "dev-key-change-before-deployment"

app.config["SECRET_KEY"] = SECRET_KEY
app.config["WTF_CSRF_SECRET_KEY"] = SECRET_KEY

# Database configuration.
database_url = os.environ.get("DATABASE_URL")

if database_url:
    # Normalize Render's PostgreSQL URL for SQLAlchemy.
    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://", "postgresql://", 1
        )
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace(
            "postgresql://", "postgresql+psycopg://", 1
        )

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    # Keep using the existing local SQLite database.
    os.makedirs(app.instance_path, exist_ok=True)

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        "sqlite:///" + os.path.join(app.instance_path, "memory_care.db")
    )

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Session-cookie security.
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION

# CSRF protection.
app.config["WTF_CSRF_ENABLED"] = True

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

csrf = CSRFProtect(app)

# -------------------------
# DATABASE MODEL
# -------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)

    full_name = db.Column(db.String(100), nullable=False)

    email = db.Column(
        db.String(120),
        unique=True,
        nullable=False,
        index=True
    )

    password_hash = db.Column(db.String(255), nullable=False)

    role = db.Column(
        db.String(20),
        nullable=False,
        default="learner"
    )

    email_verified = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"


class SetupState(db.Model):
    __tablename__ = "setup_state"

    id = db.Column(db.Integer, primary_key=True)

    admin_setup_completed = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)

    modules = db.relationship(
        "Module",
        backref="course",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="Module.position"
    )


class Module(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    position = db.Column(db.Integer, nullable=False, default=1)

    course_id = db.Column(
        db.Integer,
        db.ForeignKey("course.id"),
        nullable=False
    )


class StudyNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)

    position = db.Column(db.Integer, nullable=False, default=1)

    module_id = db.Column(
        db.Integer,
        db.ForeignKey("module.id"),
        nullable=False
    )



class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    text = db.Column(db.Text, nullable=False)

    option_a = db.Column(db.Text, nullable=False)
    option_b = db.Column(db.Text, nullable=False)
    option_c = db.Column(db.Text, nullable=False)
    option_d = db.Column(db.Text, nullable=False)

    correct_answer = db.Column(db.String(1), nullable=False)

    position = db.Column(db.Integer, nullable=False, default=1)

    course_id = db.Column(
        db.Integer,
        db.ForeignKey("course.id"),
        nullable=False
    )

    course = db.relationship("Course", backref="assessment_questions")

class AssessmentAttempt(db.Model):
    __tablename__ = "assessment_attempt"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    course_id = db.Column(
        db.Integer,
        db.ForeignKey("course.id"),
        nullable=False
    )

    score = db.Column(db.Integer, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    percentage = db.Column(db.Integer, nullable=False)
    passed = db.Column(db.Boolean, nullable=False)

    attempted_at = db.Column(
        db.DateTime,
        default=db.func.current_timestamp(),
        nullable=False
    )

    user = db.relationship("User")
    course = db.relationship("Course")


class SystemSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    key = db.Column(
        db.String(100),
        unique=True,
        nullable=False
    )

    value = db.Column(
        db.String(255),
        nullable=False
    )


class LearnerModuleProgress(db.Model):
    __tablename__ = "learner_module_progress"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    course_id = db.Column(
        db.Integer,
        db.ForeignKey("course.id"),
        nullable=False
    )

    module_id = db.Column(
        db.Integer,
        db.ForeignKey("module.id"),
        nullable=False
    )

    completed = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    last_accessed_at = db.Column(
        db.DateTime,
        nullable=False,
        default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp()
    )

    user = db.relationship("User")
    course = db.relationship("Course")
    module = db.relationship("Module")

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "module_id",
            name="uq_learner_module_progress"
        ),
    )


def admin_required(view_function):
    @wraps(view_function)
    @login_required
    def wrapped_view(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)

        return view_function(*args, **kwargs)

    return wrapped_view



@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (ValueError, TypeError):
        return None


# -------------------------
# HOME PAGE
# -------------------------

@app.route("/")
def index():
    return redirect(url_for("register"))

# -------------------------
# REGISTRATION
# -------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not full_name or not email or not password:
            flash("Please complete all required fields.", "error")
            return render_template("register.html")

        if len(full_name) > 100 or len(email) > 120:
            flash("Your name or email address is too long.", "error")
            return render_template("register.html")

        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            flash("Please enter a valid email address.", "error")
            return render_template("register.html")

        if len(password) < 8:
            flash("Your password must contain at least 8 characters.", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Your passwords do not match.", "error")
            return render_template("register.html")

        existing_user = db.session.execute(
            db.select(User).filter_by(email=email)
        ).scalar_one_or_none()

        if existing_user:
            flash("An account with this email already exists.", "error")
            return render_template("register.html")

        user = User(full_name=full_name, email=email)
        user.set_password(password)

        try:
            db.session.add(user)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Could not create learner account")
            flash("We couldn't create your account. Please try again.", "error")
            return render_template("register.html")

        login_user(user)
        flash("Welcome to Memory Care! Your account is ready.", "success")
        return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/setup-admin", methods=["GET", "POST"])
def setup_admin():
    # Setup must be explicitly enabled by the application owner.
    if os.environ.get("ADMIN_SETUP_ENABLED", "").lower() != "true":
        abort(404)

    # Get or initialize the persistent setup state.
    state = db.session.get(SetupState, 1)

    if state is None:
        state = SetupState(
            id=1,
            admin_setup_completed=False
        )
        db.session.add(state)
        db.session.commit()

    # Close setup permanently once it has been completed.
    if state.admin_setup_completed:
        abort(404)

    # Also protect against an existing administrator.
    admin_exists = db.session.execute(
        db.select(User.id)
        .filter_by(role="admin")
        .limit(1)
    ).first()

    if admin_exists:
        state.admin_setup_completed = True
        db.session.commit()
        abort(404)

    if request.method == "POST":
        setup_key = request.form.get("setup_key", "")
        expected_key = os.environ.get("ADMIN_SETUP_KEY", "")

        if not expected_key or not hmac.compare_digest(
            setup_key, expected_key
        ):
            flash("Invalid setup key.", "error")
            return render_template("setup_admin.html")

        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not full_name or not email or not password:
            flash("Please complete all required fields.", "error")
            return render_template("setup_admin.html")

        if len(full_name) > 100 or len(email) > 120:
            flash("Your name or email address is too long.", "error")
            return render_template("setup_admin.html")

        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            flash("Please enter a valid email address.", "error")
            return render_template("setup_admin.html")

        if len(password) < 12:
            flash("Your password must contain at least 12 characters.", "error")
            return render_template("setup_admin.html")

        if password != confirm_password:
            flash("Your passwords do not match.", "error")
            return render_template("setup_admin.html")

        existing_user = db.session.execute(
            db.select(User).filter_by(email=email)
        ).scalar_one_or_none()

        if existing_user:
            flash("An account with this email already exists.", "error")
            return render_template("setup_admin.html")

        # Recheck setup state immediately before creation.
        state = db.session.get(SetupState, 1)

        admin_exists = db.session.execute(
            db.select(User.id)
            .filter_by(role="admin")
            .limit(1)
        ).first()

        if state is None or state.admin_setup_completed or admin_exists:
            db.session.rollback()
            abort(404)

        user = User(
            full_name=full_name,
            email=email,
            role="admin",
            email_verified=False
        )
        user.set_password(password)

        try:
            db.session.add(user)
            state.admin_setup_completed = True
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception(
                "Could not create the initial administrator"
            )
            flash(
                "We couldn't create the administrator account. "
                "Please try again.",
                "error"
            )
            return render_template("setup_admin.html")

        # Close setup for this running process too.
        os.environ["ADMIN_SETUP_ENABLED"] = "false"

        login_user(user)
        flash("Administrator account created successfully!", "success")
        return redirect(url_for("admin_dashboard"))

    return render_template("setup_admin.html")

# -------------------------
# LOGIN
# -------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = db.session.execute(
            db.select(User).filter_by(email=email)
        ).scalar_one_or_none()

        if user and user.check_password(password):
            login_user(user)
            flash("Welcome back!", "success")

            # Allow safe internal next-page redirects.
            next_page = request.args.get("next")

            if next_page and (
                next_page.startswith("/")
                and not next_page.startswith("//")
                and "\\" not in next_page
            ):
                return redirect(next_page)

            # Administrators land on the admin dashboard.
            if user.is_admin:
                return redirect(url_for("admin_dashboard"))

            # Learners land on the learner dashboard.
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


# -------------------------
# LEARNER DASHBOARD
# -------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", user=current_user)


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()

        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        # Validate personal information
        if not full_name or not email:
            flash("Full name and email are required.", "error")
            return redirect(url_for("settings"))

        # Check whether another user already has this email
        existing_user = User.query.filter(
            User.email == email,
            User.id != current_user.id
        ).first()

        if existing_user:
            flash("That email address is already in use.", "error")
            return redirect(url_for("settings"))

        # Change password only when requested
        if current_password or new_password or confirm_password:
            if not current_password or not current_user.check_password(
                current_password
            ):
                flash("Your current password is incorrect.", "error")
                return redirect(url_for("settings"))

            if len(new_password) < 8:
                flash(
                    "Your new password must be at least 8 characters.",
                    "error"
                )
                return redirect(url_for("settings"))

            if new_password != confirm_password:
                flash("The new passwords do not match.", "error")
                return redirect(url_for("settings"))

            current_user.set_password(new_password)

        # Save personal information
        current_user.full_name = full_name
        current_user.email = email

        db.session.commit()

        flash("Your settings have been updated successfully.", "success")
        return redirect(url_for("settings"))

    return render_template("settings.html", active_page="settings")



@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if not current_user.is_admin:
        flash("Access denied. Administrator access required.", "error")
        return redirect(url_for("dashboard"))

    # Get or create the assessment pass mark.
    setting = SystemSetting.query.filter_by(
        key="assessment_pass_mark"
    ).first()

    if setting is None:
        setting = SystemSetting(
            key="assessment_pass_mark",
            value="80"
        )
        db.session.add(setting)
        db.session.commit()

    if request.method == "POST":

        form_type = request.form.get("form_type", "")

        
        # CHANGE ADMINISTRATOR PASSWORD
        if form_type == "password":
            current_password = request.form.get(
                "current_password", ""
            )

            new_password = request.form.get(
                "new_password", ""
            )

            confirm_password = request.form.get(
                "confirm_password", ""
            )

            if not current_user.check_password(current_password):
                flash("Your current password is incorrect.", "error")

            elif len(new_password) < 8:
                flash(
                    "Your new password must contain at least 8 characters.",
                    "error"
                )

            elif new_password != confirm_password:
                flash("The new passwords do not match.", "error")

            elif current_password == new_password:
                flash(
                    "Your new password must be different from your current password.",
                    "error"
                )

            else:
                current_user.set_password(new_password)
                db.session.commit()

                flash(
                    "Your password has been changed successfully.",
                    "success"
                )

                return redirect(url_for("admin_settings"))


        # UPDATE ADMIN PROFILE
        if form_type == "profile":
            full_name = request.form.get(
                "full_name", ""
            ).strip()

            email = request.form.get(
                "email", ""
            ).strip().lower()

            if not full_name or not email:
                flash(
                    "Please enter both your full name and email.",
                    "error"
                )

            else:
                existing_user = User.query.filter(
                    User.email == email,
                    User.id != current_user.id
                ).first()

                if existing_user:
                    flash(
                        "That email address is already in use.",
                        "error"
                    )
                else:
                    current_user.full_name = full_name
                    current_user.email = email

                    db.session.commit()

                    flash(
                        "Your administrator information has been updated.",
                        "success"
                    )

                    return redirect(url_for("admin_settings"))

        # UPDATE ASSESSMENT PASS MARK
        elif form_type == "pass_mark":
            pass_mark_text = request.form.get(
                "assessment_pass_mark", ""
            ).strip()

            try:
                pass_mark = int(pass_mark_text)
            except (ValueError, TypeError):
                pass_mark = -1

            if not 1 <= pass_mark <= 100:
                flash(
                    "Enter a whole-number pass mark between 1 and 100.",
                    "error"
                )
            else:
                setting.value = str(pass_mark)
                db.session.commit()

                flash(
                    f"Assessment pass mark updated to {pass_mark}%.",
                    "success"
                )

                return redirect(url_for("admin_settings"))

    return render_template(
        "admin_settings.html",
        user=current_user,
        pass_mark=int(setting.value)
    )


# -------------------------
# LEARNER COURSES
# -------------------------
@app.route("/learner/courses")
@login_required
def learner_courses():
    courses = Course.query.order_by(Course.id.asc()).all()

    course_progress = {}

    for course in courses:
        modules = Module.query.filter_by(
            course_id=course.id
        ).order_by(Module.position.asc()).all()

        total_modules = len(modules)

        progress_records = LearnerModuleProgress.query.filter_by(
            user_id=current_user.id,
            course_id=course.id
        ).all()

        completed_module_ids = {
            record.module_id
            for record in progress_records
            if record.completed
        }

        completed_modules = len(completed_module_ids)

        progress_percentage = (
            round((completed_modules / total_modules) * 100)
            if total_modules else 0
        )

        last_progress = max(
            progress_records,
            key=lambda record: record.last_accessed_at,
            default=None
        )

        last_module = (
            Module.query.get(last_progress.module_id)
            if last_progress else None
        )

        passed_attempt = AssessmentAttempt.query.filter_by(
            user_id=current_user.id,
            course_id=course.id,
            passed=True
        ).first()

        if passed_attempt:
            status = "Completed"
        elif last_progress:
            status = "In Progress"
        else:
            status = "Not Started"

        course_progress[course.id] = {
            "total_modules": total_modules,
            "completed_modules": completed_modules,
            "percentage": progress_percentage,
            "status": status,
            "last_module": last_module,
            "passed": passed_attempt is not None
        }

    return render_template(
        "learner_courses.html",
        user=current_user,
        courses=courses,
        course_progress=course_progress
    )


# -------------------------
# LEARNER COURSE MODULES
# -------------------------

@app.route("/learner/course/<int:course_id>/modules")
@login_required
def learner_course_modules(course_id):
    course = Course.query.get_or_404(course_id)

    modules = Module.query.filter_by(
        course_id=course.id
    ).order_by(Module.position.asc()).all()

    return render_template(
        "learner_modules.html",
        user=current_user,
        course=course,
        modules=modules
    )


# -------------------------
# LEARNER STUDY MATERIALS
# -------------------------

@app.route("/learner/study-materials")
@login_required
def learner_study_materials():
    courses = Course.query.order_by(Course.id.asc()).all()

    if not courses:
        return render_template(
            "learner_study_materials.html",
            user=current_user,
            courses=courses
        )

    course = courses[0]

    modules = Module.query.filter_by(
        course_id=course.id
    ).order_by(Module.position.asc()).all()

    return render_template(
        "learner_modules.html",
        user=current_user,
        course=course,
        modules=modules
    )


# -------------------------
# LEARNER MODULE NOTES
# -------------------------

@app.route("/learner/modules/<int:module_id>")
@login_required
def learner_module_notes(module_id):
    module = Module.query.get_or_404(module_id)

    # Find or create this learner's progress record
    progress = LearnerModuleProgress.query.filter_by(
        user_id=current_user.id,
        module_id=module.id
    ).first()

    if progress is None:
        progress = LearnerModuleProgress(
            user_id=current_user.id,
            course_id=module.course_id,
            module_id=module.id
        )
        db.session.add(progress)
    else:
        progress.last_accessed_at = datetime.utcnow()

    db.session.commit()

    # Load the study notes as before
    notes = StudyNote.query.filter_by(
        module_id=module.id
    ).order_by(StudyNote.position.asc()).all()

    return render_template(
        "learner_module_notes.html",
        user=current_user,
        module=module,
        notes=notes
    )


@app.route("/learner/modules/<int:module_id>/complete", methods=["POST"])
@login_required
def complete_learner_module(module_id):
    module = Module.query.get_or_404(module_id)

    # Find this learner's progress record
    progress = LearnerModuleProgress.query.filter_by(
        user_id=current_user.id,
        module_id=module.id
    ).first()

    # Create a record if the learner has not opened this module before
    if progress is None:
        progress = LearnerModuleProgress(
            user_id=current_user.id,
            course_id=module.course_id,
            module_id=module.id,
            completed=True
        )
        db.session.add(progress)
    else:
        progress.completed = True
        progress.last_accessed_at = datetime.utcnow()

    db.session.commit()

    # Get modules in the current course, in learning order
    modules = Module.query.filter_by(
        course_id=module.course_id
    ).order_by(
        Module.position.asc(),
        Module.id.asc()
    ).all()

    current_index = next(
        i for i, item in enumerate(modules)
        if item.id == module.id
    )

    # Continue to the next module when one exists
    if current_index + 1 < len(modules):
        next_module = modules[current_index + 1]

        return redirect(
            url_for(
                "learner_module_notes",
                module_id=next_module.id
            )
        )

    # After the final module, go to the assessment
    return redirect(url_for("learner_assessment"))


# -------------------------
# LEARNER PROGRESS
# -------------------------

@app.route("/learner/progress")
@login_required
def learner_progress():
    courses = Course.query.order_by(Course.id.asc()).all()

    course_progress = {}
    total_modules = 0
    completed_modules = 0

    for course in courses:
        modules = Module.query.filter_by(
            course_id=course.id
        ).order_by(Module.position.asc()).all()

        progress_records = LearnerModuleProgress.query.filter_by(
            user_id=current_user.id,
            course_id=course.id
        ).all()

        completed_ids = {
            record.module_id
            for record in progress_records
            if record.completed
        }

        course_total = len(modules)
        course_completed = len(completed_ids)

        total_modules += course_total
        completed_modules += course_completed

        percentage = (
            round((course_completed / course_total) * 100)
            if course_total else 0
        )

        passed = AssessmentAttempt.query.filter_by(
            user_id=current_user.id,
            course_id=course.id,
            passed=True
        ).first() is not None

        last_record = max(
            progress_records,
            key=lambda record: record.last_accessed_at,
            default=None
        )

        last_module = (
            Module.query.get(last_record.module_id)
            if last_record else None
        )

        course_progress[course.id] = {
            "total_modules": course_total,
            "completed_modules": course_completed,
            "percentage": percentage,
            "passed": passed,
            "status": (
                "Completed" if passed
                else "In Progress" if last_record
                else "Not Started"
            ),
            "last_module": last_module
        }

    overall_percentage = (
        round((completed_modules / total_modules) * 100)
        if total_modules else 0
    )

    attempts = AssessmentAttempt.query.filter_by(
        user_id=current_user.id
    ).order_by(
        AssessmentAttempt.attempted_at.desc()
    ).all()

    return render_template(
        "learner_progress.html",
        user=current_user,
        courses=courses,
        course_progress=course_progress,
        total_modules=total_modules,
        completed_modules=completed_modules,
        overall_percentage=overall_percentage,
        attempts=attempts
    )


# -------------------------
# ADMIN
# -------------------------

@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template(
        "admin_dashboard.html",
        user=current_user
    )


@app.route("/admin/assessment-results")
@admin_required
def admin_assessment_results():
    if not current_user.is_admin:
        abort(403)

    attempts = AssessmentAttempt.query.order_by(
        AssessmentAttempt.attempted_at.desc()
    ).all()

    return render_template(
        "admin_assessment_results.html",
        attempts=attempts
    )


@app.route("/admin/learners")
@admin_required
def admin_learners():
    if not current_user.is_admin:
        abort(403)

    search_query = request.args.get("q", "").strip()

    learners_query = User.query.filter_by(role="learner")

    if search_query:
        learners_query = learners_query.filter(
            db.or_(
                User.full_name.ilike(f"%{search_query}%"),
                User.email.ilike(f"%{search_query}%")
            )
        )

    learners = learners_query.order_by(
        User.full_name.asc()
    ).all()

    return render_template(
        "admin_learners.html",
        learners=learners,
        search_query=search_query,
        user=current_user
    )


@app.route("/admin/courses")
@admin_required
def admin_courses():
    courses = Course.query.order_by(Course.id.asc()).all()

    return render_template(
        "admin_courses.html",
        user=current_user,
        courses=courses
    )


@app.route("/admin/cognitive-changes-guide")
@admin_required
def cognitive_changes_guide():
    return render_template(
        "cognitive_changes_guide.html",
        user=current_user
    )


@app.route("/admin/assessments")
@admin_required
def admin_assessments():
    courses = Course.query.order_by(Course.id.asc()).all()

    return render_template(
        "admin_assessments.html",
        user=current_user,
        courses=courses
    )

@app.route("/learner/assessment")
@login_required
def learner_assessment():
    course = Course.query.first_or_404()

    questions = Question.query.filter_by(
        course_id=course.id
    ).order_by(Question.position.asc()).all()

    return render_template(
        "learner_assessment.html",
        user=current_user,
        course=course,
        questions=questions
    )

@app.route(
    "/learner/assessment/<int:course_id>/submit",
    methods=["POST"]
)
@login_required
def submit_assessment(course_id):
    course = Course.query.get_or_404(course_id)

    questions = Question.query.filter_by(
        course_id=course.id
    ).order_by(Question.position.asc()).all()

    if not questions:
        flash("There are no questions to grade.", "error")
        return redirect(url_for("learner_assessment"))

    score = 0
    total = len(questions)
    results = []

    for question in questions:
        selected_answer = request.form.get(
            f"question_{question.id}", ""
        ).strip().upper()

        is_correct = selected_answer == question.correct_answer

        if is_correct:
            score += 1

        results.append({
            "question": question,
            "selected_answer": selected_answer,
            "is_correct": is_correct
        })

    
    percentage = round((score / total) * 100)

    pass_mark_setting = SystemSetting.query.filter_by(
        key="assessment_pass_mark"
    ).first()

    pass_mark = (
        int(pass_mark_setting.value)
        if pass_mark_setting
        else 80
    )

    passed = percentage >= pass_mark

    # Save this assessment attempt to the database.
    attempt = AssessmentAttempt(
        user_id=current_user.id,
        course_id=course.id,
        score=score,
        total_questions=total,
        percentage=percentage,
        passed=passed
    )

    db.session.add(attempt)
    db.session.commit()

    return render_template(
        "assessment_result.html",
        user=current_user,
        course=course,
        score=score,
        total=total,
        percentage=percentage,
        passed=passed,
        results=results
    )


@app.route("/admin/courses/<int:course_id>/assessments/questions", methods=["GET", "POST"])
@admin_required
def manage_assessment_questions(course_id):
    course = Course.query.get_or_404(course_id)

    if request.method == "POST":
        text = request.form.get("text", "").strip()
        option_a = request.form.get("option_a", "").strip()
        option_b = request.form.get("option_b", "").strip()
        option_c = request.form.get("option_c", "").strip()
        option_d = request.form.get("option_d", "").strip()
        correct_answer = request.form.get("correct_answer", "").strip().upper()

        if (
            not all([text, option_a, option_b, option_c, option_d])
            or correct_answer not in {"A", "B", "C", "D"}
        ):
            flash("Complete the question, all four options, and the correct answer.", "error")
            return redirect(url_for("manage_assessment_questions", course_id=course.id))

        question = Question(
            text=text,
            option_a=option_a,
            option_b=option_b,
            option_c=option_c,
            option_d=option_d,
            correct_answer=correct_answer,
            position=Question.query.filter_by(course_id=course.id).count() + 1,
            course_id=course.id
        )

        db.session.add(question)
        db.session.commit()

        flash("Assessment question added successfully!", "success")
        return redirect(url_for("manage_assessment_questions", course_id=course.id))

    questions = Question.query.filter_by(
        course_id=course.id
    ).order_by(Question.position.asc()).all()

    return render_template(
        "manage_assessment_questions.html",
        user=current_user,
        course=course,
        questions=questions
    )


@app.route(
    "/admin/assessment-questions/<int:question_id>/edit",
    methods=["GET", "POST"]
)
@admin_required
def edit_assessment_question(question_id):
    question = Question.query.get_or_404(question_id)

    if request.method == "POST":
        text = request.form.get("text", "").strip()
        option_a = request.form.get("option_a", "").strip()
        option_b = request.form.get("option_b", "").strip()
        option_c = request.form.get("option_c", "").strip()
        option_d = request.form.get("option_d", "").strip()
        correct_answer = request.form.get(
            "correct_answer", ""
        ).strip().upper()

        if (
            not all([
                text, option_a, option_b,
                option_c, option_d
            ])
            or correct_answer not in {"A", "B", "C", "D"}
        ):
            flash(
                "Complete the question, all four options, "
                "and the correct answer.",
                "error"
            )
            return redirect(
                url_for(
                    "edit_assessment_question",
                    question_id=question.id
                )
            )

        question.text = text
        question.option_a = option_a
        question.option_b = option_b
        question.option_c = option_c
        question.option_d = option_d
        question.correct_answer = correct_answer

        db.session.commit()

        flash("Question updated successfully!", "success")
        return redirect(
            url_for(
                "manage_assessment_questions",
                course_id=question.course_id
            )
        )

    return render_template(
        "edit_assessment_question.html",
        user=current_user,
        question=question
    )


@app.route(
    "/admin/assessment-questions/<int:question_id>/delete",
    methods=["POST"]
)
@admin_required
def delete_assessment_question(question_id):
    question = Question.query.get_or_404(question_id)
    course_id = question.course_id

    db.session.delete(question)
    db.session.commit()

    flash("Question deleted successfully.", "success")

    return redirect(
        url_for(
            "manage_assessment_questions",
            course_id=course_id
        )
    )


@app.route("/admin/courses/<int:course_id>/modules")
@admin_required
def manage_modules(course_id):
    course = db.session.get(Course, course_id)

    if course is None:
        abort(404)

    return render_template(
        "manage_modules.html",
        user=current_user,
        course=course
    )



@app.route(
    "/admin/modules/<int:module_id>/notes",
    methods=["GET", "POST"]
)
@admin_required
def manage_study_notes(module_id):
    module = Module.query.get_or_404(module_id)

    print(f"OPENING STUDY NOTES: Module ID={module.id}, Title={module.title}")

    if request.method == "POST":
        action = request.form.get("action", "add")

        if action == "add":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()

            if not title or not content:
                flash(
                    "Please enter both a note title and content.",
                    "error"
                )
                return redirect(url_for(
                    "manage_study_notes",
                    module_id=module.id
                ))

            note = StudyNote(
                title=title,
                content=content,
                position=StudyNote.query.filter_by(
                    module_id=module.id
                ).count() + 1,
                module_id=module.id
            )

            db.session.add(note)
            db.session.commit()

            flash("Study note added successfully!", "success")

        elif action == "edit":
            note_id = request.form.get("note_id", type=int)
            note = StudyNote.query.filter_by(
                id=note_id,
                module_id=module.id
            ).first_or_404()

            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()

            if not title or not content:
                flash(
                    "Please enter both a note title and content.",
                    "error"
                )
                return redirect(url_for(
                    "manage_study_notes",
                    module_id=module.id
                ))

            note.title = title
            note.content = content

            db.session.commit()
            flash("Study note updated successfully!", "success")

        elif action == "delete":
            note_id = request.form.get("note_id", type=int)
            note = StudyNote.query.filter_by(
                id=note_id,
                module_id=module.id
            ).first_or_404()

            db.session.delete(note)
            db.session.commit()

            flash("Study note deleted successfully!", "success")

        else:
            flash("Invalid action.", "error")

        return redirect(url_for(
            "manage_study_notes",
            module_id=module.id
        ))

    notes = StudyNote.query.filter_by(
        module_id=module.id
    ).order_by(StudyNote.position.asc()).all()

    return render_template(
        "manage_study_notes.html",
        user=current_user,
        module=module,
        notes=notes,
        debug_message="CORRECT STUDY NOTES TEMPLATE"
    )


@app.route("/admin/courses/add", methods=["GET", "POST"])
@admin_required
def add_course():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()

        if not title:
            flash("Please enter a course title.", "error")
            return render_template(
                "add_course.html",
                user=current_user,
                title=title,
                description=description
            )

        existing_course = Course.query.filter_by(title=title).first()

        if existing_course:
            flash("A course with this title already exists.", "error")
            return render_template(
                "add_course.html",
                user=current_user,
                title=title,
                description=description
            )

        course = Course(
            title=title,
            description=description or None
        )

        db.session.add(course)
        db.session.commit()

        flash("Course created successfully!", "success")
        return redirect(url_for("admin_courses"))

    return render_template(
        "add_course.html",
        user=current_user,
        title="",
        description=""
    )



# -------------------------
# LOGOUT
# -------------------------

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have signed out successfully.", "success")
    return redirect(url_for("login"))


# -------------------------
# DATABASE INITIALIZATION
# -------------------------

with app.app_context():
    db.create_all()


# -------------------------
# START APPLICATION
# -------------------------

if __name__ == "__main__":
    app.run(
        debug=not IS_PRODUCTION
    )
