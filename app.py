from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
from werkzeug.utils import secure_filename
import secrets
from flask_mail import Mail, Message
import re
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ваш_секретный_ключ_здесь'  # В продакшене используйте безопасный ключ
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/school_tournaments.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Настройка логирования
if not os.path.exists('logs'):
    os.mkdir('logs')
file_handler = RotatingFileHandler('logs/tournament_scheduler.log', maxBytes=10240, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('Tournament scheduler startup')

# Настройки для отправки email
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'mazaxak2@gmail.com'  # Замените на ваш email
app.config['MAIL_PASSWORD'] = 'qqwaijdvsxozzbys'     # Замените на пароль приложения

mail = Mail(app)
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Инициализация планировщика
scheduler = BackgroundScheduler()
scheduler.start()

def start_tournament_job(tournament_id):
    with app.app_context():
        tournament = Tournament.query.get(tournament_id)
        if tournament:
            tournament.status = 'started'
            db.session.commit()
            app.logger.info(f'Турнир {tournament.title} (ID: {tournament.id}) начался в {datetime.utcnow()}')

def end_tournament_job(tournament_id):
    with app.app_context():
        tournament = Tournament.query.get(tournament_id)
        if tournament:
            tournament.status = 'finished'
            tournament.is_active = False
            db.session.commit()
            app.logger.info(f'Турнир {tournament.title} (ID: {tournament.id}) завершен в {datetime.utcnow()}')

def add_scheduler_job(job_func, run_date, tournament_id, job_type):
    """Добавляет задачу в планировщик с логированием"""
    job_id = f'{job_type}_tournament_{tournament_id}'
    tournament = Tournament.query.get(tournament_id)
    
    try:
        scheduler.add_job(
            job_func,
            trigger=DateTrigger(run_date=run_date),
            args=[tournament_id],
            id=job_id
        )
        app.logger.info(
            f'Добавлена задача {job_type} для турнира "{tournament.title}" (ID: {tournament_id})\n'
            f'Время выполнения: {run_date}\n'
            f'Текущее время сервера: {datetime.utcnow()}'
        )
    except Exception as e:
        app.logger.error(
            f'Ошибка при добавлении задачи {job_type} для турнира "{tournament.title}" (ID: {tournament_id}): {str(e)}'
        )

def remove_scheduler_job(tournament_id, job_type):
    """Удаляет задачу из планировщика с логированием"""
    job_id = f'{job_type}_tournament_{tournament_id}'
    tournament = Tournament.query.get(tournament_id)
    
    try:
        scheduler.remove_job(job_id)
        app.logger.info(
            f'Удалена задача {job_type} для турнира "{tournament.title}" (ID: {tournament_id})\n'
            f'Текущее время сервера: {datetime.utcnow()}'
        )
    except Exception as e:
        app.logger.warning(
            f'Ошибка при удалении задачи {job_type} для турнира "{tournament.title}" (ID: {tournament_id}): {str(e)}'
        )

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=False)  # Для подтверждения email
    is_blocked = db.Column(db.Boolean, default=False)  # Для блокировки пользователя
    email_confirmation_token = db.Column(db.String(100), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    balance = db.Column(db.Integer, default=0)  # Общий счет
    tickets = db.Column(db.Integer, default=0)  # Количество билетов

    # Добавляем связь с турнирами через TournamentParticipation
    tournaments = db.relationship('Tournament', 
                                secondary='tournament_participation',
                                back_populates='participants',
                                lazy='dynamic',
                                overlaps="tournament_participations")
    
    # Добавляем связь с участиями в турнирах
    tournament_participations = db.relationship('TournamentParticipation',
                                             back_populates='user',
                                             overlaps="tournaments,participants")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_confirmation_token(self):
        token = secrets.token_urlsafe(32)
        self.email_confirmation_token = token
        db.session.commit()
        return token

class Tournament(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    rules = db.Column(db.Text, nullable=False)  # Добавляем поле для правил
    image = db.Column(db.String(200))
    start_date = db.Column(db.DateTime, nullable=False)
    duration = db.Column(db.Integer, nullable=False)  # в минутах
    is_active = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='pending')  # pending, started, finished
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Добавляем отношения
    participants = db.relationship('User',
                                 secondary='tournament_participation',
                                 back_populates='tournaments',
                                 lazy='dynamic',
                                 overlaps="tournament_participations")
    participations = db.relationship('TournamentParticipation',
                                   back_populates='tournament',
                                   overlaps="participants,tournaments")

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(200))
    points = db.Column(db.Integer, nullable=False)
    correct_answer = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tournament = db.relationship('Tournament', backref=db.backref('tasks', lazy=True))

class TicketPurchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    purchase_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('ticket_purchases', lazy=True))

class TournamentParticipation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    score = db.Column(db.Integer, default=0)
    place = db.Column(db.Integer)
    participation_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', 
                         back_populates='tournament_participations',
                         overlaps="tournaments,participants")
    tournament = db.relationship('Tournament', 
                               back_populates='participations',
                               overlaps="participants,tournaments")

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def create_admin_user():
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(
            username='admin',
            email='admin@school-tournaments.ru',
            is_admin=True,
            is_active=True  # Устанавливаем is_active=True для администратора
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print("Администратор успешно создан")

def send_confirmation_email(user):
    token = user.generate_confirmation_token()
    msg = Message('Подтверждение регистрации',
                  sender=app.config['MAIL_USERNAME'],
                  recipients=[user.email])
    msg.body = f'''Для подтверждения вашей регистрации перейдите по следующей ссылке:
{url_for('confirm_email', token=token, _external=True)}

Если вы не регистрировались на нашем сайте, просто проигнорируйте это письмо.
'''
    mail.send(msg)

def send_credentials_email(user, password):
    msg = Message('Ваши учетные данные',
                  sender=app.config['MAIL_USERNAME'],
                  recipients=[user.email])
    msg.body = f'''Ваш аккаунт успешно подтвержден!

Ваши учетные данные:
Логин: {user.username}
Пароль: {password}

Рекомендуем сменить пароль после первого входа в систему.
'''
    mail.send(msg)

@app.route('/')
def home():
    # Получаем текущее время
    current_time = datetime.utcnow()
    
    # Сначала ищем будущие турниры
    next_tournament = Tournament.query.filter(
        Tournament.start_date > current_time,
        Tournament.is_active == True
    ).order_by(Tournament.start_date.asc()).first()
    
    # Если нет будущих турниров, ищем текущий активный турнир
    if not next_tournament:
        # Получаем все активные турниры, которые уже начались
        active_tournaments = Tournament.query.filter(
            Tournament.start_date <= current_time,
            Tournament.is_active == True
        ).all()
        
        # Находим турнир, который еще не закончился
        for tournament in active_tournaments:
            end_time = tournament.start_date + timedelta(minutes=tournament.duration)
            if end_time > current_time:
                next_tournament = tournament
                break
    
    return render_template('index.html', 
                         title='Главная страница',
                         next_tournament=next_tournament,
                         now=current_time)

@app.route('/about')
def about():
    return render_template('about.html', title='О нас')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        # Ищем пользователя без учета регистра
        user = User.query.filter(User.username.ilike(username)).first()
        
        if user and user.check_password(password):
            if user.is_blocked:
                flash('Ваш аккаунт заблокирован администратором. Для разблокировки обратитесь к администратору по email: admin@school-tournaments.ru', 'danger')
                return redirect(url_for('login'))
            if not user.is_active:
                flash('Пожалуйста, подтвердите ваш email перед входом', 'warning')
                return redirect(url_for('login'))
            login_user(user)
            return redirect(url_for('home'))
        else:
            flash('Неверный логин или пароль', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('Недостаточно прав', 'error')
        return redirect(url_for('home'))
    
    users_count = User.query.count()
    return render_template('admin/dashboard.html', 
                         title='Панель администратора',
                         users_count=users_count)

@app.route('/admin/users')
@login_required
def admin_users():
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/users/add', methods=['POST'])
@login_required
def admin_add_user():
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    is_admin = 'is_admin' in request.form
    
    if User.query.filter_by(username=username).first():
        flash('Пользователь с таким логином уже существует', 'danger')
        return redirect(url_for('admin_users'))
    
    if User.query.filter_by(email=email).first():
        flash('Пользователь с таким email уже существует', 'danger')
        return redirect(url_for('admin_users'))
    
    user = User(username=username, email=email, is_admin=is_admin, is_active=True)
    user.set_password(password)
    
    db.session.add(user)
    db.session.commit()
    
    flash('Пользователь успешно добавлен', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/<int:user_id>/edit', methods=['POST'])
@login_required
def admin_edit_user(user_id):
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    user = User.query.get_or_404(user_id)
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    is_admin = 'is_admin' in request.form
    tickets = request.form.get('tickets')
    
    if username != user.username and User.query.filter_by(username=username).first():
        flash('Пользователь с таким логином уже существует', 'danger')
        return redirect(url_for('admin_users'))
    
    if email != user.email and User.query.filter_by(email=email).first():
        flash('Пользователь с таким email уже существует', 'danger')
        return redirect(url_for('admin_users'))
    
    try:
        tickets = int(tickets)
        if tickets < 0:
            raise ValueError
    except ValueError:
        flash('Количество билетов должно быть неотрицательным числом', 'danger')
        return redirect(url_for('admin_users'))
    
    user.username = username
    user.email = email
    user.is_admin = is_admin
    user.tickets = tickets
    
    if password:
        user.set_password(password)
    
    db.session.commit()
    
    flash('Пользователь успешно обновлен', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    user = User.query.get_or_404(user_id)
    
    if user.id == current_user.id:
        flash('Вы не можете удалить свой аккаунт', 'danger')
        return redirect(url_for('admin_users'))
    
    db.session.delete(user)
    db.session.commit()
    
    flash('Пользователь успешно удален', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/<int:user_id>/toggle-block', methods=['POST'])
@login_required
def admin_toggle_user_block(user_id):
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    user = User.query.get_or_404(user_id)
    
    if user.id == current_user.id:
        flash('Вы не можете заблокировать свой аккаунт', 'danger')
        return redirect(url_for('admin_users'))
    
    user.is_blocked = not user.is_blocked
    db.session.commit()
    
    action = "заблокирован" if user.is_blocked else "разблокирован"
    flash(f'Пользователь {user.username} успешно {action}', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/tournaments')
@login_required
def admin_tournaments():
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    tournaments = Tournament.query.order_by(Tournament.start_date.desc()).all()
    return render_template('admin/tournaments.html', title='Управление турнирами', tournaments=tournaments)

@app.route('/admin/tournaments/add', methods=['POST'])
@login_required
def admin_add_tournament():
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    title = request.form.get('title')
    description = request.form.get('description')
    rules = request.form.get('rules')  # Получаем правила из формы
    start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%dT%H:%M')
    duration = int(request.form.get('duration'))
    
    # Обработка изображения
    image = request.files.get('image')
    image_filename = None
    if image and image.filename:
        image_filename = secure_filename(image.filename)
        image_path = os.path.join(app.static_folder, 'uploads', image_filename)
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        image.save(image_path)
    
    tournament = Tournament(
        title=title,
        description=description,
        rules=rules,  # Добавляем правила в создание турнира
        image=image_filename,
        start_date=start_date,
        duration=duration
    )
    
    db.session.add(tournament)
    db.session.commit()
    
    flash('Турнир успешно добавлен', 'success')
    return redirect(url_for('admin_tournaments'))

@app.route('/admin/tournaments/<int:tournament_id>/edit', methods=['POST'])
@login_required
def admin_edit_tournament(tournament_id):
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    tournament = Tournament.query.get_or_404(tournament_id)
    
    tournament.title = request.form.get('title')
    tournament.description = request.form.get('description')
    tournament.rules = request.form.get('rules')  # Обновляем правила
    tournament.start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%dT%H:%M')
    tournament.duration = int(request.form.get('duration'))
    
    # Обработка изображения
    image = request.files.get('image')
    if image and image.filename:
        # Удаляем старое изображение
        if tournament.image:
            old_image_path = os.path.join(app.static_folder, 'uploads', tournament.image)
            if os.path.exists(old_image_path):
                os.remove(old_image_path)
        
        # Сохраняем новое изображение
        image_filename = secure_filename(image.filename)
        image_path = os.path.join(app.static_folder, 'uploads', image_filename)
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        image.save(image_path)
        tournament.image = image_filename
    
    db.session.commit()
    
    flash('Турнир успешно обновлен', 'success')
    return redirect(url_for('admin_tournaments'))

@app.route('/admin/tournaments/<int:tournament_id>/activate', methods=['POST'])
@login_required
def admin_activate_tournament(tournament_id):
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Проверяем, не активирован ли уже турнир
    if tournament.is_active:
        flash('Турнир уже активирован', 'warning')
        return redirect(url_for('admin_tournaments'))
    
    # Проверяем, не начался ли уже турнир
    if tournament.start_date <= datetime.utcnow():
        flash('Нельзя активировать турнир, который уже должен был начаться', 'danger')
        return redirect(url_for('admin_tournaments'))
    
    # Активируем турнир
    tournament.is_active = True
    db.session.commit()
    
    # Создаем задачи в планировщике
    add_scheduler_job(start_tournament_job, tournament.start_date, tournament.id, 'start')
    end_time = tournament.start_date + timedelta(minutes=tournament.duration)
    add_scheduler_job(end_tournament_job, end_time, tournament.id, 'end')
    
    flash('Турнир успешно активирован', 'success')
    return redirect(url_for('admin_tournaments'))

@app.route('/admin/tournaments/<int:tournament_id>/deactivate', methods=['POST'])
@login_required
def admin_deactivate_tournament(tournament_id):
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Удаляем задачи из планировщика
    remove_scheduler_job(tournament.id, 'start')
    remove_scheduler_job(tournament.id, 'end')
    
    tournament.is_active = False
    db.session.commit()
    
    flash('Турнир успешно деактивирован', 'success')
    return redirect(url_for('admin_tournaments'))

@app.route('/admin/tournaments/<int:tournament_id>/delete', methods=['POST'])
@login_required
def admin_delete_tournament(tournament_id):
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Удаляем изображение
    if tournament.image:
        image_path = os.path.join(app.static_folder, 'uploads', tournament.image)
        if os.path.exists(image_path):
            os.remove(image_path)
    
    db.session.delete(tournament)
    db.session.commit()
    
    flash('Турнир успешно удален', 'success')
    return redirect(url_for('admin_tournaments'))

@app.route('/admin/tournaments/<int:tournament_id>/stats')
@login_required
def admin_tournament_stats(tournament_id):
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    tournament = Tournament.query.get_or_404(tournament_id)
    # TODO: Добавить статистику турнира
    return render_template('admin/tournament_stats.html', title='Статистика турнира', tournament=tournament)

@app.route('/admin/shop')
@login_required
def admin_shop():
    if not current_user.is_admin:
        flash('Недостаточно прав', 'error')
        return redirect(url_for('home'))
    return render_template('admin/shop.html', title='Управление магазином')

@app.route('/admin/tournaments/<int:tournament_id>/configure')
@login_required
def configure_tournament(tournament_id):
    if not current_user.is_admin:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('home'))
    
    tournament = Tournament.query.get_or_404(tournament_id)
    return render_template('admin/configure_tournament.html', tournament=tournament)

@app.route('/admin/tournaments/<int:tournament_id>/tasks/add', methods=['POST'])
@login_required
def add_tournament_task(tournament_id):
    if not current_user.is_admin:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('home'))
    
    tournament = Tournament.query.get_or_404(tournament_id)
    
    title = request.form.get('title')
    description = request.form.get('description')
    points = request.form.get('points')
    correct_answer = request.form.get('correct_answer')
    
    if not all([title, description, points, correct_answer]):
        flash('Все поля должны быть заполнены', 'danger')
        return redirect(url_for('configure_tournament', tournament_id=tournament_id))
    
    try:
        points = int(points)
        if points < 1:
            raise ValueError
    except ValueError:
        flash('Количество баллов должно быть положительным числом', 'danger')
        return redirect(url_for('configure_tournament', tournament_id=tournament_id))
    
    # Обработка изображения
    image = request.files.get('image')
    image_filename = None
    if image and image.filename:
        image_filename = secure_filename(image.filename)
        image_path = os.path.join(app.static_folder, 'uploads', 'tasks', image_filename)
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        image.save(image_path)
    
    task = Task(
        tournament_id=tournament_id,
        title=title,
        description=description,
        image=image_filename,
        points=points,
        correct_answer=correct_answer
    )
    
    db.session.add(task)
    db.session.commit()
    
    flash('Задача успешно добавлена', 'success')
    return redirect(url_for('configure_tournament', tournament_id=tournament_id))

@app.route('/admin/tournaments/<int:tournament_id>/tasks/<int:task_id>/edit', methods=['POST'])
@login_required
def edit_tournament_task(tournament_id, task_id):
    if not current_user.is_admin:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('home'))
    
    tournament = Tournament.query.get_or_404(tournament_id)
    task = Task.query.get_or_404(task_id)
    
    if task.tournament_id != tournament_id:
        flash('Задача не принадлежит указанному турниру', 'danger')
        return redirect(url_for('configure_tournament', tournament_id=tournament_id))
    
    title = request.form.get('title')
    description = request.form.get('description')
    points = request.form.get('points')
    correct_answer = request.form.get('correct_answer')
    
    if not all([title, description, points, correct_answer]):
        flash('Все поля должны быть заполнены', 'danger')
        return redirect(url_for('configure_tournament', tournament_id=tournament_id))
    
    try:
        points = int(points)
        if points < 1:
            raise ValueError
    except ValueError:
        flash('Количество баллов должно быть положительным числом', 'danger')
        return redirect(url_for('configure_tournament', tournament_id=tournament_id))
    
    # Обработка изображения
    image = request.files.get('image')
    if image and image.filename:
        # Удаляем старое изображение
        if task.image:
            old_image_path = os.path.join(app.static_folder, 'uploads', 'tasks', task.image)
            if os.path.exists(old_image_path):
                os.remove(old_image_path)
        
        # Сохраняем новое изображение
        image_filename = secure_filename(image.filename)
        image_path = os.path.join(app.static_folder, 'uploads', 'tasks', image_filename)
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        image.save(image_path)
        task.image = image_filename
    
    task.title = title
    task.description = description
    task.points = points
    task.correct_answer = correct_answer
    
    db.session.commit()
    
    flash('Задача успешно обновлена', 'success')
    return redirect(url_for('configure_tournament', tournament_id=tournament_id))

@app.route('/admin/tournaments/<int:tournament_id>/tasks/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_tournament_task(tournament_id, task_id):
    if not current_user.is_admin:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('home'))
    
    tournament = Tournament.query.get_or_404(tournament_id)
    task = Task.query.get_or_404(task_id)
    
    if task.tournament_id != tournament_id:
        flash('Задача не принадлежит указанному турниру', 'danger')
        return redirect(url_for('configure_tournament', tournament_id=tournament_id))
    
    # Удаляем изображение
    if task.image:
        image_path = os.path.join(app.static_folder, 'uploads', 'tasks', task.image)
        if os.path.exists(image_path):
            os.remove(image_path)
    
    db.session.delete(task)
    db.session.commit()
    
    flash('Задача успешно удалена', 'success')
    return redirect(url_for('configure_tournament', tournament_id=tournament_id))

def is_password_strong(password):
    # Проверяем длину пароля (минимум 8 символов)
    if len(password) < 8:
        return False
    
    # Проверяем наличие цифр
    if not re.search(r"\d", password):
        return False
    
    # Проверяем наличие букв
    if not re.search(r"[a-zA-Z]", password):
        return False
    
    return True

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if not is_password_strong(password):
            flash('Пароль должен содержать минимум 8 символов, включая цифры и буквы', 'danger')
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Пароли не совпадают', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash('Пользователь с таким логином уже существует', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('Пользователь с таким email уже существует', 'danger')
            return redirect(url_for('register'))

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        # Добавляем пароль в URL для подтверждения
        token = user.generate_confirmation_token()
        confirm_url = url_for('confirm_email', token=token, password=password, _external=True)
        
        msg = Message('Подтверждение регистрации',
                      sender=app.config['MAIL_USERNAME'],
                      recipients=[user.email])
        msg.body = f'''Для подтверждения вашей регистрации перейдите по следующей ссылке:
{confirm_url}

Если вы не регистрировались на нашем сайте, просто проигнорируйте это письмо.
'''
        mail.send(msg)
        
        flash('Письмо с подтверждением отправлено на ваш email', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/confirm/<token>')
def confirm_email(token):
    user = User.query.filter_by(email_confirmation_token=token).first()
    if user:
        user.is_active = True
        user.email_confirmation_token = None
        db.session.commit()
        
        # Отправляем письмо с учетными данными
        # Получаем пароль из формы регистрации
        password = request.args.get('password')
        if password:
            send_credentials_email(user, password)
        
        flash('Email успешно подтвержден! Теперь вы можете войти.', 'success')
    else:
        flash('Недействительная или устаревшая ссылка подтверждения.', 'danger')
    return redirect(url_for('login'))

def get_user_rank(user_id):
    # Получаем всех пользователей, отсортированных по балансу (по убыванию)
    users = User.query.filter(User.is_admin == False).order_by(User.balance.desc()).all()
    # Находим индекс пользователя в отсортированном списке
    for index, user in enumerate(users, 1):
        if user.id == user_id:
            return index
    return None

@app.route('/profile')
@login_required
def profile():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    
    # Получаем текущее время
    current_time = datetime.utcnow()
    
    # Сначала ищем будущие турниры
    next_tournament = Tournament.query.filter(
        Tournament.start_date > current_time,
        Tournament.is_active == True
    ).order_by(Tournament.start_date.asc()).first()
    
    # Если нет будущих турниров, ищем текущий активный турнир
    if not next_tournament:
        # Получаем все активные турниры, которые уже начались
        active_tournaments = Tournament.query.filter(
            Tournament.start_date <= current_time,
            Tournament.is_active == True
        ).all()
        
        # Находим турнир, который еще не закончился
        for tournament in active_tournaments:
            end_time = tournament.start_date + timedelta(minutes=tournament.duration)
            if end_time > current_time:
                next_tournament = tournament
                break
    
    user_rank = get_user_rank(current_user.id)
    return render_template('profile.html', 
                         title='Личный кабинет', 
                         user_rank=user_rank,
                         next_tournament=next_tournament,
                         now=current_time)

@app.route('/buy-tickets')
@login_required
def buy_tickets():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    return render_template('buy_tickets.html', title='Покупка билетов')

@app.route('/purchase-history')
@login_required
def purchase_history():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    return render_template('purchase_history.html', title='История покупок')

@app.route('/completed-tournaments')
@login_required
def completed_tournaments():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    return render_template('completed_tournaments.html', title='Пройденные турниры')

@app.route('/tournament/<int:tournament_id>/join')
@login_required
def join_tournament(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    # Используем локальное время вместо UTC
    current_time = datetime.now()
    
    print(f"Tournament start time: {tournament.start_date}")
    print(f"Current time (local): {current_time}")
    print(f"Tournament duration: {tournament.duration} minutes")
    
    # Проверяем, не является ли пользователь администратором
    if current_user.is_admin:
        print("User is admin, redirecting to home")
        flash('Администраторы не могут участвовать в турнирах', 'warning')
        return redirect(url_for('home'))
    
    # Проверяем, есть ли у пользователя билет
    if current_user.tickets < 1:
        print("User has no tickets, redirecting to profile")
        flash('У вас недостаточно билетов для участия в турнире', 'warning')
        return redirect(url_for('profile'))
    
    # Проверяем, начался ли турнир
    if tournament.start_date <= current_time:
        # Проверяем, не закончился ли турнир
        end_time = tournament.start_date + timedelta(minutes=tournament.duration)
        print(f"Tournament end time: {end_time}")
        if end_time > current_time:
            print("Tournament is active, redirecting to menu")
            # Если турнир идет, перенаправляем в меню турнира
            return redirect(url_for('tournament_menu', tournament_id=tournament.id))
        else:
            print("Tournament has ended, redirecting to home")
            flash('Турнир уже закончился', 'warning')
            return redirect(url_for('home'))
    else:
        print("Tournament hasn't started yet, redirecting to home")
        # Показываем время начала турнира в локальном времени
        local_start_time = tournament.start_date.strftime('%H:%M')
        flash(f'Турнир начнется в {local_start_time}', 'warning')
        return redirect(url_for('home'))

@app.route('/tournament/<int:tournament_id>/menu')
@login_required
def tournament_menu(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Проверяем, не является ли пользователь администратором
    if current_user.is_admin:
        flash('Администраторы не могут участвовать в турнирах', 'warning')
        return redirect(url_for('home'))
    
    # Проверяем, начался ли турнир
    current_time = datetime.now()
    if tournament.start_date > current_time:
        flash('Турнир еще не начался', 'warning')
        return redirect(url_for('home'))
    
    # Проверяем, не закончился ли турнир
    end_time = tournament.start_date + timedelta(minutes=tournament.duration)
    if end_time <= current_time:
        flash('Турнир уже закончился', 'warning')
        return redirect(url_for('home'))
    
    # Проверяем, есть ли у пользователя билет
    if current_user.tickets < 1:
        flash('У вас недостаточно билетов для участия в турнире', 'warning')
        return redirect(url_for('profile'))
    
    return render_template('tournament_menu.html', tournament=tournament)

@app.route('/tournament/<int:tournament_id>/start')
@login_required
def start_tournament(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Проверяем, есть ли у пользователя билет
    if current_user.tickets < 1:
        flash('У вас недостаточно билетов для участия в турнире', 'warning')
        return redirect(url_for('profile'))
    
    # Проверяем, не является ли пользователь администратором
    if current_user.is_admin:
        flash('Администраторы не могут участвовать в турнирах', 'warning')
        return redirect(url_for('home'))
    
    # Здесь будет логика начала турнира
    # Пока просто перенаправляем на страницу турнира
    return redirect(url_for('tournament', tournament_id=tournament.id))

@app.route('/admin/users/<int:user_id>/details')
@login_required
def admin_user_details(user_id):
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    user = User.query.get_or_404(user_id)
    
    # Получаем статистику
    total_tickets_purchased = sum(purchase.quantity for purchase in user.ticket_purchases)
    total_tournaments_participated = len(user.tournament_participations)
    total_tournaments_won = sum(1 for p in user.tournament_participations if p.place == 1)
    average_tournament_score = sum(p.score for p in user.tournament_participations) / total_tournaments_participated if total_tournaments_participated > 0 else 0
    
    # Получаем историю покупок и участия в турнирах
    ticket_purchases = TicketPurchase.query.filter_by(user_id=user.id).order_by(TicketPurchase.purchase_date.desc()).all()
    tournament_participations = TournamentParticipation.query.filter_by(user_id=user.id).order_by(TournamentParticipation.participation_date.desc()).all()
    
    return render_template('admin/user_details.html',
                         user=user,
                         total_tickets_purchased=total_tickets_purchased,
                         total_tournaments_participated=total_tournaments_participated,
                         total_tournaments_won=total_tournaments_won,
                         average_tournament_score=round(average_tournament_score, 2),
                         ticket_purchases=ticket_purchases,
                         tournament_participations=tournament_participations)

def update_tournament_status():
    now = datetime.utcnow()
    tournaments = Tournament.query.filter(Tournament.status != 'finished').all()
    
    for tournament in tournaments:
        if tournament.start_date <= now and now <= tournament.start_date + timedelta(minutes=tournament.duration):
            tournament.status = 'started'
        elif now > tournament.start_date + timedelta(minutes=tournament.duration):
            tournament.status = 'finished'
    
    db.session.commit()

@app.before_request
def before_request():
    update_tournament_status()

def restore_scheduler_jobs():
    """Восстанавливает задачи планировщика для активных турниров при запуске приложения"""
    active_tournaments = Tournament.query.filter_by(is_active=True).all()
    now = datetime.utcnow()
    
    app.logger.info(f'Начало восстановления задач планировщика. Текущее время: {now}')
    
    for tournament in active_tournaments:
        app.logger.info(f'Обработка турнира "{tournament.title}" (ID: {tournament.id})')
        
        # Если турнир еще не начался
        if tournament.start_date > now:
            add_scheduler_job(start_tournament_job, tournament.start_date, tournament.id, 'start')
            end_time = tournament.start_date + timedelta(minutes=tournament.duration)
            add_scheduler_job(end_tournament_job, end_time, tournament.id, 'end')
            
        # Если турнир уже идет
        elif tournament.start_date <= now and now <= tournament.start_date + timedelta(minutes=tournament.duration):
            tournament.status = 'started'
            end_time = tournament.start_date + timedelta(minutes=tournament.duration)
            add_scheduler_job(end_tournament_job, end_time, tournament.id, 'end')
            app.logger.info(f'Турнир "{tournament.title}" (ID: {tournament.id}) уже идет')
            
        # Если турнир уже должен был закончиться
        else:
            tournament.status = 'finished'
            tournament.is_active = False
            app.logger.info(f'Турнир "{tournament.title}" (ID: {tournament.id}) уже должен был закончиться')
    
    db.session.commit()
    app.logger.info('Восстановление задач планировщика завершено')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_admin_user()
        restore_scheduler_jobs()  # Восстанавливаем задачи планировщика
    app.run(debug=True) 