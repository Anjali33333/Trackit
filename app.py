from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import razorpay
import json
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from io import BytesIO
from sqlalchemy.sql import text

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-123'  # Using a constant secret key
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads/medical_certificates'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Email Configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USERNAME'] = 'anjalisreekumar0304@gmail.com'
app.config['MAIL_PASSWORD'] = 'ilzp yiqj ktic wspo'  # App password from Gmail (removed spaces)
app.config['MAIL_USE_TLS'] = True

# Razorpay Configuration
RAZORPAY_KEY_ID = 'rzp_test_dlLIxHdrPSrAuw'  # Replace with your Razorpay Key ID
RAZORPAY_KEY_SECRET = 'FjTb7Kvh8Ev88eQxz1RPLuwT'  # Replace with your Razorpay Key Secret
client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    user_type = db.Column(db.String(20), nullable=False)  # 'Student', 'Teacher', or 'Admin'
    # Optional fields for students
    roll_number = db.Column(db.String(20), unique=True, nullable=True)
    department = db.Column(db.String(50), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    # Password reset fields
    reset_token = db.Column(db.String(100), unique=True, nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)
    # Relationships
    attendances = db.relationship('Attendance', backref='student', lazy=True, cascade='all, delete-orphan')
    leave_requests = db.relationship('LeaveRequest', backref='student', lazy=True, cascade='all, delete-orphan')
    medical_certificates = db.relationship('MedicalCertificate', backref='student', lazy=True, cascade='all, delete-orphan')
    donations = db.relationship('Donation', backref='donor', lazy=True, cascade='all, delete-orphan')

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False)

class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending')

class MedicalCertificate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    leave_request_id = db.Column(db.Integer, db.ForeignKey('leave_request.id'), nullable=True)
    leave_request = db.relationship('LeaveRequest', backref='medical_certificate')

class Donation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_id = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='completed')  # completed, failed
    donation_date = db.Column(db.DateTime, default=datetime.utcnow)

# Create tables only if they don't exist
with app.app_context():
    # Create all tables with new schema
    db.create_all()
    
    # Check and add new columns to medical_certificate table if they don't exist
    try:
        with db.engine.connect() as conn:
            # Get existing columns
            result = conn.execute(text("PRAGMA table_info(medical_certificate)"))
            existing_columns = [row[1] for row in result.fetchall()]
            
            # Add start_date if it doesn't exist
            if 'start_date' not in existing_columns:
                conn.execute(text("ALTER TABLE medical_certificate ADD COLUMN start_date DATE"))
            
            # Add end_date if it doesn't exist
            if 'end_date' not in existing_columns:
                conn.execute(text("ALTER TABLE medical_certificate ADD COLUMN end_date DATE"))
            
            conn.commit()
    except Exception as e:
        print(f"Error checking/adding columns: {str(e)}")
    
    # Create default admin user if it doesn't exist
    admin = User.query.filter_by(email='admin@trackit.com').first()
    if not admin:
        admin = User(
            name='Admin',
            email='admin@trackit.com',
            password=generate_password_hash('admin123'),
            user_type='Admin'
        )
        db.session.add(admin)
        db.session.commit()

# Routes
@app.route('/')
def index():
    if 'user_id' in session:
        if session['user_type'] == 'Student':
            return redirect(url_for('student_dashboard'))
        elif session['user_type'] == 'Teacher':
            return redirect(url_for('teacher_dashboard'))
        elif session['user_type'] == 'Admin':
            return redirect(url_for('admin_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user_type = request.form.get('user_type')
        not_robot = request.form.get('not_robot')

        # Debug print
        print(f"Login attempt - Email: {email}, User Type: {user_type}")

        # Check if the user checked the "I am not a robot" checkbox
        if not not_robot:
            flash('Please confirm that you are not a robot.', 'error')
            return redirect(url_for('login'))

        user = User.query.filter_by(email=email, user_type=user_type).first()
        if user:
            print(f"User found - ID: {user.id}, Name: {user.name}")
            if check_password_hash(user.password, password):
                session['user_id'] = user.id
                session['user_type'] = user.user_type
                session['name'] = user.name
                flash('Logged in successfully!', 'success')
                print(f"Login successful - User ID: {user.id}")
                if user_type == 'Student':
                    return redirect(url_for('student_dashboard'))
                elif user_type == 'Teacher':
                    return redirect(url_for('teacher_dashboard'))
            else:
                print("Password verification failed")
        else:
            print("User not found")
        flash('Invalid credentials.', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        user_type = request.form.get('user_type')
        department = request.form.get('department')

        # Check if passwords match
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('register'))

        # Check if email already exists
        if User.query.filter_by(email=email).first():
            flash('Email already exists.', 'error')
            return redirect(url_for('register'))

        # Create new user
        new_user = User(
            name=name,
            email=email,
            password=generate_password_hash(password),
            user_type=user_type,
            department=department  # Set department for both students and teachers
        )

        # Add student-specific fields if user is a student
        if user_type == 'Student':
            roll_number = request.form.get('roll_number')
            phone = request.form.get('phone')

            # Check if roll number already exists
            if User.query.filter_by(roll_number=roll_number).first():
                flash('Roll number already exists.', 'error')
                return redirect(url_for('register'))

            new_user.roll_number = roll_number
            new_user.phone = phone

        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred. Please try again.', 'error')
            return redirect(url_for('register'))

    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/student/dashboard')
def student_dashboard():
    if 'user_id' not in session or session['user_type'] != 'Student':
        return redirect(url_for('login'))
    
    attendances = Attendance.query.filter_by(student_id=session['user_id']).order_by(Attendance.date.desc()).all()
    leave_requests = LeaveRequest.query.filter_by(student_id=session['user_id']).order_by(LeaveRequest.start_date.desc()).all()
    medical_certificates = MedicalCertificate.query.filter_by(student_id=session['user_id']).order_by(MedicalCertificate.upload_date.desc()).all()
    donations = Donation.query.filter_by(student_id=session['user_id']).order_by(Donation.donation_date.desc()).all()
    
    return render_template('student_dashboard.html', 
                         attendances=attendances, 
                         leave_requests=leave_requests,
                         medical_certificates=medical_certificates,
                         donations=donations)

@app.route('/student/leave/apply', methods=['POST'])
def apply_leave():
    if 'user_id' not in session or session['user_type'] != 'Student':
        return redirect(url_for('login'))

    # Check for any pending leave requests
    pending_leave = LeaveRequest.query.filter(
        LeaveRequest.student_id == session['user_id'],
        LeaveRequest.status == 'pending'
    ).first()

    if pending_leave:
        flash('You already have a pending leave request. Please wait for it to be approved or rejected before applying for another leave.', 'error')
        return redirect(url_for('student_dashboard'))

    try:
        start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d').date()
        reason = request.form.get('reason')

        # Validate dates
        today = datetime.now().date()
        if start_date < today:
            flash('Cannot apply for leave on past dates.', 'error')
            return redirect(url_for('student_dashboard'))

        if end_date < start_date:
            flash('End date cannot be before start date.', 'error')
            return redirect(url_for('student_dashboard'))

        # Check for overlapping leave requests
        existing_leave = LeaveRequest.query.filter(
            LeaveRequest.student_id == session['user_id'],
            LeaveRequest.status != 'rejected',  # Don't count rejected leaves
            (
                # Check if new leave overlaps with existing leave
                (LeaveRequest.start_date <= end_date) & (LeaveRequest.end_date >= start_date)
            )
        ).first()

        if existing_leave:
            flash('You already have a leave request for these dates. Please check your existing leave requests.', 'error')
            return redirect(url_for('student_dashboard'))

        # Create leave request
        leave_request = LeaveRequest(
            student_id=session['user_id'],
            start_date=start_date,
            end_date=end_date,
            reason=reason
        )
        db.session.add(leave_request)
        db.session.commit()

        # Handle medical certificate upload if provided
        if 'certificate' in request.files:
            file = request.files['certificate']
            if file and file.filename != '' and allowed_file(file.filename):
                try:
                    # Ensure upload directory exists
                    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                    
                    # Generate a unique filename
                    filename = f"{session['user_id']}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    
                    # Save the file
                    file.save(file_path)
                    
                    # Verify file was saved
                    if not os.path.exists(file_path):
                        raise Exception("File was not saved successfully")

                    # Create certificate record
                    certificate = MedicalCertificate(
                        student_id=session['user_id'],
                        filename=filename,
                        leave_request_id=leave_request.id,
                        start_date=start_date,
                        end_date=end_date
                    )
                    db.session.add(certificate)
                    db.session.commit()

                    flash('Leave request submitted with medical certificate!', 'success')
                except Exception as e:
                    app.logger.error(f"Error saving medical certificate: {str(e)}")
                    flash('Error saving medical certificate. Please try again.', 'error')
                    # Delete the leave request if certificate upload failed
                    db.session.delete(leave_request)
                    db.session.commit()
                    return redirect(url_for('student_dashboard'))
            else:
                flash('Leave request submitted, but invalid certificate file.', 'warning')
        else:
            flash('Leave request submitted successfully!', 'success')

    except ValueError:
        flash('Invalid date format.', 'error')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error applying for leave: {str(e)}")
        flash('Error submitting leave request. Please try again.', 'error')

    return redirect(url_for('student_dashboard'))

@app.route('/teacher/dashboard')
def teacher_dashboard():
    if 'user_id' not in session or session['user_type'] != 'Teacher':
        return redirect(url_for('login'))
    
    # Get the teacher's department using the newer SQLAlchemy 2.0 style
    teacher = db.session.get(User, session['user_id'])
    teacher_department = teacher.department
    
    # Get search query from request args
    search_query = request.args.get('search', '')
    
    # Get students from the same department as the teacher
    if search_query:
        students = User.query.filter(
            User.user_type == 'Student',
            User.department == teacher_department,
            User.name.ilike(f'%{search_query}%')
        ).all()
    else:
        students = User.query.filter_by(
            user_type='Student',
            department=teacher_department
        ).all()
    
    # Get leave requests for students in the same department
    leave_requests = LeaveRequest.query.join(User).filter(
        User.user_type == 'Student',
        User.department == teacher_department
    ).order_by(LeaveRequest.start_date.desc()).all()
    
    # Get donation information for students in the same department
    donations = Donation.query.join(User).filter(
        User.user_type == 'Student',
        User.department == teacher_department
    ).order_by(Donation.donation_date.desc()).all()
    total_donations = sum(donation.amount for donation in donations)
    recent_donations = donations[:10]  # Get the 10 most recent donations
    
    return render_template('teacher_dashboard.html', 
                         students=students, 
                         leave_requests=leave_requests,
                         donations=donations,
                         total_donations=total_donations,
                         recent_donations=recent_donations)

@app.route('/teacher/attendance/mark', methods=['GET', 'POST'])
def mark_attendance_page():
    if 'user_id' not in session or session['user_type'] != 'Teacher':
        return redirect(url_for('login'))
    
    # Get the teacher's department
    teacher = User.query.get(session['user_id'])
    teacher_department = teacher.department
    
    if request.method == 'POST':
        date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        
        # Get students from the same department as the teacher
        students = User.query.filter_by(
            user_type='Student',
            department=teacher_department
        ).all()
        
        # Process attendance for each student
        for student in students:
            status = request.form.get(f'status_{student.id}')
            if status:
                # Check if attendance record exists for this date
                attendance = Attendance.query.filter_by(
                    student_id=student.id,
                    date=date
                ).first()
                
                if attendance:
                    attendance.status = status
                else:
                    attendance = Attendance(
                        student_id=student.id,
                        date=date,
                        status=status
                    )
                    db.session.add(attendance)
        
        db.session.commit()
        flash('Attendance marked successfully!', 'success')
        return redirect(url_for('mark_attendance_page'))
    
    # Get students from the same department as the teacher
    students = User.query.filter_by(
        user_type='Student',
        department=teacher_department
    ).all()
    
    return render_template('mark_attendance.html', students=students)

@app.route('/teacher/leave/update/<int:leave_id>', methods=['POST'])
def update_leave(leave_id):
    if 'user_id' not in session or session['user_type'] != 'Teacher':
        return redirect(url_for('login'))

    # Get the teacher's department
    teacher = User.query.get(session['user_id'])
    teacher_department = teacher.department

    leave = LeaveRequest.query.get_or_404(leave_id)
    
    # Ensure the leave request belongs to a student in teacher's department
    if leave.student.department != teacher_department:
        flash('You can only manage leave requests for students in your department.', 'error')
        return redirect(url_for('teacher_dashboard'))

    status = request.form.get('status')
    if status in ['approved', 'rejected']:
        leave.status = status
        leave.teacher_id = session['user_id']
        db.session.commit()
        flash('Leave request updated successfully!', 'success')
    return redirect(url_for('teacher_dashboard'))

@app.route('/student/leave/delete', methods=['POST'])
def delete_leave_request():
    if 'user_id' not in session or session['user_type'] != 'Student':
        return redirect(url_for('login'))

    leave_id = request.form.get('leave_id')
    leave_request = LeaveRequest.query.get_or_404(leave_id)

    # Ensure the leave request belongs to the current student and is pending
    if leave_request.student_id != session['user_id'] or leave_request.status != 'pending':
        flash('You can only delete your own pending leave requests.', 'error')
        return redirect(url_for('student_dashboard'))

    # Delete the leave request
    db.session.delete(leave_request)
    db.session.commit()

    flash('Leave request deleted successfully!', 'success')
    return redirect(url_for('student_dashboard'))

@app.route('/teacher/students')
def manage_students():
    if 'user_id' not in session or session['user_type'] != 'Teacher':
        return redirect(url_for('login'))
    
    # Get the teacher's department
    teacher = User.query.get(session['user_id'])
    teacher_department = teacher.department
    
    # Only show students from the teacher's department
    students = User.query.filter_by(
        user_type='Student',
        department=teacher_department
    ).all()
    return render_template('manage_students.html', students=students)

@app.route('/teacher/student/add', methods=['POST'])
def add_student():
    if 'user_id' not in session or session['user_type'] != 'Teacher':
        return redirect(url_for('login'))

    # Get the teacher's department
    teacher = User.query.get(session['user_id'])
    teacher_department = teacher.department

    name = request.form.get('name')
    email = request.form.get('email')
    roll_number = request.form.get('roll_number')
    phone = request.form.get('phone')
    password = request.form.get('password')

    if User.query.filter_by(email=email).first():
        flash('Email already exists.', 'error')
        return redirect(url_for('manage_students'))

    if User.query.filter_by(roll_number=roll_number).first():
        flash('Roll number already exists.', 'error')
        return redirect(url_for('manage_students'))

    hashed_password = generate_password_hash(password)
    new_student = User(
        name=name,
        email=email,
        password=hashed_password,
        user_type='Student',
        roll_number=roll_number,
        department=teacher_department,  # Use teacher's department
        phone=phone
    )

    try:
        db.session.add(new_student)
        db.session.commit()
        flash('Student added successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error adding student. Please try again.', 'error')

    return redirect(url_for('manage_students'))

@app.route('/teacher/student/edit/<int:student_id>', methods=['GET', 'POST'])
def edit_student(student_id):
    if 'user_id' not in session or session['user_type'] != 'Teacher':
        return redirect(url_for('login'))

    # Get the teacher's department
    teacher = User.query.get(session['user_id'])
    teacher_department = teacher.department

    student = User.query.get_or_404(student_id)
    
    # Ensure student belongs to teacher's department
    if student.department != teacher_department:
        flash('You can only edit students from your department.', 'error')
        return redirect(url_for('manage_students'))

    if request.method == 'POST':
        student.name = request.form.get('name')
        student.roll_number = request.form.get('roll_number')
        student.phone = request.form.get('phone')
        
        if request.form.get('password'):
            student.password = generate_password_hash(request.form.get('password'))

        try:
            db.session.commit()
            flash('Student details updated successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash('Error updating student details. Please try again.', 'error')

    return redirect(url_for('manage_students'))

@app.route('/teacher/student/delete/<int:student_id>', methods=['POST'])
def delete_student(student_id):
    if 'user_id' not in session or session['user_type'] != 'Teacher':
        return redirect(url_for('login'))

    try:
        # Get the student
        student = User.query.get_or_404(student_id)
        if student.user_type != 'Student':
            flash('Invalid student.', 'error')
            return redirect(url_for('manage_students'))

        # Delete medical certificate files first
        for certificate in student.medical_certificates:
            try:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], certificate.filename)
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"Error deleting certificate file {certificate.filename}: {str(e)}")
                # Continue with deletion even if file removal fails

        # Delete all related records first
        try:
            # Delete attendance records
            Attendance.query.filter_by(student_id=student.id).delete()
            
            # Delete leave requests
            LeaveRequest.query.filter_by(student_id=student.id).delete()
            
            # Delete medical certificates
            MedicalCertificate.query.filter_by(student_id=student.id).delete()
            
            # Delete donations
            Donation.query.filter_by(student_id=student.id).delete()
            
            # Delete the student
            db.session.delete(student)
            db.session.commit()
            
            flash('Student and all related records deleted successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            print(f"Database error while deleting student: {str(e)}")
            flash('Error deleting student records. Please try again.', 'error')
            return redirect(url_for('manage_students'))

    except Exception as e:
        print(f"Unexpected error while deleting student: {str(e)}")
        flash('An unexpected error occurred. Please try again.', 'error')
        return redirect(url_for('manage_students'))

    return redirect(url_for('manage_students'))

@app.route('/student/certificate/upload', methods=['POST'])
def upload_certificate():
    if 'user_id' not in session or session['user_type'] != 'Student':
        return redirect(url_for('login'))

    if 'certificate' not in request.files:
        flash('No file selected.', 'error')
        return redirect(url_for('student_dashboard'))

    file = request.files['certificate']
    if file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('student_dashboard'))

    try:
        start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d').date()
        
        if end_date < start_date:
            flash('End date cannot be before start date.', 'error')
            return redirect(url_for('student_dashboard'))

        if file and allowed_file(file.filename):
            # Generate a unique filename
            filename = f"{session['user_id']}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            # Create certificate record
            certificate = MedicalCertificate(
                student_id=session['user_id'],
                filename=filename,
                start_date=start_date,
                end_date=end_date
            )
            db.session.add(certificate)
            db.session.commit()

            flash('Medical certificate uploaded successfully!', 'success')
        else:
            flash('Invalid file type. Allowed types: PNG, JPG, JPEG, PDF', 'error')
    except ValueError:
        flash('Invalid date format.', 'error')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error uploading certificate: {str(e)}")
        flash('Error uploading medical certificate. Please try again.', 'error')

    return redirect(url_for('student_dashboard'))

@app.route('/student/certificate/delete', methods=['POST'])
def delete_certificate():
    if 'user_id' not in session or session['user_type'] != 'Student':
        flash('Please login to delete medical certificates.', 'error')
        return redirect(url_for('login'))

    try:
        certificate_id = request.form.get('certificate_id')
        certificate = MedicalCertificate.query.get_or_404(certificate_id)

        # Check if the certificate belongs to the current student
        if certificate.student_id != session['user_id']:
            flash('You do not have permission to delete this certificate.', 'error')
            return redirect(url_for('student_dashboard'))

        # Delete the file from the filesystem
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], certificate.filename)
        if os.path.exists(file_path):
            os.remove(file_path)

        # Delete the database record
        db.session.delete(certificate)
        db.session.commit()

        flash('Medical certificate deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting certificate: {str(e)}")
        flash('Error deleting medical certificate. Please try again.', 'error')

    return redirect(url_for('student_dashboard'))

@app.route('/teacher/certificates')
def view_certificates():
    if 'user_id' not in session or session['user_type'] != 'Teacher':
        return redirect(url_for('login'))
    
    # Get the teacher's department
    teacher = User.query.get(session['user_id'])
    teacher_department = teacher.department
    
    # Get certificates only for students in the same department
    certificates = MedicalCertificate.query.join(User).filter(
        User.user_type == 'Student',
        User.department == teacher_department
    ).order_by(MedicalCertificate.upload_date.desc()).all()
    
    return render_template('view_certificates.html', certificates=certificates)

@app.route('/certificate/<filename>')
def serve_certificate(filename):
    try:
        # Check if user is logged in
        if 'user_id' not in session:
            flash('Please login to view medical certificates.', 'error')
            return redirect(url_for('login'))
            
        # Get the certificate record
        certificate = MedicalCertificate.query.filter_by(filename=filename).first_or_404()
        
        # Check if user has permission to view the certificate
        if session['user_type'] == 'Student' and certificate.student_id != session['user_id']:
            flash('You do not have permission to view this certificate.', 'error')
            return redirect(url_for('student_dashboard'))
            
        # Ensure the upload folder exists
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        
        # Check if file exists
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if not os.path.exists(file_path):
            app.logger.error(f"File not found: {file_path}")
            flash('Medical certificate not found.', 'error')
            return redirect(url_for('student_dashboard'))
            
        # Get file extension
        file_ext = os.path.splitext(filename)[1].lower()
        
        # Set appropriate MIME type
        mime_types = {
            '.pdf': 'application/pdf',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png'
        }
        mimetype = mime_types.get(file_ext, 'application/octet-stream')
        
        # Log the request
        app.logger.info(f"Serving file: {filename} with mimetype: {mimetype}")
        
        # Use send_file with absolute path
        return send_file(
            file_path,
            mimetype=mimetype,
            as_attachment=False
        )
    except Exception as e:
        app.logger.error(f"Error serving certificate: {str(e)}")
        flash('Error accessing medical certificate.', 'error')
        return redirect(url_for('student_dashboard'))

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'user_id' not in session or session['user_type'] != 'Admin':
        return redirect(url_for('login'))
    
    # Get statistics
    total_students = User.query.filter_by(user_type='Student').count()
    total_teachers = User.query.filter_by(user_type='Teacher').count()
    total_attendance = Attendance.query.count()
    total_leave_requests = LeaveRequest.query.count()
    
    # Get all departments from both students and teachers
    student_departments = db.session.query(User.department).filter(User.user_type=='Student').distinct().all()
    teacher_departments = db.session.query(User.department).filter(User.user_type=='Teacher').distinct().all()
    
    # Combine and deduplicate departments
    departments = list(set([dept[0] for dept in student_departments] + [dept[0] for dept in teacher_departments]))
    
    # Get students grouped by department
    students_by_dept = {}
    for dept in departments:
        students = User.query.filter_by(user_type='Student', department=dept).all()
        students_by_dept[dept] = students
    
    # Get teachers grouped by department
    teachers_by_dept = {}
    for dept in departments:
        teachers = User.query.filter_by(user_type='Teacher', department=dept).all()
        teachers_by_dept[dept] = teachers
    
    # Get attendance records grouped by department
    attendance_by_dept = {}
    for dept in departments:
        attendance = Attendance.query.join(User).filter(
            User.user_type=='Student',
            User.department==dept
        ).order_by(Attendance.date.desc()).limit(10).all()
        attendance_by_dept[dept] = attendance
    
    # Get student statistics grouped by department
    student_stats_by_dept = {}
    for dept in departments:
        students = User.query.filter_by(user_type='Student', department=dept).all()
        stats = []
        for student in students:
            attendance_count = Attendance.query.filter_by(student_id=student.id).count()
            present_count = Attendance.query.filter_by(student_id=student.id, status='Present').count()
            absent_count = Attendance.query.filter_by(student_id=student.id, status='Absent').count()
            attendance_percentage = (present_count / attendance_count * 100) if attendance_count > 0 else 0
            
            stats.append({
                'student': student,
                'attendance_count': attendance_count,
                'present_count': present_count,
                'absent_count': absent_count,
                'attendance_percentage': round(attendance_percentage, 2)
            })
        student_stats_by_dept[dept] = stats
    
    return render_template('admin_dashboard.html',
                         total_students=total_students,
                         total_teachers=total_teachers,
                         total_attendance=total_attendance,
                         total_leave_requests=total_leave_requests,
                         departments=departments,
                         students_by_dept=students_by_dept,
                         teachers_by_dept=teachers_by_dept,
                         attendance_by_dept=attendance_by_dept,
                         student_stats_by_dept=student_stats_by_dept)

@app.route('/admin/students')
def admin_students():
    if 'user_id' not in session or session['user_type'] != 'Admin':
        return redirect(url_for('login'))
    
    students = User.query.filter_by(user_type='Student').all()
    return render_template('admin_students.html', students=students)

@app.route('/admin/teachers')
def admin_teachers():
    if 'user_id' not in session or session['user_type'] != 'Admin':
        return redirect(url_for('login'))
    
    teachers = User.query.filter_by(user_type='Teacher').all()
    return render_template('admin_teachers.html', teachers=teachers)

@app.route('/admin/attendance')
def admin_attendance():
    if 'user_id' not in session or session['user_type'] != 'Admin':
        return redirect(url_for('login'))
    
    # Get all attendance records with student details
    attendance_records = Attendance.query.join(User).filter(User.user_type=='Student').order_by(Attendance.date.desc()).all()
    return render_template('admin_attendance.html', attendance_records=attendance_records)

@app.route('/admin/student/edit/<int:student_id>', methods=['POST'])
def admin_edit_student(student_id):
    if 'user_id' not in session or session['user_type'] != 'Admin':
        return redirect(url_for('login'))

    student = User.query.get_or_404(student_id)
    if student.user_type != 'Student':
        flash('Invalid student.', 'error')
        return redirect(url_for('admin_students'))

    # Check if email is already taken by another user
    email = request.form.get('email')
    if email != student.email and User.query.filter_by(email=email).first():
        flash('Email already exists.', 'error')
        return redirect(url_for('admin_students'))

    # Check if roll number is already taken by another student
    roll_number = request.form.get('roll_number')
    if roll_number != student.roll_number and User.query.filter_by(roll_number=roll_number).first():
        flash('Roll number already exists.', 'error')
        return redirect(url_for('admin_students'))

    try:
        student.name = request.form.get('name')
        student.email = email
        student.roll_number = roll_number
        student.department = request.form.get('department')
        student.phone = request.form.get('phone')
        
        db.session.commit()
        flash('Student details updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error updating student details. Please try again.', 'error')

    return redirect(url_for('admin_students'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # Check for default admin credentials
        if username == 'admin' and password == 'admin123':
            admin = User.query.filter_by(email='admin@trackit.com').first()
            if admin:
                session['user_id'] = admin.id
                session['user_type'] = admin.user_type
                session['name'] = admin.name
                flash('Admin logged in successfully!', 'success')
                return redirect(url_for('admin_dashboard'))
        
        flash('Invalid admin credentials.', 'error')
    return render_template('admin_login.html')

@app.route('/student/donate', methods=['GET', 'POST'])
def donate():
    if 'user_id' not in session or session['user_type'] != 'Student':
        return redirect(url_for('login'))

    if request.method == 'POST':
        amount = float(request.form.get('amount')) * 100  # Convert to paise
        student = User.query.get(session['user_id'])
        
        # Create Razorpay order
        order_data = {
            'amount': int(amount),
            'currency': 'INR',
            'receipt': f'donation_{session["user_id"]}_{datetime.utcnow().strftime("%Y%m%d%H%M%S")}',
            'payment_capture': 1
        }
        
        try:
            order = client.order.create(data=order_data)
            return jsonify({
                'order_id': order['id'],
                'amount': amount,
                'currency': 'INR',
                'key': RAZORPAY_KEY_ID
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    return render_template('donate.html')

@app.route('/student/donation/verify', methods=['POST'])
def verify_donation():
    if 'user_id' not in session or session['user_type'] != 'Student':
        return redirect(url_for('login'))

    try:
        # Verify payment signature
        payment_id = request.form.get('razorpay_payment_id')
        order_id = request.form.get('razorpay_order_id')
        signature = request.form.get('razorpay_signature')
        
        client.utility.verify_payment_signature({
            'razorpay_payment_id': payment_id,
            'razorpay_order_id': order_id,
            'razorpay_signature': signature
        })

        # Get payment details
        payment = client.payment.fetch(payment_id)
        
        # Create donation record
        donation = Donation(
            student_id=session['user_id'],
            amount=float(payment['amount']) / 100,  # Convert from paise to rupees
            payment_id=payment_id
        )
        db.session.add(donation)
        db.session.commit()

        return jsonify({'success': True, 'donation_id': donation.id})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/student/donation/invoice/<int:donation_id>')
def download_invoice(donation_id):
    if 'user_id' not in session or session['user_type'] != 'Student':
        return redirect(url_for('login'))

    try:
        # Get the donation record
        donation = Donation.query.get_or_404(donation_id)
        
        # Verify the donation belongs to the current user
        if donation.student_id != session['user_id']:
            flash('You do not have permission to access this invoice.', 'error')
            return redirect(url_for('student_dashboard'))

        # Get the donor information directly from the session
        # This avoids the need to query the database for the user
        donor_name = session.get('name', 'Unknown')
        donor_roll = User.query.get(session['user_id']).roll_number if User.query.get(session['user_id']) else 'Unknown'
        donor_email = session.get('email', 'Unknown')

        # Create PDF invoice
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        elements = []

        # Invoice data
        data = [
            ['Department Fund Collection Invoice'],
            [''],
            ['Invoice Number:', f'INV-{donation.id:06d}'],
            ['Date:', donation.donation_date.strftime('%Y-%m-%d %H:%M')],
            [''],
            ['Student Details:'],
            ['Name:', donor_name],
            ['Roll Number:', donor_roll],
            ['Email:', donor_email],
            [''],
            ['Amount:', f'₹{donation.amount:.2f}']
        ]

        # Create table
        table = Table(data)
        table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 16),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 20),
            ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 1), (-1, 1), 12),
            ('BOTTOMPADDING', (0, 1), (-1, 1), 12),
            ('FONTNAME', (0, 2), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 2), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 2), (-1, -1), 6),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('ALIGN', (0, 1), (-1, 1), 'CENTER'),
            ('ALIGN', (0, 2), (-1, -1), 'LEFT'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ]))

        elements.append(table)
        doc.build(elements)

        buffer.seek(0)
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'invoice_{donation.id}.pdf'
        )
    except Exception as e:
        print(f"Error generating invoice: {str(e)}")
        flash('An error occurred while generating the invoice. Please try again later.', 'error')
        return redirect(url_for('student_dashboard'))

@app.route('/student/department/invoice')
def download_department_invoice():
    if 'user_id' not in session or session['user_type'] != 'Student':
        return redirect(url_for('login'))
    
    student = User.query.get(session['user_id'])
    donations = Donation.query.filter_by(student_id=session['user_id']).order_by(Donation.donation_date.desc()).all()
    
    # Calculate total donations
    total_amount = sum(donation.amount for donation in donations)
    
    # Create PDF invoice
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    # Invoice data
    data = [
        ['Department Fund Collection Summary'],
        [''],
        ['Invoice Number:', f'DEPT-{session["user_id"]}-{datetime.utcnow().strftime("%Y%m%d")}'],
        ['Date:', datetime.utcnow().strftime('%Y-%m-%d %H:%M')],
        [''],
        ['Student Details:'],
        ['Name:', student.name],
        ['Roll Number:', student.roll_number],
        ['Email:', student.email],
        [''],
        ['Total Amount:', f'₹{total_amount:.2f}']
    ]
    
    # Create table
    table = Table(data)
    table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 16),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 20),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (-1, 1), 12),
        ('BOTTOMPADDING', (0, 1), (-1, 1), 12),
        ('FONTNAME', (0, 2), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 2), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 2), (-1, -1), 6),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (0, 1), (-1, 1), 'CENTER'),
        ('ALIGN', (0, 2), (-1, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
    ]))
    
    elements.append(table)
    doc.build(elements)
    
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'department_invoice_{student.roll_number}.pdf'
    )

def send_email(to_email, subject, body):
    """Send an email using SMTP"""
    try:
        print(f"Attempting to send email to: {to_email}")
        print(f"Using SMTP server: {app.config['MAIL_SERVER']}:{app.config['MAIL_PORT']}")
        print(f"Using email account: {app.config['MAIL_USERNAME']}")
        
        msg = MIMEMultipart()
        msg['From'] = app.config['MAIL_USERNAME']
        msg['To'] = to_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Create SMTP connection with explicit error handling
        print("Creating SMTP connection...")
        server = smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT'])
        print("SMTP connection created")
        
        print("Starting EHLO...")
        server.ehlo()
        print("EHLO completed")
        
        print("Starting TLS...")
        server.starttls()
        print("TLS started")
        
        print("Starting EHLO after TLS...")
        server.ehlo()
        print("EHLO after TLS completed")
        
        # Login with detailed error handling
        try:
            print("Attempting to login...")
            server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
            print("Login successful")
        except smtplib.SMTPAuthenticationError as e:
            print(f"SMTP Authentication Error: {str(e)}")
            print("Please check your email and app password")
            return False
        except Exception as e:
            print(f"Login Error: {str(e)}")
            print(f"Error type: {type(e)}")
            return False
        
        # Send email with error handling
        try:
            print("Attempting to send message...")
            server.send_message(msg)
            print(f"Email sent successfully to {to_email}")
            return True
        except Exception as e:
            print(f"Error sending message: {str(e)}")
            print(f"Error type: {type(e)}")
            return False
        finally:
            print("Closing SMTP connection...")
            server.quit()
            print("SMTP connection closed")
    except Exception as e:
        print(f"General email error: {str(e)}")
        print(f"Error type: {type(e)}")
        return False

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user_type = request.form.get('user_type')
        
        user = User.query.filter_by(email=email, user_type=user_type).first()
        
        if user:
            # Generate a secure token
            token = secrets.token_urlsafe(32)
            expiry = datetime.utcnow() + timedelta(hours=1)  # Token expires in 1 hour
            
            # Save token to database
            user.reset_token = token
            user.reset_token_expiry = expiry
            db.session.commit()
            
            # Create reset link
            reset_link = url_for('reset_password', token=token, _external=True)
            
            # Email content
            subject = "Password Reset Request - TrackIt"
            body = f"""
            Hello {user.name},
            
            You have requested to reset your password for your TrackIt account.
            
            Please click on the following link to reset your password:
            {reset_link}
            
            This link will expire in 1 hour.
            
            If you did not request this password reset, please ignore this email.
            
            Best regards,
            TrackIt Team
            """
            
            # Send email
            if send_email(user.email, subject, body):
                flash('Password reset instructions have been sent to your email.', 'success')
            else:
                flash('Failed to send reset email. Please try again later.', 'error')
        else:
            # Don't reveal if the email exists or not for security reasons
            flash('If your email is registered, you will receive password reset instructions.', 'success')
        
        return redirect(url_for('login'))
    
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # Find user with this token
    user = User.query.filter_by(reset_token=token).first()
    
    if not user or not user.reset_token_expiry or user.reset_token_expiry < datetime.utcnow():
        flash('Invalid or expired reset token. Please request a new password reset.', 'error')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('reset_password.html', token=token)
        
        # Update password
        user.password = generate_password_hash(password)
        user.reset_token = None
        user.reset_token_expiry = None
        db.session.commit()
        
        flash('Your password has been reset successfully. You can now login with your new password.', 'success')
        return redirect(url_for('login'))
    
    return render_template('reset_password.html', token=token)

@app.route('/teacher/student/search')
def student_search():
    if 'user_id' not in session or session['user_type'] != 'Teacher':
        return redirect(url_for('login'))
    
    # Get the teacher's department
    teacher = User.query.get(session['user_id'])
    teacher_department = teacher.department
    
    # Get search query from request args
    search_query = request.args.get('search', '')
    
    # Get students filtered by name and department if search query exists
    if search_query:
        students = User.query.filter(
            User.user_type == 'Student',
            User.department == teacher_department,
            User.name.ilike(f'%{search_query}%')
        ).all()
    else:
        # If no search query, show all students from teacher's department
        students = User.query.filter_by(
            user_type='Student',
            department=teacher_department
        ).all()
    
    return render_template('student_search_results.html', 
                         students=students, 
                         search_query=search_query)

@app.route('/admin/teacher/delete/<int:teacher_id>', methods=['POST'])
def delete_teacher(teacher_id):
    if 'user_id' not in session or session['user_type'] != 'Admin':
        return redirect(url_for('login'))

    try:
        # Get the teacher
        teacher = User.query.get_or_404(teacher_id)
        if teacher.user_type != 'Teacher':
            flash('Invalid teacher.', 'error')
            return redirect(url_for('admin_teachers'))

        # Delete all related records first
        try:
            # Delete leave requests where this teacher was the approver
            LeaveRequest.query.filter_by(teacher_id=teacher.id).delete()
            
            # Delete the teacher
            db.session.delete(teacher)
            db.session.commit()
            
            flash('Teacher deleted successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            print(f"Database error while deleting teacher: {str(e)}")
            flash('Error deleting teacher. Please try again.', 'error')
            return redirect(url_for('admin_teachers'))

    except Exception as e:
        print(f"Unexpected error while deleting teacher: {str(e)}")
        flash('An unexpected error occurred. Please try again.', 'error')
        return redirect(url_for('admin_teachers'))

    return redirect(url_for('admin_teachers'))

@app.route('/admin/teacher/edit/<int:teacher_id>', methods=['POST'])
def admin_edit_teacher(teacher_id):
    if 'user_id' not in session or session['user_type'] != 'Admin':
        return redirect(url_for('login'))

    teacher = User.query.get_or_404(teacher_id)
    if teacher.user_type != 'Teacher':
        flash('Invalid teacher.', 'error')
        return redirect(url_for('admin_teachers'))

    # Check if email is already taken by another user
    email = request.form.get('email')
    if email != teacher.email and User.query.filter_by(email=email).first():
        flash('Email already exists.', 'error')
        return redirect(url_for('admin_teachers'))

    try:
        teacher.name = request.form.get('name')
        teacher.email = email
        teacher.department = request.form.get('department')
        teacher.phone = request.form.get('phone')
        
        db.session.commit()
        flash('Teacher details updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error updating teacher details. Please try again.', 'error')

    return redirect(url_for('admin_teachers'))

@app.route('/admin/teacher/delete_by_email', methods=['POST'])
def delete_teacher_by_email():
    if 'user_id' not in session or session['user_type'] != 'Admin':
        return redirect(url_for('login'))

    email = request.form.get('email')
    if not email:
        flash('Email is required.', 'error')
        return redirect(url_for('admin_dashboard'))

    try:
        # Get the teacher
        teacher = User.query.filter_by(email=email, user_type='Teacher').first()
        if not teacher:
            flash('Teacher not found.', 'error')
            return redirect(url_for('admin_dashboard'))

        try:
            # Delete the teacher directly
            # The cascade delete will handle related records
            db.session.delete(teacher)
            db.session.commit()
            
            flash('Teacher deleted successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            print(f"Database error while deleting teacher: {str(e)}")
            print(f"Error type: {type(e)}")
            flash(f'Error deleting teacher: {str(e)}', 'error')
            return redirect(url_for('admin_dashboard'))

    except Exception as e:
        print(f"Unexpected error while deleting teacher: {str(e)}")
        print(f"Error type: {type(e)}")
        flash(f'An unexpected error occurred: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))

    return redirect(url_for('admin_dashboard'))

@app.route('/admin/teacher/check/<email>')
def check_teacher(email):
    if 'user_id' not in session or session['user_type'] != 'Admin':
        return redirect(url_for('login'))
    
    teacher = User.query.filter_by(email=email, user_type='Teacher').first()
    if teacher:
        return jsonify({
            'exists': True,
            'id': teacher.id,
            'name': teacher.name,
            'department': teacher.department
        })
    return jsonify({'exists': False})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000) 