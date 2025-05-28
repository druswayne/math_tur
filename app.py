from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from sqlalchemy.testing import fails
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
from werkzeug.utils import secure_filename
import secrets
from flask_mail import Mail, Message
import re
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
import random
from flask import session
from sqlalchemy import func
from sqlalchemy import case
from email_sender import add_to_queue, start_email_worker

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(32).hex()  # Генерируем криптографически стойкий ключ
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/school_tournaments.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_PERMANENT'] = False  # Сессия не будет постоянной
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)  # Максимальное время жизни сессии

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
scheduler = BackgroundScheduler(timezone='Europe/Moscow')
scheduler.start()

# Запускаем обработчик очереди писем
start_email_worker()

def start_tournament_job(tournament_id):
    try:
        with app.app_context():
            tournament = Tournament.query.get(tournament_id)
            if tournament:
                tournament.status = 'started'
                db.session.commit()
    except Exception as e:
        pass

def update_global_ranks():
    """Обновляет места пользователей в общей таблице на основе их баланса"""
    try:
        # Получаем всех пользователей, отсортированных по балансу (по убыванию)
        users = User.query.filter_by(is_admin=False).order_by(User.balance.desc()).all()
        
        # Обновляем места
        for rank, user in enumerate(users, 1):
            user.global_rank = rank
        
        db.session.commit()
    except Exception as e:
        db.session.rollback()

def end_tournament_job(tournament_id):
    try:
        with app.app_context():
            tournament = Tournament.query.get(tournament_id)
            if tournament:
                tournament.status = 'finished'
                tournament.is_active = False
                
                # Обновляем места участников в турнире
                participations = TournamentParticipation.query.filter_by(tournament_id=tournament_id).order_by(TournamentParticipation.score.desc()).all()
                
                current_time = datetime.utcnow() + timedelta(hours=3)
                
                for rank, participation in enumerate(participations, 1):
                    participation.place = rank

                
                # Обновляем рейтинги в категориях
                update_category_ranks()
                
                db.session.commit()
    except Exception as e:
        db.session.rollback()

def add_scheduler_job(job_func, run_date, tournament_id, job_type):
    """Добавляет задачу в планировщик"""
    job_id = f'{job_type}_tournament_{tournament_id}'
    tournament = Tournament.query.get(tournament_id)
    
    try:
        scheduler.add_job(
            job_func,
            trigger=DateTrigger(run_date=run_date),
            args=[tournament_id],
            id=job_id,
            replace_existing=True
        )
    except Exception as e:
        pass

def remove_scheduler_job(tournament_id, job_type):
    """Удаляет задачу из планировщика"""
    job_id = f'{job_type}_tournament_{tournament_id}'
    tournament = Tournament.query.get(tournament_id)
    
    try:
        scheduler.remove_job(job_id)
    except Exception as e:
        pass

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    parent_name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(10), nullable=False)
    password_hash = db.Column(db.String(128))
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=False)  # Для подтверждения email
    is_blocked = db.Column(db.Boolean, default=False)  # Для блокировки пользователя
    block_reason = db.Column(db.Text, nullable=True)  # Причина блокировки
    email_confirmation_token = db.Column(db.String(100), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    last_activity = db.Column(db.DateTime, nullable=True)  # Время последней активности
    balance = db.Column(db.Integer, default=0)  # Общий счет
    tickets = db.Column(db.Integer, default=0)  # Количество билетов
    tournaments_count = db.Column(db.Integer, default=0)  # Количество турниров, в которых участвовал пользователь
    session_token = db.Column(db.String(100), unique=True)  # Токен текущей сессии
    category_rank = db.Column(db.Integer, default=0)  # Место в рейтинге категории
    temp_password = db.Column(db.String(128), nullable=True)  # Временное хранение пароля до подтверждения email
    total_tournament_time = db.Column(db.Integer, default=0)  # Общее время в турнирах в секундах

    # Добавляем связь с турнирами через TournamentParticipation
    tournaments = db.relationship('Tournament', 
                                secondary='tournament_participation',
                                back_populates='participants',
                                lazy='dynamic',
                                overlaps="tournament_participations")
    
    # Добавляем связь с участиями в турнирах
    tournament_participations = db.relationship('TournamentParticipation',
                                             back_populates='user',
                                             cascade='all, delete-orphan',
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
    category = db.Column(db.String(10), nullable=False)  # Добавляем поле для категории
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tournament = db.relationship('Tournament', backref=db.backref('tasks', lazy=True))

class TicketPurchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    discount = db.Column(db.Integer, default=0)  # Скидка в процентах
    purchase_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('ticket_purchases', lazy=True))

class TournamentParticipation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id', ondelete='CASCADE'), nullable=False)
    score = db.Column(db.Integer, default=0)
    place = db.Column(db.Integer)
    participation_date = db.Column(db.DateTime, default=datetime.utcnow)
    start_time = db.Column(db.DateTime, default=datetime.utcnow)  # Время начала участия в турнире
    
    user = db.relationship('User', 
                         back_populates='tournament_participations',
                         overlaps="tournaments,participants")
    tournament = db.relationship('Tournament', 
                               back_populates='participations',
                               overlaps="participants,tournaments")

class SolvedTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id', ondelete='CASCADE'), nullable=False)
    solved_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_correct = db.Column(db.Boolean, default=False)
    
    user = db.relationship('User', backref=db.backref('solved_tasks', lazy=True, cascade='all, delete-orphan'))
    task = db.relationship('Task', backref=db.backref('solutions', lazy=True, cascade='all, delete-orphan'))

class TicketPackage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    price = db.Column(db.Float, nullable=False)  # Базовая цена за 1 билет
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class TicketDiscount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    min_quantity = db.Column(db.Integer, nullable=False)  # Минимальное количество билетов для скидки
    discount = db.Column(db.Integer, nullable=False)  # Скидка в процентах
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def get_discount_for_quantity(quantity):
        """Получает максимальную доступную скидку для указанного количества билетов"""
        discount = TicketDiscount.query.filter(
            TicketDiscount.min_quantity <= quantity,
            TicketDiscount.is_active == True
        ).order_by(TicketDiscount.discount.desc()).first()
        return discount.discount if discount else 0

class Prize(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(200))  # Путь к изображению
    points_cost = db.Column(db.Integer, nullable=False)  # Стоимость в баллах
    quantity = db.Column(db.Integer, default=0)  # 0 означает неограниченное количество
    is_active = db.Column(db.Boolean, default=True)
    is_unique = db.Column(db.Boolean, default=False)  # Флаг уникального приза
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PrizePurchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    prize_id = db.Column(db.Integer, db.ForeignKey('prize.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    points_cost = db.Column(db.Integer, nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    address = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('prize_purchases', lazy=True))
    prize = db.relationship('Prize', backref=db.backref('purchases', lazy=True))

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    prize_id = db.Column(db.Integer, db.ForeignKey('prize.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('cart_items', lazy=True))
    prize = db.relationship('Prize', backref=db.backref('cart_items', lazy=True))

class ShopSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_open = db.Column(db.Boolean, default=True)
    # Процент лучших пользователей для каждой категории
    top_users_percentage_1_2 = db.Column(db.Integer, default=100)  # 1-2 классы
    top_users_percentage_3_4 = db.Column(db.Integer, default=100)  # 3-4 классы
    top_users_percentage_5_6 = db.Column(db.Integer, default=100)  # 5-6 классы
    top_users_percentage_7_8 = db.Column(db.Integer, default=100)  # 7-8 классы
    top_users_percentage_9 = db.Column(db.Integer, default=100)    # 9 класс
    top_users_percentage_10_11 = db.Column(db.Integer, default=100)  # 10-11 классы
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get_settings():
        settings = ShopSettings.query.first()
        if not settings:
            settings = ShopSettings()
            db.session.add(settings)
            db.session.commit()
        return settings

    def can_user_shop(self, user):
        if not self.is_open:
            return False
        
        # Получаем процент для категории пользователя
        category_percentage = getattr(self, f'top_users_percentage_{user.category.replace("-", "_")}')
        
        if category_percentage >= 100:
            return True
            
        # Получаем количество пользователей в категории пользователя
        category_users = User.query.filter_by(category=user.category, is_admin=False).count()
        if category_users == 0:
            return False
            
        # Вычисляем количество пользователей в категории, которым разрешено делать покупки
        allowed_users_count = max(1, int(category_users * category_percentage / 100))
        
        # Получаем ранг пользователя в его категории
        user_rank = user.category_rank
        if not user_rank:
            return False
            
        return user_rank <= allowed_users_count

class TournamentSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_season_active = db.Column(db.Boolean, default=True)
    closed_season_message = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def get_settings():
        settings = TournamentSettings.query.first()
        if not settings:
            settings = TournamentSettings()
            db.session.add(settings)
            db.session.commit()
        return settings

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def create_admin_user():
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(
            username='admin',
            email='admin@school-tournaments.ru',
            phone='+375000000000',  # Добавляем номер телефона
            parent_name='Администратор',  # Добавляем имя представителя
            category='10-11',  # Добавляем категорию
            is_admin=True,
            is_active=True  # Устанавливаем is_active=True для администратора
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

def send_confirmation_email(user):
    token = user.generate_confirmation_token()
    msg = Message('Подтверждение регистрации',
                  sender=app.config['MAIL_USERNAME'],
                  recipients=[user.email])
    msg.body = f'''Для подтверждения вашей регистрации перейдите по следующей ссылке:
{url_for('confirm_email', token=token, _external=True)}

Если вы не регистрировались на нашем сайте, просто проигнорируйте это письмо.
'''
    add_to_queue(app, mail, msg)

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
    add_to_queue(app, mail, msg)

@app.route('/')
def home():
    settings = TournamentSettings.get_settings()
    if settings.is_season_active:
        # Получаем текущее время
        current_time = datetime.utcnow() + timedelta(hours=3)
        
        # Сначала ищем текущий активный турнир
        active_tournaments = Tournament.query.filter(
            Tournament.start_date <= current_time,
            Tournament.is_active == True
        ).order_by(Tournament.start_date.desc()).all()
        
        next_tournament = None
        is_tournament_running = False
        
        # Проверяем каждый активный турнир
        for tournament in active_tournaments:
            end_time = tournament.start_date + timedelta(minutes=tournament.duration)
            if current_time <= end_time:
                next_tournament = tournament
                is_tournament_running = True
                break
        
        # Если нет текущего турнира, ищем следующий
        if not next_tournament:
            next_tournament = Tournament.query.filter(
                Tournament.start_date > current_time,
                Tournament.is_active == True
            ).order_by(Tournament.start_date.asc()).first()
        
        return render_template('index.html',
                             next_tournament=next_tournament,
                             now=current_time,
                             is_tournament_running=is_tournament_running)
    else:
        return render_template('index_close.html', message=settings.closed_season_message)

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
                block_message = f'Ваш аккаунт заблокирован администратором.'
                if user.block_reason:
                    block_message += f' Причина: {user.block_reason}'
                block_message += ' Для разблокировки обратитесь к администратору по email: admin@school-tournaments.ru'
                flash(block_message, 'danger')
                return redirect(url_for('login'))
            if not user.is_active:
                flash('Пожалуйста, подтвердите ваш email перед входом', 'warning')
                return redirect(url_for('login'))
            
            # Проверяем, не вошел ли пользователь с другого устройства
            if user.session_token:
                # Проверяем время последней активности
                if user.last_activity and (datetime.utcnow() - user.last_activity) < timedelta(days=1):
                    flash('Вы уже вошли в систему с другого устройства. Пожалуйста, выйдите из другого устройства перед входом или подождите 24 часа.', 'danger')
                    return redirect(url_for('login'))
                else:
                    # Если прошло больше суток, очищаем старую сессию
                    user.session_token = None
                    user.last_activity = None
            
            # Генерируем новый токен сессии
            session_token = secrets.token_urlsafe(32)
            user.session_token = session_token
            user.last_login = datetime.utcnow()
            user.last_activity = datetime.utcnow()
            db.session.commit()
            
            # Сохраняем токен в сессии
            session['session_token'] = session_token
            
            login_user(user)
            return redirect(url_for('home'))
        else:
            flash('Неверный логин или пароль', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    # Очищаем токен сессии
    current_user.session_token = None
    current_user.last_activity = None
    db.session.commit()
    session.pop('session_token', None)
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
    
    # Получаем параметры поиска и пагинации
    search_query = request.args.get('search', '').strip()
    search_type = request.args.get('search_type', 'username')
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Количество пользователей на странице
    
    # Базовый запрос
    query = User.query
    
    # Применяем фильтры поиска
    if search_query:
        if search_type == 'username':
            query = query.filter(User.username.ilike(f'%{search_query}%'))
        elif search_type == 'email':
            query = query.filter(User.email.ilike(f'%{search_query}%'))
        elif search_type == 'id':
            try:
                user_id = int(search_query)
                query = query.filter(User.id == user_id)
            except ValueError:
                flash('ID пользователя должен быть числом', 'warning')
    
    # Получаем пользователей с сортировкой по дате создания
    users = query.order_by(User.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    # Если это AJAX-запрос, возвращаем только данные
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'users': [{
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'created_at': user.created_at.strftime('%d.%m.%Y %H:%M'),
                'is_active': user.is_active,
                'is_blocked': user.is_blocked
            } for user in users.items],
            'has_next': users.has_next
        })
    
    return render_template('admin/users.html', 
                         users=users.items,
                         pagination=users,
                         search_query=search_query,
                         search_type=search_type)

@app.route('/admin/users/add', methods=['POST'])
@login_required
def admin_add_user():
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    phone = request.form.get('phone')
    parent_name = request.form.get('parent_name')
    category = request.form.get('category')
    is_admin = 'is_admin' in request.form
    
    if not all([username, email, password, phone, parent_name, category]):
        flash('Все поля должны быть заполнены', 'danger')
        return redirect(url_for('admin_users'))
    
    if User.query.filter_by(username=username).first():
        flash('Пользователь с таким логином уже существует', 'danger')
        return redirect(url_for('admin_users'))
    
    if User.query.filter_by(email=email).first():
        flash('Пользователь с таким email уже существует', 'danger')
        return redirect(url_for('admin_users'))
    
    if User.query.filter_by(phone=phone).first():
        flash('Пользователь с таким номером телефона уже существует', 'danger')
        return redirect(url_for('admin_users'))
    
    if not re.match(r'^\+375[0-9]{9}$', phone):
        flash('Номер телефона должен быть в формате +375XXXXXXXXX', 'danger')
        return redirect(url_for('admin_users'))
    
    if category not in ['1-2', '3-4', '5-6', '7-8', '9', '10-11']:
        flash('Некорректная категория', 'danger')
        return redirect(url_for('admin_users'))
    
    user = User(
        username=username,
        email=email,
        phone=phone,
        parent_name=parent_name,
        category=category,
        is_admin=is_admin,
        is_active=True
    )
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
    
    if user.is_blocked:
        # Разблокировка пользователя
        user.is_blocked = False
        user.block_reason = None
        action = "разблокирован"
    else:
        # Блокировка пользователя
        block_reason = request.form.get('block_reason')
        if not block_reason:
            flash('Необходимо указать причину блокировки', 'danger')
            return redirect(url_for('admin_users'))
        
        user.is_blocked = True
        user.block_reason = block_reason
        action = "заблокирован"
    
    db.session.commit()
    flash(f'Пользователь {user.username} успешно {action}', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/reset-all-balances', methods=['POST'])
@login_required
def admin_reset_all_balances():
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    password = request.form.get('password')
    if not password:
        return jsonify({'success': False, 'message': 'Введите пароль для подтверждения'})
    
    if not current_user.check_password(password):
        return jsonify({'success': False, 'message': 'Неверный пароль'})
    
    try:
        User.query.update({User.balance: 0})
        db.session.commit()
        return jsonify({'success': True, 'message': 'Счет всех пользователей успешно обнулен'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Произошла ошибка при обнулении счетов'})

@app.route('/admin/tournaments')
@login_required
def admin_tournaments():
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    tournaments = Tournament.query.order_by(Tournament.id.desc()).all()
    return render_template('admin/tournaments.html', title='Управление турнирами', tournaments=tournaments)

def generate_unique_filename(filename):
    """Генерирует уникальное имя файла, сохраняя расширение"""
    # Получаем расширение файла
    ext = os.path.splitext(filename)[1]
    # Генерируем уникальное имя с использованием timestamp и случайной строки
    unique_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(8)}{ext}"
    return unique_name

@app.route('/admin/tournaments/add', methods=['POST'])
@login_required
def admin_add_tournament():
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    title = request.form.get('title')
    description = request.form.get('description')
    rules = request.form.get('rules')
    start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%dT%H:%M')
    duration = int(request.form.get('duration'))
    
    # Обработка изображения
    image = request.files.get('image')
    image_filename = None
    if image and image.filename:
        image_filename = generate_unique_filename(secure_filename(image.filename))
        image_path = os.path.join(app.static_folder, 'uploads', image_filename)
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        image.save(image_path)
    
    tournament = Tournament(
        title=title,
        description=description,
        rules=rules,
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
    tournament.rules = request.form.get('rules')
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
        
        # Сохраняем новое изображение с уникальным именем
        image_filename = generate_unique_filename(secure_filename(image.filename))
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
    
    # Получаем общее количество участников
    total_participants = db.session.query(func.count(TournamentParticipation.id))\
        .filter(TournamentParticipation.tournament_id == tournament_id)\
        .scalar()
    
    # Получаем статистику по задачам
    tasks_stats = db.session.query(
        Task.id,
        Task.title,
        Task.points,
        func.count(SolvedTask.id).label('solved_count'),
        func.sum(case((SolvedTask.is_correct == True, 1), else_=0)).label('correct_count')
    ).select_from(Task)\
     .filter(Task.tournament_id == tournament_id)\
     .outerjoin(SolvedTask, Task.id == SolvedTask.task_id)\
     .group_by(Task.id, Task.title, Task.points)\
     .all()
    
    # Формируем статистику по задачам
    tasks_data = []
    total_points_earned = 0
    
    for task_id, title, points, solved_count, correct_count in tasks_stats:
        if total_participants > 0:
            solve_percentage = (correct_count or 0) / total_participants * 100
        else:
            solve_percentage = 0
            
        tasks_data.append({
            'id': task_id,
            'title': title,
            'points': points,
            'solved_count': solved_count or 0,
            'correct_count': correct_count or 0,
            'solve_percentage': round(solve_percentage, 2)
        })
        
        total_points_earned += points * (correct_count or 0)
    
    # Получаем топ-5 участников
    top_participants = db.session.query(
        User.username,
        TournamentParticipation.score
    ).join(
        TournamentParticipation,
        User.id == TournamentParticipation.user_id
    ).filter(
        TournamentParticipation.tournament_id == tournament_id
    ).order_by(
        TournamentParticipation.score.desc()
    ).limit(5).all()
    
    return jsonify({
        'tournament_title': tournament.title,
        'total_participants': total_participants,
        'tasks_stats': tasks_data,
        'total_points_earned': total_points_earned,
        'top_participants': [{'username': username, 'score': score} for username, score in top_participants]
    })

@app.route('/admin/shop')
@login_required
def admin_shop():
    if not current_user.is_admin:
        flash('Недостаточно прав', 'error')
        return redirect(url_for('home'))
    return render_template('admin/shop.html', title='Управление магазином')

@app.route('/admin/shop/tickets')
@login_required
def admin_tickets():
    if not current_user.is_admin:
        flash('Недостаточно прав', 'error')
        return redirect(url_for('home'))
    
    base_price = TicketPackage.query.filter_by(is_active=True).first()
    discounts = TicketDiscount.query.filter_by(is_active=True).order_by(TicketDiscount.min_quantity.asc()).all()
    
    return render_template('admin/tickets.html', 
                         title='Управление билетами',
                         base_price=base_price,
                         discounts=discounts)

@app.route('/admin/shop/tickets/set-price', methods=['POST'])
@login_required
def admin_set_ticket_price():
    if not current_user.is_admin:
        flash('Недостаточно прав', 'error')
        return redirect(url_for('home'))
    
    price = request.form.get('price', type=float)
    if not price or price <= 0:
        flash('Некорректная цена', 'danger')
        return redirect(url_for('admin_tickets'))
    
    # Деактивируем старый пакет
    old_package = TicketPackage.query.filter_by(is_active=True).first()
    if old_package:
        old_package.is_active = False
    
    # Создаем новый пакет с новой ценой
    new_package = TicketPackage(price=price)
    db.session.add(new_package)
    db.session.commit()
    
    flash('Базовая цена билета успешно обновлена', 'success')
    return redirect(url_for('admin_tickets'))

@app.route('/admin/shop/tickets/discounts/add', methods=['POST'])
@login_required
def admin_add_ticket_discount():
    if not current_user.is_admin:
        flash('Недостаточно прав', 'error')
        return redirect(url_for('home'))
    
    min_quantity = request.form.get('min_quantity', type=int)
    discount = request.form.get('discount', type=int)
    
    if not all([min_quantity, discount]):
        flash('Все поля должны быть заполнены', 'danger')
        return redirect(url_for('admin_tickets'))
    
    if min_quantity < 1 or discount < 0 or discount > 100:
        flash('Некорректные значения', 'danger')
        return redirect(url_for('admin_tickets'))
    
    # Проверяем, нет ли уже скидки для такого количества
    existing_discount = TicketDiscount.query.filter_by(min_quantity=min_quantity, is_active=True).first()
    if existing_discount:
        flash('Скидка для такого количества билетов уже существует', 'danger')
        return redirect(url_for('admin_tickets'))
    
    discount_obj = TicketDiscount(
        min_quantity=min_quantity,
        discount=discount
    )
    
    db.session.add(discount_obj)
    db.session.commit()
    
    flash('Скидка успешно добавлена', 'success')
    return redirect(url_for('admin_tickets'))

@app.route('/admin/shop/tickets/discounts/<int:discount_id>/delete', methods=['POST'])
@login_required
def admin_delete_ticket_discount(discount_id):
    if not current_user.is_admin:
        flash('Недостаточно прав', 'error')
        return redirect(url_for('home'))
    
    discount = TicketDiscount.query.get_or_404(discount_id)
    discount.is_active = False
    db.session.commit()
    
    flash('Скидка успешно удалена', 'success')
    return redirect(url_for('admin_tickets'))

@app.route('/admin/shop/prizes')
@login_required
def admin_prizes():
    if not current_user.is_admin:
        flash('Недостаточно прав', 'error')
        return redirect(url_for('home'))
    
    prizes = Prize.query.filter_by(is_active=True).order_by(Prize.points_cost.asc()).all()
    return render_template('admin/prizes.html', 
                         title='Управление призами',
                         prizes=prizes)

@app.route('/admin/shop/prizes/add', methods=['POST'])
@login_required
def admin_add_prize():
    if not current_user.is_admin:
        flash('Недостаточно прав', 'error')
        return redirect(url_for('home'))
    
    name = request.form.get('name')
    description = request.form.get('description')
    points_cost = request.form.get('points_cost', type=int)
    quantity = request.form.get('quantity', type=int, default=0)
    is_unique = 'is_unique' in request.form  # Получаем значение флага уникальности
    
    if not all([name, description, points_cost]):
        flash('Все обязательные поля должны быть заполнены', 'danger')
        return redirect(url_for('admin_prizes'))
    
    if points_cost < 1 or quantity < 0:
        flash('Некорректные значения', 'danger')
        return redirect(url_for('admin_prizes'))
    
    # Обработка изображения
    image = request.files.get('image')
    image_filename = None
    if image and image.filename:
        image_filename = generate_unique_filename(secure_filename(image.filename))
        image_path = os.path.join(app.static_folder, 'uploads', 'prizes', image_filename)
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        image.save(image_path)
    
    prize = Prize(
        name=name,
        description=description,
        image=image_filename,
        points_cost=points_cost,
        quantity=quantity,
        is_unique=is_unique
    )
    
    db.session.add(prize)
    db.session.commit()
    
    flash('Приз успешно добавлен', 'success')
    return redirect(url_for('admin_prizes'))

@app.route('/admin/shop/prizes/<int:prize_id>/delete', methods=['POST'])
@login_required
def admin_delete_prize(prize_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Недостаточно прав'}), 403
    
    prize = Prize.query.get_or_404(prize_id)
    
    try:
        # Удаляем изображение
        if prize.image:
            image_path = os.path.join(app.static_folder, 'uploads', 'prizes', prize.image)
            if os.path.exists(image_path):
                os.remove(image_path)
        
        # Деактивируем приз
        prize.is_active = False
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Приз успешно удален'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Произошла ошибка при удалении приза'}), 500

@app.route('/admin/shop/prizes/<int:prize_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_edit_prize(prize_id):
    if not current_user.is_admin:
        flash('Недостаточно прав', 'error')
        return redirect(url_for('home'))
    
    prize = Prize.query.get_or_404(prize_id)
    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        points_cost = request.form.get('points_cost', type=int)
        quantity = request.form.get('quantity', type=int, default=0)
        is_unique = 'is_unique' in request.form
        is_active = 'is_active' in request.form
        
        if not all([name, description, points_cost]):
            flash('Все обязательные поля должны быть заполнены', 'danger')
            return redirect(url_for('admin_edit_prize', prize_id=prize_id))
        
        if points_cost < 1 or quantity < 0:
            flash('Некорректные значения', 'danger')
            return redirect(url_for('admin_edit_prize', prize_id=prize_id))
        
        # Обработка изображения
        image = request.files.get('image')
        if image and image.filename:
            # Удаляем старое изображение, если оно есть
            if prize.image:
                old_image_path = os.path.join(app.static_folder, 'uploads', 'prizes', prize.image)
                if os.path.exists(old_image_path):
                    os.remove(old_image_path)
            
            image_filename = generate_unique_filename(secure_filename(image.filename))
            image_path = os.path.join(app.static_folder, 'uploads', 'prizes', image_filename)
            os.makedirs(os.path.dirname(image_path), exist_ok=True)
            image.save(image_path)
            prize.image = image_filename
        
        prize.name = name
        prize.description = description
        prize.points_cost = points_cost
        prize.quantity = quantity
        prize.is_unique = is_unique
        prize.is_active = is_active
        
        db.session.commit()
        flash('Приз успешно обновлен', 'success')
        return redirect(url_for('admin_prizes'))
    
    return render_template('admin/edit_prize.html', prize=prize)

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
    category = request.form.get('category')  # Получаем категорию из формы
    
    if not all([title, description, points, correct_answer, category]):  # Проверяем наличие категории
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
        image_filename = generate_unique_filename(secure_filename(image.filename))
        image_path = os.path.join(app.static_folder, 'uploads', 'tasks', image_filename)
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        image.save(image_path)
    
    task = Task(
        tournament_id=tournament_id,
        title=title,
        description=description,
        image=image_filename,
        points=points,
        correct_answer=correct_answer,
        category=category  # Добавляем категорию при создании задачи
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
        
        # Сохраняем новое изображение с уникальным именем
        image_filename = generate_unique_filename(secure_filename(image.filename))
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
    if len(password) < 8:
        return False
    if not any(c.isdigit() for c in password):
        return False
    if not any(c.isalpha() for c in password):
        return False
    return True

def is_valid_username(username):
    # Проверяем, что логин содержит только допустимые символы
    if not all(c.isalnum() or c == '_' for c in username):
        return False
    # Проверяем, что логин содержит хотя бы одну букву
    if not any(c.isalpha() for c in username):
        return False
    # Проверяем минимальную длину
    if len(username) < 3:
        return False
    return True

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        phone = request.form.get('phone')
        parent_name = request.form.get('parent_name')
        category = request.form.get('category')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if not is_valid_username(username):
            flash('Логин может содержать только буквы латинского алфавита, цифры и знак подчеркивания. Минимальная длина - 3 символа, должен содержать хотя бы одну букву.', 'danger')
            return redirect(url_for('register'))

        if not is_password_strong(password):
            flash('Пароль должен содержать минимум 8 символов, включая цифры и буквы', 'danger')
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Пароли не совпадают', 'danger')
            return redirect(url_for('register'))

        if not re.match(r'^\+375[0-9]{9}$', phone):
            flash('Номер телефона должен быть в формате +375XXXXXXXXX', 'danger')
            return redirect(url_for('register'))

        if not category or category not in ['1-2', '3-4', '5-6', '7-8', '9', '10-11']:
            flash('Пожалуйста, выберите группу', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash('Пользователь с таким логином уже существует', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('Пользователь с таким email уже существует', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(phone=phone).first():
            flash('Пользователь с таким номером телефона уже существует', 'danger')
            return redirect(url_for('register'))

        user = User(
            username=username,
            email=email,
            phone=phone,
            parent_name=parent_name,
            category=category
        )
        user.set_password(password)
        user.temp_password = password
        db.session.add(user)
        db.session.commit()

        # Отправляем письмо с подтверждением асинхронно
        send_confirmation_email(user)
        
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
        password = user.temp_password
        if password:
            send_credentials_email(user, password)
            user.temp_password = None
            db.session.commit()
        
        flash('Email успешно подтвержден! Теперь вы можете войти.', 'success')
    else:
        flash('Недействительная или устаревшая ссылка подтверждения.', 'danger')
    return redirect(url_for('login'))

def get_user_rank(user_id):
    """Получает ранг пользователя в его возрастной категории"""
    user = User.query.get(user_id)
    if not user:
        return None
    
    # Получаем всех пользователей той же категории, отсортированных по балансу
    users = User.query.filter_by(category=user.category).order_by(User.balance.desc()).all()
    
    # Находим индекс пользователя в отсортированном списке
    for index, u in enumerate(users, 1):
        if u.id == user_id:
            return index
    return None

@app.route('/profile')
@login_required
def profile():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    
    # Получаем текущее время
    current_time = datetime.utcnow() + timedelta(hours=3)
    
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
        ).order_by(Tournament.start_date.desc()).all()
        
        # Находим турнир, который идет сейчас
        for tournament in active_tournaments:
            end_time = tournament.start_date + timedelta(minutes=tournament.duration)
            if current_time <= end_time:
                next_tournament = tournament
                break
    
    user_rank = get_user_rank(current_user.id)
    settings = TournamentSettings.get_settings()
    
    return render_template('profile.html', 
                         title='Личный кабинет', 
                         user_rank=user_rank,
                         next_tournament=next_tournament,
                         now=current_time,
                         settings=settings)

@app.route('/buy-tickets')
@login_required
def buy_tickets():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    
    base_price = TicketPackage.query.filter_by(is_active=True).first()
    if not base_price:
        flash('В данный момент покупка билетов недоступна', 'warning')
        return redirect(url_for('profile'))
    
    # Получаем скидки и преобразуем их в словари
    discounts = TicketDiscount.query.filter_by(is_active=True).order_by(TicketDiscount.min_quantity.asc()).all()
    discounts_data = [{
        'min_quantity': discount.min_quantity,
        'discount': discount.discount
    } for discount in discounts]
    
    return render_template('buy_tickets.html', 
                         title='Покупка билетов',
                         base_price=base_price,
                         discounts=discounts_data)

@app.route('/process-ticket-purchase', methods=['POST'])
@login_required
def process_ticket_purchase():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    
    quantity = request.form.get('quantity', type=int)
    if not quantity or quantity < 1:
        flash('Укажите корректное количество билетов', 'danger')
        return redirect(url_for('buy_tickets'))
    
    base_price = TicketPackage.query.filter_by(is_active=True).first()
    if not base_price:
        flash('В данный момент покупка билетов недоступна', 'warning')
        return redirect(url_for('profile'))
    
    # Получаем скидку для указанного количества
    discount = TicketDiscount.get_discount_for_quantity(quantity)
    
    # Рассчитываем итоговую стоимость
    total_price = base_price.price * quantity * (1 - discount / 100)
    
    # Здесь должна быть интеграция с платежной системой
    # Для демонстрации просто добавляем билеты пользователю
    
    # Создаем запись о покупке
    purchase = TicketPurchase(
        user_id=current_user.id,
        quantity=quantity,
        amount=total_price,
        discount=discount
    )
    
    # Добавляем билеты пользователю
    current_user.tickets += quantity
    
    db.session.add(purchase)
    db.session.commit()
    
    flash(f'Успешно куплено {quantity} билетов', 'success')
    return redirect(url_for('profile'))

@app.route('/purchase-history')
@login_required
def purchase_history():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    
    # Получаем параметры пагинации
    ticket_page = request.args.get('ticket_page', 1, type=int)
    prize_page = request.args.get('prize_page', 1, type=int)
    per_page = 10  # количество записей на странице
    
    # Получаем историю покупок билетов с пагинацией
    ticket_purchases = TicketPurchase.query.filter_by(user_id=current_user.id)\
        .order_by(TicketPurchase.purchase_date.desc())\
        .paginate(page=ticket_page, per_page=per_page, error_out=False)
    
    # Получаем историю покупок товаров с пагинацией
    prize_purchases = PrizePurchase.query.filter_by(user_id=current_user.id)\
        .order_by(PrizePurchase.created_at.desc())\
        .paginate(page=prize_page, per_page=per_page, error_out=False)
    
    return render_template('purchase_history.html', 
                         title='История покупок',
                         ticket_purchases=ticket_purchases,
                         prize_purchases=prize_purchases)

@app.route('/purchase/<int:purchase_id>/details')
@login_required
def purchase_details(purchase_id):
    purchase = PrizePurchase.query.get_or_404(purchase_id)
    
    # Проверяем, принадлежит ли покупка текущему пользователю
    if purchase.user_id != current_user.id:
        return jsonify({'error': 'У вас нет доступа к этой информации'}), 403
    
    return jsonify({
        'id': purchase.id,
        'created_at': purchase.created_at.strftime('%d.%m.%Y %H:%M'),
        'status': purchase.status,
        'full_name': purchase.full_name,
        'phone': purchase.phone,
        'address': purchase.address
    })

@app.route('/download-receipt/<int:purchase_id>')
@login_required
def download_receipt(purchase_id):
    purchase = TicketPurchase.query.get_or_404(purchase_id)
    
    # Проверяем, принадлежит ли покупка текущему пользователю
    if purchase.user_id != current_user.id:
        flash('У вас нет доступа к этому чеку', 'danger')
        return redirect(url_for('purchase_history'))
    
    # TODO: Здесь будет интеграция с эквайрингом для получения чека
    flash('Функция получения чека временно недоступна', 'info')
    return redirect(url_for('purchase_history'))

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
    

    
    # Проверяем, не является ли пользователь администратором
    if current_user.is_admin:

        flash('Администраторы не могут участвовать в турнирах', 'warning')
        return redirect(url_for('home'))
    
    # Проверяем, есть ли у пользователя билет
    if current_user.tickets < 1:

        flash('У вас недостаточно билетов для участия в турнире', 'warning')
        return redirect(url_for('profile'))
    
    # Проверяем, начался ли турнир
    if tournament.start_date <= current_time:
        # Проверяем, не закончился ли турнир
        end_time = tournament.start_date + timedelta(minutes=tournament.duration)

        if end_time > current_time:

            # Если турнир идет, перенаправляем в меню турнира
            return redirect(url_for('tournament_menu', tournament_id=tournament.id))
        else:

            flash('Турнир уже закончился', 'warning')
            return redirect(url_for('home'))
    else:

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
    
    # Проверяем, идет ли турнир
    current_time = datetime.now()  # Используем локальное время
    if not (tournament.start_date <= current_time and 
            current_time <= tournament.start_date + timedelta(minutes=tournament.duration)):
        flash('Турнир не активен', 'warning')
        return redirect(url_for('home'))
    
    # Проверяем, есть ли у пользователя билет
    if current_user.tickets < 1:
        flash('У вас недостаточно билетов для участия в турнире', 'warning')
        return redirect(url_for('profile'))
    
    # Проверяем, не является ли пользователь администратором
    if current_user.is_admin:
        flash('Администраторы не могут участвовать в турнирах', 'warning')
        return redirect(url_for('home'))
    
    # Проверяем, участвует ли уже пользователь в турнире
    participation = TournamentParticipation.query.filter_by(
        user_id=current_user.id,
        tournament_id=tournament_id
    ).first()
    
    if not participation:
        # Получаем список решенных задач пользователя
        solved_tasks = SolvedTask.query.filter_by(
            user_id=current_user.id,
            is_correct=True
        ).join(Task).filter(Task.tournament_id == tournament_id).all()
        solved_task_ids = [task.task_id for task in solved_tasks]
        
        # Получаем доступные задачи для категории пользователя
        available_tasks = Task.query.filter(
            Task.tournament_id == tournament_id,
            Task.id.notin_(solved_task_ids),
            Task.category == current_user.category
        ).all()
        
        if not available_tasks:
            flash('Для вашей категории нет доступных задач в этом турнире', 'warning')
            return redirect(url_for('home'))
        
        # Если есть доступные задачи, создаем запись об участии и списываем билет
        participation = TournamentParticipation(
            user_id=current_user.id,
            tournament_id=tournament_id,
            score=0,
            start_time=current_time  # Используем локальное время
        )
        current_user.tickets -= 1
        current_user.tournaments_count += 1  # Увеличиваем счетчик турниров
        db.session.add(participation)
        db.session.commit()
        flash('Билет успешно списан. Удачи в турнире!', 'success')
    
    # Перенаправляем на страницу с задачами
    return redirect(url_for('tournament_task', tournament_id=tournament.id))

@app.route('/admin/users/<int:user_id>/details')
@login_required
def admin_user_details(user_id):
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    user = User.query.get_or_404(user_id)
    
    # Получаем статистику
    total_tickets_purchased = sum(purchase.quantity for purchase in user.ticket_purchases)
    total_tournaments_participated = user.tournaments_count  # Используем новое поле
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
    now = datetime.utcnow() + timedelta(hours=3)  # Московское время
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
    if current_user.is_authenticated:
        result = check_session()
        if result:
            return result

def check_session():
    if current_user.is_authenticated:
        session_token = session.get('session_token')
        if not session_token or session_token != current_user.session_token:
            logout_user()
            flash('Ваша сессия была завершена, так как вы вошли в систему с другого устройства', 'warning')
            return redirect(url_for('login'))
        
        # Проверяем время последней активности
        if current_user.last_activity and (datetime.utcnow() - current_user.last_activity) > timedelta(days=1):
            # Очищаем сессию
            current_user.session_token = None
            current_user.last_activity = None
            db.session.commit()
            session.pop('session_token', None)
            logout_user()
            flash('Ваша сессия была завершена из-за длительного отсутствия активности', 'warning')
            return redirect(url_for('login'))
        
        # Обновляем время последней активности
        current_user.last_activity = datetime.utcnow()
        db.session.commit()
    return None

def restore_scheduler_jobs():
    """Восстанавливает задачи планировщика для активных турниров при запуске приложения"""
    # Получаем все активные турниры
    active_tournaments = Tournament.query.filter_by(is_active=True).all()
    
    now = datetime.utcnow() + timedelta(hours=3)  # Московское время
    restored_jobs = 0
    
    for tournament in active_tournaments:
        # Если турнир еще не начался
        if tournament.start_date > now:
            add_scheduler_job(start_tournament_job, tournament.start_date, tournament.id, 'start')
            end_time = tournament.start_date + timedelta(minutes=tournament.duration)
            add_scheduler_job(end_tournament_job, end_time, tournament.id, 'end')
            restored_jobs += 2
            
        # Если турнир уже идет
        elif tournament.start_date <= now and now <= tournament.start_date + timedelta(minutes=tournament.duration):
            tournament.status = 'started'
            end_time = tournament.start_date + timedelta(minutes=tournament.duration)
            add_scheduler_job(end_tournament_job, end_time, tournament.id, 'end')
            restored_jobs += 1
            
        # Если турнир уже должен был закончиться
        else:
            tournament.status = 'finished'
            tournament.is_active = False
    
    db.session.commit()

def cleanup_scheduler_jobs():
    """Очищает все задачи планировщика перед восстановлением"""
    try:
        scheduler.remove_all_jobs()
    except Exception as e:
        pass

@app.route('/tournament/<int:tournament_id>/task')
@login_required
def tournament_task(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Проверяем, что турнир активен
    if not tournament.is_active:
        flash('Турнир неактивен', 'warning')
        return redirect(url_for('home'))
    
    # Проверяем, что турнир еще не закончился
    if datetime.utcnow() > tournament.start_date + timedelta(minutes=tournament.duration):
        flash('Турнир уже закончился', 'warning')
        return redirect(url_for('home'))
    
    # Проверяем, что пользователь участвует в турнире
    participation = TournamentParticipation.query.filter_by(
        user_id=current_user.id,
        tournament_id=tournament_id
    ).first()
    
    if not participation:
        flash('Вы не участвуете в этом турнире', 'warning')
        return redirect(url_for('home'))
    
    # Получаем список всех задач, которые пользователь уже решал (и правильно, и неправильно)
    solved_tasks = SolvedTask.query.filter_by(
        user_id=current_user.id
    ).join(Task).filter(Task.tournament_id == tournament_id).all()
    solved_task_ids = [task.task_id for task in solved_tasks]
    
    # Получаем текущую задачу из сессии
    current_task_id = session.get(f'current_task_{tournament_id}')
    
    # Получаем все задачи турнира для категории пользователя, исключая уже решенные
    available_tasks = Task.query.filter(
        Task.tournament_id == tournament_id,
        Task.id.notin_(solved_task_ids),
        Task.category == current_user.category  # Фильтруем по категории пользователя
    ).all()
    
    if not available_tasks:
        # Если все задачи решены, перенаправляем на страницу результатов
        return redirect(url_for('tournament_results', tournament_id=tournament_id))
    
    if current_task_id:
        # Проверяем, что задача все еще доступна и соответствует категории пользователя
        if current_task_id not in solved_task_ids:
            task = Task.query.get(current_task_id)
            if task and task.tournament_id == tournament_id and task.category == current_user.category:
                return render_template('tournament_task.html', 
                                     tournament=tournament, 
                                     task=task,
                                     timedelta=timedelta)
    
    # Если нет сохраненной задачи или она уже решена, выбираем новую
    task = random.choice(available_tasks)
    
    # Сохраняем ID задачи в сессии
    session[f'current_task_{tournament_id}'] = task.id
    
    return render_template('tournament_task.html', 
                         tournament=tournament, 
                         task=task,
                         timedelta=timedelta)

@app.route('/tournament/<int:tournament_id>/task/<int:task_id>/submit', methods=['POST'])
@login_required
def submit_task_answer(tournament_id, task_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    task = Task.query.get_or_404(task_id)
    
    # Проверяем, идет ли турнир
    current_time = datetime.now()  # Используем локальное время
    if not (tournament.start_date <= current_time and 
            current_time <= tournament.start_date + timedelta(minutes=tournament.duration)):
        flash('Турнир не активен', 'warning')
        return redirect(url_for('home'))
    
    # Проверяем, не решена ли уже эта задача
    if SolvedTask.query.filter_by(
        user_id=current_user.id,
        task_id=task_id,
        is_correct=True
    ).first():
        flash('Вы уже решили эту задачу', 'warning')
        return redirect(url_for('tournament_task', tournament_id=tournament_id))
    
    # Получаем участие пользователя в турнире
    participation = TournamentParticipation.query.filter_by(
        user_id=current_user.id,
        tournament_id=tournament_id
    ).first()
    
    if not participation:
        flash('Вы не участвуете в этом турнире', 'warning')
        return redirect(url_for('home'))
    
    # Получаем ответ пользователя и приводим к нижнему регистру
    user_answer = request.form.get('answer', '').strip().lower()
    
    # Проверяем ответ (приводим правильный ответ к нижнему регистру)
    is_correct = user_answer == task.correct_answer.lower()
    
    # Сохраняем результат
    solution = SolvedTask(
        user_id=current_user.id,
        task_id=task_id,
        is_correct=is_correct
    )
    db.session.add(solution)
    
    if is_correct:
        # Добавляем баллы к общему счету
        current_user.balance += task.points
        
        # Проверяем на подозрительную активность
        # Получаем все задачи турнира для категории пользователя
        all_tasks = Task.query.filter_by(
            tournament_id=tournament_id,
            category=current_user.category
        ).all()
        total_tasks = len(all_tasks)
        
        # Получаем все решенные задачи пользователя в этом турнире
        solved_tasks = SolvedTask.query.filter_by(
            user_id=current_user.id,
            is_correct=True
        ).join(Task).filter(
            Task.tournament_id == tournament_id,
            Task.category == current_user.category
        ).all()
        
        # Считаем процент правильно решенных задач
        correct_percentage = (len(solved_tasks) / total_tasks) * 100 if total_tasks > 0 else 0
        
        # Вычисляем время участия в турнире
        time_spent = (current_time - participation.start_time).total_seconds()
        
        # Выводим отладочную информацию
        print(f"\n=== Проверка подозрительной активности ===")
        print(f"Пользователь: {current_user.username}")
        print(f"Время начала: {participation.start_time}")
        print(f"Текущее время: {current_time}")
        print(f"Время участия: {time_spent} секунд")
        print(f"Решено задач: {len(solved_tasks)} из {total_tasks}")
        print(f"Процент правильных ответов: {correct_percentage:.1f}%")
        print("=====================================\n")
        
        # Если время меньше 5 минут и процент правильных ответов больше 50%
        if time_spent < 300 and correct_percentage > 50:  # 300 секунд = 5 минут
            current_user.is_blocked = True
            current_user.block_reason = "Подозрение на жульничество"
            flash('Ваш аккаунт заблокирован из-за подозрительной активности', 'danger')
            db.session.commit()
            
            # Очищаем токен сессии
            current_user.session_token = None
            current_user.last_activity = None
            db.session.commit()
            session.pop('session_token', None)
            logout_user()
            
            return redirect(url_for('login'))
        
        flash(f'Правильный ответ! +{task.points} баллов', 'success')
    else:
        flash('Неправильный ответ', 'danger')
    
    db.session.commit()
    
    # Удаляем текущую задачу из сессии
    session.pop(f'current_task_{tournament_id}', None)
    
    return redirect(url_for('tournament_task', tournament_id=tournament_id))

@app.route('/tournament/<int:tournament_id>/results')
@login_required
def tournament_results(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Получаем все задачи турнира
    all_tasks = Task.query.filter_by(tournament_id=tournament_id).all()
    total_tasks = len(all_tasks)
    
    # Получаем решенные задачи пользователя
    solved_tasks = SolvedTask.query.filter_by(
        user_id=current_user.id,
        is_correct=True
    ).join(Task).filter(Task.tournament_id == tournament_id).all()
    
    # Считаем статистику
    solved_count = len(solved_tasks)
    earned_points = sum(task.task.points for task in solved_tasks)
    
    # Получаем участие пользователя в турнире
    participation = TournamentParticipation.query.filter_by(
        user_id=current_user.id,
        tournament_id=tournament_id
    ).first()
    
    if participation:
        # Вычисляем общее время участия в турнире
        current_time = datetime.now()  # Используем локальное время
        time_spent = (current_time - participation.start_time).total_seconds()
        minutes = int(time_spent // 60)
        seconds = int(time_spent % 60)
        
        # Добавляем время к общему времени участия в турнирах
        current_user.total_tournament_time += int(time_spent)
        db.session.commit()
        
        # Выводим информацию в консоль
        print(f"\n=== Информация о турнире {tournament.title} ===")
        print(f"Пользователь: {current_user.username}")
        print(f"Время начала: {participation.start_time}")
        print(f"Время окончания: {current_time}")
        print(f"Общее время участия: {minutes} минут {seconds} секунд")
        print(f"Решено задач: {solved_count} из {total_tasks}")
        print(f"Процент правильных ответов: {(solved_count / total_tasks * 100) if total_tasks > 0 else 0:.1f}%")
        print(f"Заработано баллов: {earned_points}")
        print(f"Общее время в турнирах: {current_user.total_tournament_time} секунд")
        print("=====================================\n")
    
    return render_template('tournament_results.html',
                         tournament=tournament,
                         total_tasks=total_tasks,
                         solved_count=solved_count,
                         earned_points=earned_points,
                         current_balance=current_user.balance)

@app.route('/tournament/history')
@login_required
def tournament_history():
    if current_user.is_admin:
        flash('Администраторы не могут участвовать в турнирах', 'warning')
        return redirect(url_for('home'))
    
    # Получаем параметр страницы
    page = request.args.get('page', 1, type=int)
    per_page = 10  # количество записей на странице
    
    # Получаем все турниры, в которых участвовал пользователь
    tournaments_query = db.session.query(
        Tournament,
        TournamentParticipation.score,
        TournamentParticipation.place,
        func.count(SolvedTask.id).label('solved_tasks'),
        func.sum(case((SolvedTask.is_correct == True, Task.points), else_=0)).label('earned_points'),
        func.count(case((SolvedTask.is_correct == True, 1))).label('correct_tasks'),
        func.count(Task.id).label('total_tasks')
    ).join(
        TournamentParticipation,
        Tournament.id == TournamentParticipation.tournament_id
    ).outerjoin(
        Task,
        Tournament.id == Task.tournament_id
    ).outerjoin(
        SolvedTask,
        (Task.id == SolvedTask.task_id) & (SolvedTask.user_id == current_user.id)
    ).filter(
        TournamentParticipation.user_id == current_user.id
    ).group_by(
        Tournament.id,
        TournamentParticipation.score,
        TournamentParticipation.place
    ).order_by(
        Tournament.start_date.desc()
    )
    
    # Применяем пагинацию
    tournaments = tournaments_query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Преобразуем результаты в список словарей для удобного доступа в шаблоне
    tournament_list = []
    for tournament, score, place, solved_tasks, earned_points, correct_tasks, total_tasks in tournaments.items:
        # Рассчитываем процент правильно решенных задач
        success_rate = round((correct_tasks or 0) / (total_tasks or 1) * 100, 1)
        
        tournament_list.append({
            'id': tournament.id,
            'name': tournament.title,
            'start_date': tournament.start_date,
            'solved_tasks': solved_tasks or 0,
            'earned_points': earned_points or 0,
            'score': score or 0,
            'place': place,
            'success_rate': success_rate
        })
    
    return render_template('tournament_history.html', 
                         tournaments=tournament_list,
                         pagination=tournaments)

@app.route('/rating')
def rating():
    # Получаем параметр страницы
    page = request.args.get('page', 1, type=int)
    per_page = 20  # количество пользователей на страницу для каждой категории
    
    # Словарь для хранения пользователей по категориям
    users_by_category = {}
    
    # Получаем пользователей для каждой категории
    categories = ['1-2', '3-4', '5-6', '7-8', '9', '10-11']
    for category in categories:
        users_query = User.query.filter_by(is_admin=False, category=category).order_by(User.balance.desc())
        users = users_query.paginate(page=page, per_page=per_page, error_out=False)
        
        # Для каждого пользователя считаем статистику
        for user in users.items:
            # Получаем все решенные задачи пользователя
            solved_tasks = SolvedTask.query.filter_by(user_id=user.id).all()
            total_attempts = len(solved_tasks)
            
            # Считаем количество правильных решений
            correct_attempts = sum(1 for task in solved_tasks if task.is_correct)
            
            # Добавляем атрибуты для отображения в шаблоне
            user.solved_tasks_count = correct_attempts
            user.success_rate = round((correct_attempts / total_attempts * 100) if total_attempts > 0 else 0, 1)
        
        users_by_category[category] = {
            'users': users.items,
            'has_next': users.has_next
        }
    
    # Получаем ранг текущего пользователя
    user_rank = None
    if current_user.is_authenticated and not current_user.is_admin:
        user_rank = get_user_rank(current_user.id)
    
    # Если это AJAX-запрос, возвращаем только данные для запрошенной категории
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        category = request.args.get('category', '1-2')
        users_data = users_by_category.get(category, {'users': [], 'has_next': False})
        
        return jsonify({
            'users': [{
                'username': user.username,
                'balance': user.balance,
                'solved_tasks_count': user.solved_tasks_count,
                'success_rate': user.success_rate,
                'tournaments_count': user.tournaments_count,
                'category_rank': user.category_rank,
                'total_tournament_time': user.total_tournament_time
            } for user in users_data['users']],
            'has_next': users_data['has_next']
        })
    
    return render_template('rating.html', 
                         users_by_category=users_by_category,
                         user_rank=user_rank)

@app.route('/rating/load-more')
def load_more_users():
    page = request.args.get('page', 1, type=int)
    category = request.args.get('category', '1-2')
    per_page = 20
    
    # Получаем пользователей для указанной категории
    users_query = User.query.filter_by(is_admin=False, category=category).order_by(User.balance.desc())
    users = users_query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Для каждого пользователя считаем статистику
    for user in users.items:
        solved_tasks = SolvedTask.query.filter_by(user_id=user.id).all()
        total_attempts = len(solved_tasks)
        correct_attempts = sum(1 for task in solved_tasks if task.is_correct)
        
        user.solved_tasks_count = correct_attempts
        user.success_rate = round((correct_attempts / total_attempts * 100) if total_attempts > 0 else 0, 1)
    
    return jsonify({
        'users': [{
            'username': user.username,
            'balance': user.balance,
            'solved_tasks_count': user.solved_tasks_count,
            'success_rate': user.success_rate,
            'tournaments_count': user.tournaments_count,
            'category_rank': user.category_rank,
            'total_tournament_time': user.total_tournament_time
        } for user in users.items],
        'has_next': users.has_next
    })

@app.route('/shop')
@login_required
def shop():
    prizes = Prize.query.filter(Prize.is_active == True).all()
    settings = ShopSettings.get_settings()
    can_shop = settings.can_user_shop(current_user)
    
    return render_template('shop.html', 
                         prizes=prizes,
                         settings=settings,
                         can_shop=can_shop,
                         cart_items_count=len(current_user.cart_items))

@app.route('/cart')
@login_required
def cart():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    
    # Получаем товары из корзины
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    
    # Считаем общую стоимость
    total_cost = sum(item.prize.points_cost * item.quantity for item in cart_items)
    
    return render_template('cart.html',
                         title='Корзина',
                         cart_items=cart_items,
                         total_cost=total_cost)

@app.route('/add-to-cart', methods=['POST'])
@login_required
def add_to_cart():
    if current_user.is_admin:
        return jsonify({'success': False, 'message': 'Администраторы не могут совершать покупки'})
    
    data = request.get_json()
    prize_id = data.get('prize_id')
    quantity = data.get('quantity', 1)
    
    if not prize_id or not quantity:
        return jsonify({'success': False, 'message': 'Неверные параметры запроса'})
    
    prize = Prize.query.get(prize_id)
    if not prize or not prize.is_active:
        return jsonify({'success': False, 'message': 'Товар не найден'})
    
    # Проверяем, не является ли приз уникальным
    if prize.is_unique:
        # Проверяем, не покупал ли пользователь уже этот приз (все статусы кроме отмененного)
        existing_purchase = PrizePurchase.query.filter(
            PrizePurchase.user_id == current_user.id,
            PrizePurchase.prize_id == prize_id,
            PrizePurchase.status != 'cancelled'  # Проверяем все статусы кроме отмененного
        ).first()
        
        if existing_purchase:
            return jsonify({'success': False, 'message': 'Вы уже приобрели этот уникальный приз'})
        
        # Для уникального приза устанавливаем количество 1
        quantity = 1
    elif prize.quantity > 0 and quantity > prize.quantity:
        return jsonify({'success': False, 'message': 'Запрошенное количество превышает доступное'})
    
    # Проверяем, есть ли уже такой товар в корзине
    cart_item = CartItem.query.filter_by(
        user_id=current_user.id,
        prize_id=prize_id
    ).first()
    
    if cart_item:
        # Если товар уже есть, обновляем количество
        if prize.is_unique:
            return jsonify({'success': False, 'message': 'Этот уникальный приз уже добавлен в корзину'})
        
        new_quantity = cart_item.quantity + quantity
        if prize.quantity > 0 and new_quantity > prize.quantity:
            return jsonify({'success': False, 'message': 'Запрошенное количество превышает доступное'})
        cart_item.quantity = new_quantity
    else:
        # Если товара нет, создаем новую запись
        cart_item = CartItem(
            user_id=current_user.id,
            prize_id=prize_id,
            quantity=quantity
        )
        db.session.add(cart_item)
    
    db.session.commit()
    
    # Получаем обновленное количество товаров в корзине
    cart_items_count = CartItem.query.filter_by(user_id=current_user.id).count()
    
    return jsonify({
        'success': True,
        'message': 'Товар добавлен в корзину',
        'cart_items_count': cart_items_count
    })

@app.route('/update-cart', methods=['POST'])
@login_required
def update_cart():
    if current_user.is_admin:
        return jsonify({'success': False, 'message': 'Администраторы не могут совершать покупки'})
    
    data = request.get_json()
    prize_id = data.get('prize_id')
    quantity = data.get('quantity', 1)
    
    if not prize_id or not quantity:
        return jsonify({'success': False, 'message': 'Неверные параметры запроса'})
    
    prize = Prize.query.get(prize_id)
    if not prize or not prize.is_active:
        return jsonify({'success': False, 'message': 'Товар не найден'})
    
    # Проверяем, не является ли приз уникальным
    if prize.is_unique:
        quantity = 1
    elif prize.quantity > 0 and quantity > prize.quantity:
        return jsonify({'success': False, 'message': 'Запрошенное количество превышает доступное'})
    
    # Находим товар в корзине
    cart_item = CartItem.query.filter_by(
        user_id=current_user.id,
        prize_id=prize_id
    ).first()
    
    if not cart_item:
        return jsonify({'success': False, 'message': 'Товар не найден в корзине'})
    
    # Обновляем количество
    cart_item.quantity = quantity
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Количество товара обновлено'
    })

@app.route('/remove-from-cart', methods=['POST'])
@login_required
def remove_from_cart():
    if current_user.is_admin:
        return jsonify({'success': False, 'message': 'Администраторы не могут совершать покупки'})
    
    data = request.get_json()
    prize_id = data.get('prize_id')
    
    if not prize_id:
        return jsonify({'success': False, 'message': 'Неверные параметры запроса'})
    
    # Находим товар в корзине
    cart_item = CartItem.query.filter_by(
        user_id=current_user.id,
        prize_id=prize_id
    ).first()
    
    if not cart_item:
        return jsonify({'success': False, 'message': 'Товар не найден в корзине'})
    
    # Удаляем товар из корзины
    db.session.delete(cart_item)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Товар удален из корзины'
    })

@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    if current_user.is_admin:
        return jsonify({'success': False, 'message': 'Администраторы не могут совершать покупки'})
    
    settings = ShopSettings.get_settings()
    if not settings.is_open:
        return jsonify({'success': False, 'message': 'Магазин временно закрыт'})
    
    if not settings.can_user_shop(current_user):
        return jsonify({'success': False, 'message': 'У вас нет доступа к магазину'})
    
    data = request.get_json()
    full_name = data.get('full_name')
    phone = data.get('phone')
    address = data.get('address')
    
    if not all([full_name, phone, address]):
        return jsonify({'success': False, 'message': 'Пожалуйста, заполните все поля'})
    
    # Получаем все товары из корзины
    cart_items = CartItem.query.filter_by(user_id=current_user.id).all()
    if not cart_items:
        return jsonify({'success': False, 'message': 'Ваша корзина пуста'})
    
    # Проверяем баланс и доступность товаров
    total_cost = sum(item.prize.points_cost * item.quantity for item in cart_items)
    if current_user.balance < total_cost:
        return jsonify({'success': False, 'message': 'Недостаточно баллов для оформления заказа'})
    
    # Проверяем доступность всех товаров
    for item in cart_items:
        if item.prize.quantity > 0 and item.quantity > item.prize.quantity:
            return jsonify({'success': False, 'message': f'Товар "{item.prize.name}" доступен только в количестве {item.prize.quantity} шт.'})
    
    try:
        # Создаем записи о покупке для каждого товара
        for item in cart_items:
            # Создаем запись о покупке
            purchase = PrizePurchase(
                user_id=current_user.id,
                prize_id=item.prize.id,
                quantity=item.quantity,
                points_cost=item.prize.points_cost * item.quantity,
                full_name=full_name,
                phone=phone,
                address=address,
                status='pending'
            )
            db.session.add(purchase)
            
            # Уменьшаем количество доступных товаров
            if item.prize.quantity > 0:
                item.prize.quantity -= item.quantity
        
        # Списываем баллы
        current_user.balance -= total_cost
        
        # Очищаем корзину
        CartItem.query.filter_by(user_id=current_user.id).delete()
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Заказ успешно оформлен'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Произошла ошибка при оформлении заказа'})

@app.route('/admin/orders')
@login_required
def admin_orders():
    if not current_user.is_admin:
        flash('Недостаточно прав', 'error')
        return redirect(url_for('home'))
    
    # Получаем все заявки, отсортированные по дате (новые сверху)
    orders = PrizePurchase.query.order_by(PrizePurchase.created_at.desc()).all()
    
    return render_template('admin/orders.html', 
                         title='Управление заявками',
                         orders=orders)

@app.route('/admin/orders/<int:order_id>/details')
@login_required
def admin_order_details(order_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Недостаточно прав'})
    
    order = PrizePurchase.query.get_or_404(order_id)
    
    return jsonify({
        'id': order.id,
        'created_at': order.created_at.strftime('%d.%m.%Y %H:%M'),
        'status': order.status,
        'user': {
            'username': order.user.username,
            'email': order.user.email
        },
        'prize': {
            'name': order.prize.name
        },
        'quantity': order.quantity,
        'points_cost': order.points_cost,
        'full_name': order.full_name,
        'phone': order.phone,
        'address': order.address
    })

@app.route('/admin/orders/<int:order_id>/toggle-status', methods=['POST'])
@login_required
def admin_toggle_order_status(order_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Недостаточно прав'})
    
    order = PrizePurchase.query.get_or_404(order_id)
    
    # Меняем статус заказа
    order.status = 'completed' if order.status == 'pending' else 'pending'
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Статус заказа успешно обновлен'
    })

@app.route('/admin/orders/<int:order_id>/delete', methods=['POST'])
@login_required
def admin_delete_order(order_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Недостаточно прав'})
    
    order = PrizePurchase.query.get_or_404(order_id)
    
    # Удаляем заказ
    db.session.delete(order)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Заказ успешно удален'
    })

@app.route('/purchase/<int:purchase_id>/cancel', methods=['POST'])
@login_required
def cancel_purchase(purchase_id):
    purchase = PrizePurchase.query.get_or_404(purchase_id)
    
    # Проверяем, что покупка принадлежит текущему пользователю
    if purchase.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'У вас нет прав для отмены этой покупки'}), 403
    
    # Проверяем, что покупка еще не обработана
    if purchase.status != 'pending':
        return jsonify({'success': False, 'message': 'Нельзя отменить уже обработанную покупку'}), 400
    
    try:
        # Возвращаем баллы пользователю
        current_user.balance += purchase.points_cost
        
        # Обновляем статус покупки
        purchase.status = 'cancelled'
        
        # Возвращаем товары на склад
        purchase.prize.quantity += purchase.quantity
        
        db.session.commit()
        return jsonify({
            'success': True, 
            'message': 'Покупка успешно отменена. Баллы возвращены на ваш счет.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Произошла ошибка при отмене покупки'}), 500

@app.route('/admin/shop/settings')
@login_required
def admin_shop_settings():
    if not current_user.is_admin:
        flash('Недостаточно прав', 'error')
        return redirect(url_for('home'))
    
    settings = ShopSettings.get_settings()
    return render_template('admin/shop_settings.html', 
                         title='Настройки магазина',
                         settings=settings)

@app.route('/admin/shop/settings/update', methods=['POST'])
@login_required
def admin_update_shop_settings():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Недостаточно прав'})
    
    settings = ShopSettings.get_settings()
    
    # Обновляем настройки
    settings.is_open = 'is_open' in request.form
    
    # Обновляем проценты для каждой категории
    categories = ['1_2', '3_4', '5_6', '7_8', '9', '10_11']
    for category in categories:
        try:
            percentage = int(request.form.get(f'top_users_percentage_{category}', 100))
            if percentage < 1 or percentage > 100:
                raise ValueError
            setattr(settings, f'top_users_percentage_{category}', percentage)
        except ValueError:
            return jsonify({'success': False, 'message': f'Некорректное значение процента для категории {category.replace("_", "-")}'})
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Настройки магазина успешно обновлены'
    })

@app.route('/admin/tournaments/settings', methods=['GET', 'POST'])
@login_required
def tournament_settings():
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    settings = TournamentSettings.get_settings()
    
    if request.method == 'POST':
        settings.is_season_active = request.form.get('is_season_active') == 'on'
        settings.closed_season_message = request.form.get('closed_season_message')
        settings.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Настройки турниров успешно обновлены', 'success')
        return redirect(url_for('tournament_settings'))
    
    return render_template('admin/tournament_settings.html', settings=settings)

@app.before_first_request
def clear_sessions():
    # Очищаем все токены сессий при запуске приложения
    User.query.update({User.session_token: None, User.last_activity: None})
    db.session.commit()

@app.route('/change-password', methods=['POST'])
@login_required
def change_password():
    data = request.get_json()
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    
    if not current_password or not new_password:
        return jsonify({
            'success': False,
            'message': 'Пожалуйста, заполните все поля'
        })
    
    if not current_user.check_password(current_password):
        return jsonify({
            'success': False,
            'message': 'Неверный текущий пароль'
        })
    
    if not is_password_strong(new_password):
        return jsonify({
            'success': False,
            'message': 'Пароль должен содержать минимум 8 символов, включая цифры и буквы'
        })
    
    current_user.set_password(new_password)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Пароль успешно изменен'
    })

@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy_policy.html', title='Политика конфиденциальности')

def update_category_ranks():
    """Обновляет рейтинг пользователей внутри их возрастных категорий"""
    categories = ['1-2', '3-4', '5-6', '7-8', '9', '10-11']
    
    for category in categories:
        # Получаем всех пользователей данной категории, отсортированных по балансу и времени
        users = User.query.filter_by(category=category)\
            .order_by(User.balance.desc(), User.total_tournament_time.asc())\
            .all()
        
        # Обновляем рейтинг для каждого пользователя
        current_rank = 1
        current_balance = None
        current_time = None
        same_rank_count = 0
        
        for user in users:
            # Если баланс и время отличаются от предыдущего пользователя
            if current_balance != user.balance or current_time != user.total_tournament_time:
                current_rank += same_rank_count
                same_rank_count = 0
                current_balance = user.balance
                current_time = user.total_tournament_time
            
            user.category_rank = current_rank
            same_rank_count += 1
        
        db.session.commit()

# Добавляем вызов функции обновления рейтинга после изменения баланса пользователя
@app.after_request
def after_request(response):
    if response.status_code == 200 and request.endpoint in ['submit_answer', 'buy_tickets', 'use_tickets']:
        update_category_ranks()
    return response

@app.route('/update-profile', methods=['POST'])
@login_required
def update_profile():
    data = request.get_json()
    
    # Получаем данные из запроса
    phone = data.get('phone')
    category = data.get('category')
    new_password = data.get('new_password')
    
    # Проверяем обязательные поля
    if not phone or not category:
        return jsonify({'success': False, 'message': 'Пожалуйста, заполните все обязательные поля'})
    
    # Проверяем формат телефона
    if not re.match(r'^\+375\d{9}$', phone):
        return jsonify({'success': False, 'message': 'Неверный формат номера телефона'})
    
    # Проверяем категорию
    valid_categories = ['1-2', '3-4', '5-6', '7-8', '9', '10-11']
    if category not in valid_categories:
        return jsonify({'success': False, 'message': 'Неверная категория'})
    
    # Проверяем статус сезона
    settings = TournamentSettings.get_settings()
    if settings.is_season_active and category != current_user.category:
        return jsonify({'success': False, 'message': 'Изменение группы недоступно во время активного сезона'})
    
    try:
        # Обновляем данные пользователя
        current_user.phone = phone
        current_user.category = category
        
        # Если указан новый пароль, обновляем его
        if new_password:
            current_user.set_password(new_password)
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Профиль успешно обновлен'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Произошла ошибка при обновлении профиля'})

@app.route('/admin/users/clear-data', methods=['POST'])
@login_required
def admin_clear_user_data():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Доступ запрещен'}), 403
    
    admin_password = request.form.get('admin_password')
    if not admin_password:
        return jsonify({'success': False, 'message': 'Не указан пароль администратора'}), 400
    
    if not current_user.check_password(admin_password):
        return jsonify({'success': False, 'message': 'Неверный пароль администратора'}), 400
    
    try:
        # Очищаем счет и время решения задач для всех пользователей
        users = User.query.filter_by(is_admin=False).all()
        for user in users:
            user.balance = 0
            user.total_tournament_time = 0
            user.tournaments_count = 0  # Очищаем количество турниров
        
        # Очищаем историю решенных задач
        SolvedTask.query.delete()
        
        # Очищаем историю участия в турнирах
        TournamentParticipation.query.delete()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Данные пользователей успешно очищены'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Произошла ошибка при очистке данных: {str(e)}'
        }), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_admin_user()
        cleanup_scheduler_jobs()  # Сначала очищаем все задачи
        restore_scheduler_jobs()  # Затем восстанавливаем нужные

    app.run(host='0.0.0.0', port=8000, debug=True)