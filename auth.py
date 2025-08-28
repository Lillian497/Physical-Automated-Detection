from flask import Blueprint, render_template_string, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, Length
from models import User
from app import db

auth_bp = Blueprint('auth', __name__, url_prefix='')

# --- 表單 ---
class RegisterForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    submit = SubmitField('Register')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

# --- 白名單工具 ---
def is_email_allowed(email: str) -> bool:
    email = email.strip().lower()
    allowed_emails = current_app.config.get('WHITELIST_EMAILS', set())
    allowed_domains = current_app.config.get('WHITELIST_DOMAINS', set())

    if email in allowed_emails:
        return True
    # 網域白名單：example.edu
    if '@' in email and allowed_domains:
        domain = email.split('@', 1)[1]
        if domain in allowed_domains:
            return True
    return False

# --- 註冊 ---
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()

        # 白名單檢查（註冊時強制）
        if not is_email_allowed(email):
            flash('註冊失敗：此 Email 不在白名單中。', 'danger')
            return redirect(url_for('auth.register'))

        if User.query.filter_by(email=email).first():
            flash('此 Email 已被註冊，請改用登入。', 'warning')
            return redirect(url_for('auth.login'))

        user = User(email=email)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('註冊成功，請登入。', 'success')
        return redirect(url_for('auth.login'))

    # 簡易模板（你也可以改用獨立 HTML 檔）
    return render_template_string('''
    <h2>Register</h2>
    <form method="post">
      {{ form.csrf_token }}
      {{ form.email.label }} {{ form.email(size=40) }}<br>
      {{ form.password.label }} {{ form.password(size=40) }}<br><br>
      {{ form.submit() }}
    </form>
    <p><a href="{{ url_for('auth.login') }}">Go to Login</a></p>
    ''' , form=form)

# --- 登入 ---
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()

        if not user or not user.check_password(form.password.data):
            flash('登入失敗：帳號或密碼錯誤。', 'danger')
            return redirect(url_for('auth.login'))

        # （可選）登入時也強制白名單檢查（避免先前已註冊但後來被移出白名單）
        enforce = current_app.config.get('ENFORCE_WHITELIST_ON_LOGIN', True)
        if enforce and (not user.is_admin) and (not is_email_allowed(email)):
            flash('登入失敗：此 Email 已不在白名單中。', 'danger')
            return redirect(url_for('auth.login'))

        login_user(user)
        flash('登入成功。', 'success')
        return redirect(url_for('auth.dashboard'))

    return render_template_string('''
    <h2>Login</h2>
    <form method="post">
      {{ form.csrf_token }}
      {{ form.email.label }} {{ form.email(size=40) }}<br>
      {{ form.password.label }} {{ form.password(size=40) }}<br><br>
      {{ form.submit() }}
    </form>
    <p><a href="{{ url_for('auth.register') }}">Go to Register</a></p>
    ''', form=form)

# --- 登出 ---
@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('你已登出。', 'info')
    return redirect(url_for('auth.login'))

# --- 範例保護頁 ---
@auth_bp.route('/dashboard')
@login_required
def dashboard():
    return render_template_string('''
    <h2>Dashboard</h2>
    <p>Welcome, {{ current_user.email }}!</p>
    <p><a href="{{ url_for('auth.logout') }}">Logout</a></p>
    ''')
