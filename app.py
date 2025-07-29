from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from sqlalchemy.testing import fails
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import logging
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
from email_sender import add_to_queue, add_bulk_to_queue, start_email_worker
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
import threading
from s3_utils import upload_file_to_s3, delete_file_from_s3, get_s3_url, get_file_url
import platform
import re
import atexit
import signal
import subprocess
import socket
import uuid
import json
import hashlib
import smtplib
from dotenv import load_dotenv
load_dotenv()
# Переменная окружения для уникального идентификатора сервера
# В продакшене должна быть установлена в .env файле
SERVER_ID = os.environ.get('SERVER_ID')
DEBAG = bool(os.environ.get('DEBAG'))


# Константы для реферальной системы
REFERRAL_BONUS_POINTS = 150  # Бонусные баллы за приглашенного пользователя
REFERRAL_BONUS_TICKETS = 23   # Бонусные жетоны за приглашенного пользователя
# Получаем количество ядер CPU
CPU_COUNT = multiprocessing.cpu_count()
# Создаем пул потоков
thread_pool = ThreadPoolExecutor(max_workers=CPU_COUNT * 2)

app = Flask(__name__)
#app.config['SECRET_KEY'] = os.urandom(32).hex()
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
#app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:1234@localhost:5432/school_tournaments'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 300,  # Увеличиваем базовый размер пула для 2000+ пользователей
    'max_overflow': 200,  # Увеличиваем дополнительные соединения при пиковой нагрузке
    'pool_timeout': 30,  # Уменьшаем таймаут ожидания соединения из пула
    'pool_recycle': 1800,  # Пересоздание соединений каждые 30 минут
    'pool_pre_ping': True,  # Проверка соединений перед использованием
    'echo': False,  # Отключение вывода SQL-запросов в консоль
    'pool_use_lifo': True,  # Используем LIFO для пула соединений
    'connect_args': {
        'connect_timeout': 10,  # Таймаут подключения к БД
        'application_name': 'math_tur_app',  # Имя приложения для мониторинга
        'options': '-c statement_timeout=30000 -c lock_timeout=10000'  # Устанавливаем таймауты на уровне соединения
    }
}
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=3650)  # 10 лет - практически неограниченное время

# Настройки для многопоточности
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['THREAD_POOL_SIZE'] = CPU_COUNT * 2

# Настройки для отправки email
app.config['MAIL_SERVER'] = 'mail.liga-znatokov.by'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True  # Для порта 465 используется SSL, а не TLS
app.config['MAIL_USE_TLS'] = False  # Отключаем TLS для порта 465
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')

# Настройки сессии
app.config['SESSION_COOKIE_SECURE'] = bool(os.environ.get('SESSION_COOKIE_SECURE'))  # Куки только по HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Защита от XSS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Защита от CSRF
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=3650)  # 10 лет
app.config['SESSION_COOKIE_NAME'] = 'math_tur_session'  # Уникальное имя куки

mail = Mail(app)
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите в систему для доступа к этой странице.'
login_manager.login_message_category = 'info'

def generate_session_token():
    """Генерирует уникальный токен сессии"""
    return secrets.token_urlsafe(32)

def create_user_session(user_id, device_info=None, user_type='user', teacher_id=None):
    """Создает новую сессию пользователя или учителя"""
    if user_type == 'teacher':
        # Деактивируем все существующие сессии учителя
        UserSession.query.filter_by(teacher_id=teacher_id, user_type='teacher').update({'is_active': False})
        
        # Создаем новую сессию учителя
        session_token = generate_session_token()
        new_session = UserSession(
            teacher_id=teacher_id,
            user_type='teacher',
            is_active=True,
            session_token=session_token,
            device_info=device_info
        )
    else:
        # Деактивируем все существующие сессии пользователя
        UserSession.query.filter_by(user_id=user_id, user_type='user').update({'is_active': False})
        
        # Создаем новую сессию пользователя
        session_token = generate_session_token()
        new_session = UserSession(
            user_id=user_id,
            user_type='user',
            is_active=True,
            session_token=session_token,
            device_info=device_info
        )
    
    db.session.add(new_session)
    db.session.commit()
    return session_token

def deactivate_user_session(user_id, user_type='user', teacher_id=None):
    """Деактивирует все сессии пользователя или учителя"""
    if user_type == 'teacher':
        UserSession.query.filter_by(teacher_id=teacher_id, user_type='teacher').update({'is_active': False})
    else:
        UserSession.query.filter_by(user_id=user_id, user_type='user').update({'is_active': False})
    db.session.commit()

def is_session_active(user_id, session_token, user_type='user', teacher_id=None):
    """Проверяет, активна ли сессия пользователя или учителя"""
    if user_type == 'teacher':
        session = UserSession.query.filter_by(
            teacher_id=teacher_id,
            session_token=session_token,
            user_type='teacher',
            is_active=True
        ).first()
    else:
        session = UserSession.query.filter_by(
            user_id=user_id,
            session_token=session_token,
            user_type='user',
            is_active=True
        ).first()
    return session is not None

def update_session_activity(session_token):
    """Обновляет время последней активности сессии"""
    session = UserSession.query.filter_by(session_token=session_token).first()
    if session:
        session.update_last_active()
        db.session.commit()

# Инициализация планировщика
scheduler = BackgroundScheduler(timezone='Europe/Moscow')
scheduler.start()
print(scheduler.timezone)

# Запускаем обработчик очереди писем
start_email_worker()

# Создаем локальное хранилище для потоков
thread_local = threading.local()

def get_db():
    """Получает или создает соединение с базой данных для текущего потока"""
    if not hasattr(thread_local, 'db'):
        thread_local.db = db.create_scoped_session()
    return thread_local.db

def update_tournament_status():
    now = datetime.now()  # Московское время
    tournaments = Tournament.query.filter(Tournament.status != 'finished').all()
    
    for tournament in tournaments:
        if tournament.start_date <= now and now <= tournament.start_date + timedelta(minutes=tournament.duration):
            tournament.status = 'started'
        elif now > tournament.start_date + timedelta(minutes=tournament.duration):
            tournament.status = 'finished'
    
    db.session.commit()



def cleanup_scheduler_jobs():
    """Очищает все задачи планировщика перед восстановлением"""
    try:
        scheduler.remove_all_jobs()
    except Exception as e:
        pass

@app.before_request
def before_request():
    """Инициализация перед каждым запросом"""
    # Создаем сессию базы данных для текущего потока
    thread_local.db = db.create_scoped_session()
    
    # Обновляем статус турниров
    update_tournament_status()
    
    # Проверяем сессию для авторизованных пользователей
    if current_user.is_authenticated:
        session_token = session.get('session_token')
        user_type = session.get('user_type', 'user')
        
        # Определяем параметры для проверки сессии
        if user_type == 'teacher':
            # Для учителей
            if not session_token or not is_session_active(None, session_token, 'teacher', current_user.id):
                # Если сессия недействительна, выходим из системы
                deactivate_user_session(None, 'teacher', current_user.id)
                session.pop('session_token', None)
                session.pop('user_type', None)
                logout_user()
                flash('Ваша сессия истекла или была завершена на другом устройстве. Пожалуйста, войдите снова.', 'error')
                return redirect(url_for('login'))
        else:
            # Для обычных пользователей
            if not session_token or not is_session_active(current_user.id, session_token, 'user'):
                # Если сессия недействительна, выходим из системы
                deactivate_user_session(current_user.id, 'user')
                session.pop('session_token', None)
                session.pop('user_type', None)
                logout_user()
                flash('Ваша сессия истекла или была завершена на другом устройстве. Пожалуйста, войдите снова.', 'error')
                return redirect(url_for('login'))
        
        # Обновляем время последней активности
        update_session_activity(session_token)
        # Делаем сессию постоянной
        session.permanent = True

@app.teardown_request
def teardown_request(exception=None):
    """Очистка после каждого запроса"""
    # Закрываем сессию базы данных
    if hasattr(thread_local, 'db'):
        thread_local.db.remove()

@app.teardown_appcontext
def shutdown_session(exception=None):
    """Очистка при завершении контекста приложения"""
    db.session.remove()

def run_in_thread(func, *args, **kwargs):
    """Запускает функцию в отдельном потоке"""
    return thread_pool.submit(func, *args, **kwargs)

# Модифицируем функции, которые могут выполняться асинхронно

def update_user_activity_async(user_id):
    """Асинхронное обновление активности пользователя"""
    def _update():
        with app.app_context():
            user = User.query.get(user_id)
            if user:
                user.last_activity = datetime.now()
                db.session.commit()
    return run_in_thread(_update)

def start_tournament_job(tournament_id):
    try:
        with app.app_context():
            tournament = Tournament.query.get(tournament_id)
            if tournament:
                tournament.status = 'started'
                db.session.commit()
                
                # Удаляем запись о задаче из БД после выполнения
                job_id = f'start_tournament_{tournament_id}'
                scheduler_job = SchedulerJob.query.filter_by(job_id=job_id).first()
                if scheduler_job:
                    db.session.delete(scheduler_job)
                    db.session.commit()
                    
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка в start_tournament_job: {e}")

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
                
                # Для каждой категории вычисляем места отдельно
                from collections import defaultdict
                participations_by_category = defaultdict(list)
                participations = TournamentParticipation.query.filter_by(tournament_id=tournament_id).all()
                for p in participations:
                    if p.user and p.user.category:
                        participations_by_category[p.user.category].append(p)
                current_time = datetime.now()
                for category, plist in participations_by_category.items():
                    # Сортируем по score (баллы), затем по времени участия (меньше — выше)
                    plist_sorted = sorted(plist, key=lambda p: (-p.score, (p.end_time or current_time) - (p.start_time or current_time)))
                    for rank, participation in enumerate(plist_sorted, 1):
                        participation.place = rank
                        # Устанавливаем время окончания участия, если оно еще не установлено
                        if not participation.end_time:
                            participation.end_time = current_time
                        # Вычисляем время участия в турнире и добавляем к общему времени пользователя
                        if participation.start_time and participation.end_time:
                            time_spent = (participation.end_time - participation.start_time).total_seconds()
                            participation.user.total_tournament_time += int(time_spent)
                # Обновляем рейтинги в категориях
                update_category_ranks()
                
                db.session.commit()
                
                # Удаляем запись о задаче из БД после выполнения
                job_id = f'end_tournament_{tournament_id}'
                scheduler_job = SchedulerJob.query.filter_by(job_id=job_id).first()
                if scheduler_job:
                    db.session.delete(scheduler_job)
                    db.session.commit()
                    
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка в end_tournament_job: {e}")

def add_scheduler_job(job_func, run_date, tournament_id, job_type, interval_hours=None):
    """Добавляет задачу в планировщик и сохраняет информацию в БД"""
    job_id = f'{job_type}_tournament_{tournament_id}' if tournament_id else f'{job_type}'
    
    try:
        # Проверяем, не существует ли уже такая задача в БД
        existing_job = SchedulerJob.query.filter_by(job_id=job_id).first()
        if existing_job:
            # Задача уже существует, не добавляем дубликат
            return False
        
        if interval_hours:
            # Интервальная задача (например, очистка сессий)
            scheduler.add_job(
                job_func,
                trigger='interval',
                hours=interval_hours,
                id=job_id,
                replace_existing=True
            )
        else:
            # Обычная задача с конкретным временем выполнения
            scheduler.add_job(
                job_func,
                trigger=DateTrigger(run_date=run_date),
                args=[tournament_id] if tournament_id else [],
                id=job_id,
                replace_existing=True
            )
        
        # Сохраняем информацию о задаче в БД
        scheduler_job = SchedulerJob(
            job_id=job_id,
            job_type=job_type,
            tournament_id=tournament_id,
            run_date=run_date,
            is_active=True,
            server_id=SERVER_ID
        )
        db.session.add(scheduler_job)
        db.session.commit()
        
        return True
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при добавлении задачи в планировщик: {e}")
        return False

def remove_scheduler_job(tournament_id, job_type):
    """Удаляет задачу из планировщика и БД"""
    job_id = f'{job_type}_tournament_{tournament_id}'
    
    try:
        # Удаляем задачу из планировщика
        scheduler.remove_job(job_id)
        
        # Удаляем запись из БД
        scheduler_job = SchedulerJob.query.filter_by(job_id=job_id).first()
        if scheduler_job:
            db.session.delete(scheduler_job)
            db.session.commit()
            
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при удалении задачи из планировщика: {e}")

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    hashed_password = db.Column(db.String(128), nullable=False, index=True)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    student_name = db.Column(db.String(100), nullable=True)  # Фамилия и имя учащегося
    parent_name = db.Column(db.String(100), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=False, index=True)
    is_blocked = db.Column(db.Boolean, default=False, index=True)
    block_reason = db.Column(db.Text, nullable=True)
    email_confirmation_token = db.Column(db.String(100), unique=True, nullable=True, index=True)
    session_token = db.Column(db.String(100), unique=True, nullable=True, index=True)
    temp_password = db.Column(db.String(128), nullable=True)
    reset_password_token = db.Column(db.String(100), unique=True, nullable=True, index=True)
    reset_password_token_expires = db.Column(db.DateTime, nullable=True)
    category = db.Column(db.String(50), nullable=True, index=True)
    category_rank = db.Column(db.Integer, nullable=True, index=True)
    balance = db.Column(db.Integer, default=0)
    tickets = db.Column(db.Integer, default=0)
    tournaments_count = db.Column(db.Integer, default=0)
    total_tournament_time = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
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
    
    educational_institution_id = db.Column(db.Integer, db.ForeignKey('educational_institutions.id'), nullable=True)
    educational_institution = db.relationship('EducationalInstitution', backref=db.backref('users', lazy=True))

    # Связь с учителем
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=True, index=True)
    teacher = db.relationship('Teacher', backref=db.backref('students', lazy=True))

    def set_password(self, password):
        self.hashed_password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.hashed_password, password)

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
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

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
    topic = db.Column(db.String(200), nullable=True)  # Тема задачи
    solution_text = db.Column(db.Text, nullable=True)  # Текст решения
    solution_image = db.Column(db.String(200), nullable=True)  # Изображение решения
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    tournament = db.relationship('Tournament', backref=db.backref('tasks', lazy=True))

class TicketPurchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    discount = db.Column(db.Integer, default=0)  # Скидка в процентах
    purchase_date = db.Column(db.DateTime, default=datetime.now)
    
    # Поля для платежей
    payment_system = db.Column(db.String(20), nullable=True)  # 'yukassa', 'express_pay' или 'bepaid'
    payment_id = db.Column(db.String(100), nullable=True, index=True)  # ID платежа в платежной системе
    payment_status = db.Column(db.String(20), default='pending', index=True)  # pending, waiting_for_capture, succeeded, canceled, failed
    payment_method = db.Column(db.String(50), nullable=True)  # Способ оплаты (epos, erip)
    currency = db.Column(db.String(3), default='RUB')  # Валюта платежа
    payment_url = db.Column(db.String(500), nullable=True)  # URL для оплаты
    payment_created_at = db.Column(db.DateTime(), nullable=True)  # Время создания платежа
    payment_confirmed_at = db.Column(db.DateTime(), nullable=True)  # Время подтверждения платежа
    
    user = db.relationship('User', backref=db.backref('ticket_purchases', lazy=True))

class TournamentParticipation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id', ondelete='CASCADE'), nullable=False)
    score = db.Column(db.Integer, default=0)
    place = db.Column(db.Integer)
    participation_date = db.Column(db.DateTime, default=datetime.now)
    start_time = db.Column(db.DateTime, default=datetime.now)  # Время начала участия в турнире
    end_time = db.Column(db.DateTime, nullable=True)  # Время окончания участия в турнире
    
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
    solved_at = db.Column(db.DateTime, default=datetime.now)
    is_correct = db.Column(db.Boolean, default=False)
    user_answer = db.Column(db.String(200), nullable=True)  # Ответ пользователя
    
    user = db.relationship('User', backref=db.backref('solved_tasks', lazy=True, cascade='all, delete-orphan'))
    task = db.relationship('Task', backref=db.backref('solutions', lazy=True, cascade='all, delete-orphan'))

class TicketPackage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    price = db.Column(db.Float, nullable=False)  # Базовая цена за 1 билет
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

class TicketDiscount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    min_quantity = db.Column(db.Integer, nullable=False)  # Минимальное количество билетов для скидки
    discount = db.Column(db.Integer, nullable=False)  # Скидка в процентах
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

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
    created_at = db.Column(db.DateTime, default=datetime.now)

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
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    
    user = db.relationship('User', backref=db.backref('prize_purchases', lazy=True))
    prize = db.relationship('Prize', backref=db.backref('purchases', lazy=True))

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    prize_id = db.Column(db.Integer, db.ForeignKey('prize.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    user = db.relationship('User', backref=db.backref('cart_items', lazy=True))
    prize = db.relationship('Prize', backref=db.backref('cart_items', lazy=True))

class ShopSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_open = db.Column(db.Boolean, default=True)
    # Процент лучших пользователей для каждой категории
    top_users_percentage_1_2 = db.Column(db.Integer, default=100)  # 1-2 классы
    top_users_percentage_3 = db.Column(db.Integer, default=100)    # 3 класс
    top_users_percentage_4 = db.Column(db.Integer, default=100)    # 4 класс
    top_users_percentage_5 = db.Column(db.Integer, default=100)    # 5 класс
    top_users_percentage_6 = db.Column(db.Integer, default=100)    # 6 класс
    top_users_percentage_7 = db.Column(db.Integer, default=100)    # 7 класс
    top_users_percentage_8 = db.Column(db.Integer, default=100)    # 8 класс
    top_users_percentage_9 = db.Column(db.Integer, default=100)    # 9 класс
    top_users_percentage_10 = db.Column(db.Integer, default=100)   # 10 класс
    top_users_percentage_11 = db.Column(db.Integer, default=100)   # 11 класс
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

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
    allow_category_change = db.Column(db.Boolean, default=True)  # Разрешить изменение группы
    closed_season_message = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.now)

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
    # Проверяем, является ли ID учителем (начинается с 't')
    if user_id.startswith('t'):
        teacher_id = int(user_id[1:])  # Убираем префикс 't'
        return Teacher.query.get(teacher_id)
    else:
        return User.query.get(int(user_id))

def create_admin_user():
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(
            username='admin',
            email='admin@school-tournaments.ru',
            phone='+375000000000',  # Добавляем номер телефона
            student_name='Администратор',  # Добавляем имя учащегося
            parent_name='Администратор',  # Добавляем имя представителя
            category='11',  # Исправляем категорию на допустимую
            is_admin=True,
            is_active=True  # Устанавливаем is_active=True для администратора
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

def send_admin_notification(subject, message, recipient_email=None):
    """Отправка уведомления всем администраторам или конкретному получателю"""
    try:
        if recipient_email:
            # Отправляем конкретному получателю
            msg = Message(subject,
                         sender=app.config['MAIL_USERNAME'],
                         recipients=[recipient_email])
            msg.body = message
            add_to_queue(app, mail, msg)
        else:
            # Отправляем всем администраторам
            admins = User.query.filter_by(is_admin=True, is_active=True).all()
            
            if not admins:
                return
            
            # Создаем сообщения для всех администраторов
            messages = []
            for admin in admins:
                msg = Message(subject,
                             sender=app.config['MAIL_USERNAME'],
                             recipients=[admin.email])
                msg.body = message
                messages.append(msg)
            
            # Отправляем массово через очередь
            add_bulk_to_queue(app, mail, messages)
        
    except Exception as e:
        print(f"Ошибка отправки уведомления: {e}")

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

def send_teacher_confirmation_email(teacher):
    """Отправляет письмо с подтверждением регистрации для учителя"""
    token = teacher.generate_confirmation_token()
    msg = Message('Подтверждение регистрации учителя',
                  sender=app.config['MAIL_USERNAME'],
                  recipients=[teacher.email])
    msg.body = f'''Уважаемый {teacher.full_name}!

Для подтверждения вашей регистрации как учителя перейдите по следующей ссылке:
{url_for('confirm_teacher_email', token=token, _external=True)}

После подтверждения вы получите доступ к личному кабинету учителя с возможностью:
- Создавать пригласительные ссылки для учеников
- Отслеживать прогресс приглашенных учеников
- Участвовать в бонусной программе

Если вы не регистрировались на нашем сайте, просто проигнорируйте это письмо.

С уважением,
Команда Math Tournament Platform
'''
    add_to_queue(app, mail, msg)

def send_teacher_credentials_email(teacher, password):
    """Отправляет учителю письмо с паролем после подтверждения email"""
    msg = Message('Ваши данные для входа',
                  sender=app.config['MAIL_USERNAME'],
                  recipients=[teacher.email])
    msg.body = f'''Уважаемый {teacher.full_name}!

Ваш email успешно подтвержден! Теперь вы можете войти в систему как учитель.

Ваши данные для входа:
Логин: {teacher.username}
Пароль: {password}

Обязательно смените пароль после первого входа в систему!

Для входа как учитель:
1. Перейдите на страницу входа
2. Введите свои данные
3. Обязательно поставьте галочку "Я учитель"

В личном кабинете учителя вы сможете:
- Создавать пригласительные ссылки для учеников
- Отслеживать прогресс приглашенных учеников
- Просматривать статистику участия в турнирах
- Участвовать в бонусной программе

С уважением,
Команда Лиги Знатоков
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

def send_reset_password_email(user):
    token = secrets.token_urlsafe(32)
    user.reset_password_token = token
    user.reset_password_token_expires = datetime.now() + timedelta(hours=1)
    db.session.commit()
    
    msg = Message('Сброс пароля',
                  sender=app.config['MAIL_USERNAME'],
                  recipients=[user.email])
    msg.body = f'''Для сброса пароля перейдите по следующей ссылке:
{url_for('reset_password', token=token, _external=True)}

Ссылка действительна в течение 1 часа.

Если вы не запрашивали сброс пароля, проигнорируйте это письмо.
'''
    add_to_queue(app, mail, msg)

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        
        if user:
            send_reset_password_email(user)
            flash('Инструкции по сбросу пароля отправлены на ваш email. Проверьте также папку "Спам", если письмо не пришло в течение нескольких минут.', 'success')
        else:
            flash('Пользователь с таким email не найден', 'danger')
        
        return redirect(url_for('login'))
    
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_password_token=token).first()
    
    if not user or not user.reset_password_token_expires or user.reset_password_token_expires < datetime.now():
        flash('Недействительная или устаревшая ссылка для сброса пароля', 'danger')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Пароли не совпадают', 'danger')
            return redirect(url_for('reset_password', token=token))
        
        is_strong, message = is_password_strong(password)
        if not is_strong:
            flash(message, 'danger')
            return redirect(url_for('reset_password', token=token))
        
        user.set_password(password)
        user.reset_password_token = None
        user.reset_password_token_expires = None
        
        # Очищаем токен сессии и время последней активности
        user.session_token = None
        user.last_activity = None
        
        db.session.commit()
        
        # Если пользователь был авторизован, выходим из системы
        if current_user.is_authenticated:
            session.pop('session_token', None)
            logout_user()
        
        flash('Пароль успешно изменен. Пожалуйста, войдите в систему с новым паролем.', 'success')
        return redirect(url_for('login'))
    
    return render_template('reset_password.html', token=token)

@app.route('/')
def home():
    settings = TournamentSettings.get_settings()
    if settings.is_season_active:
        # Получаем текущее время
        current_time = datetime.now()
        
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
        
        # Получаем статистику для информационного окна
        # Топ-10 лучших игроков по общему счету (balance)
        top_players = User.query.filter(
            User.is_active == True,
            User.is_admin == False
        ).order_by(User.balance.desc()).limit(10).all()
        
        # Общая статистика
        total_tournaments = Tournament.query.filter(
            Tournament.status == 'finished'
        ).count()
        
        avg_tournament_score = db.session.query(db.func.avg(TournamentParticipation.score)).scalar() or 0
        
        max_tournament_score = db.session.query(db.func.max(TournamentParticipation.score)).scalar() or 0
        
        total_solved_tasks = SolvedTask.query.filter(
            SolvedTask.is_correct == True
        ).count()
        

        
        return render_template('index.html',
                             next_tournament=next_tournament,
                             now=current_time,
                             is_tournament_running=is_tournament_running,
                             top_players=top_players,
                             total_tournaments=total_tournaments,
                             avg_tournament_score=round(avg_tournament_score, 1),
                             max_tournament_score=max_tournament_score,
                             total_solved_tasks=total_solved_tasks)
    else:
        return render_template('index_close.html', message=settings.closed_season_message)

@app.route('/about')
def about():
    return render_template('about.html', title='О нас')

@app.route('/cooperation')
def cooperation():
    """Страница сотрудничества с учителями"""
    return render_template('cooperation.html', title='Сотрудничество')

@app.route('/news')
def news():
    # Получаем номер страницы из параметров запроса
    page = request.args.get('page', 1, type=int)
    per_page = 5  # Количество новостей на странице
    
    # Получаем опубликованные новости с пагинацией, отсортированные по дате создания (новые сначала)
    pagination = News.query.filter_by(is_published=True).order_by(News.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    news_list = pagination.items
    
    return render_template('news.html', title='Новости', news_list=news_list, pagination=pagination, now=datetime.now())

@app.route('/news/<int:news_id>')
def news_detail(news_id):
    # Получаем конкретную новость по ID
    news_item = News.query.filter_by(id=news_id, is_published=True).first_or_404()
    
    # Получаем список других новостей для боковой панели
    other_news = News.query.filter(
        News.is_published == True,
        News.id != news_id
    ).order_by(News.created_at.desc()).limit(5).all()
    
    return render_template('news_detail.html', title=news_item.title, news=news_item, news_list=other_news)

def parse_user_agent(user_agent_string):
    """Парсит User-Agent строку и возвращает информацию об устройстве в читаемом формате"""
    # Определяем операционную систему
    os_info = "Неизвестная ОС"
    if "Windows" in user_agent_string:
        os_info = "Windows"
        if "Windows NT 10.0" in user_agent_string:
            os_info = "Windows 10"
        elif "Windows NT 6.3" in user_agent_string:
            os_info = "Windows 8.1"
        elif "Windows NT 6.2" in user_agent_string:
            os_info = "Windows 8"
        elif "Windows NT 6.1" in user_agent_string:
            os_info = "Windows 7"
    elif "Mac OS X" in user_agent_string:
        os_info = "macOS"
    elif "Linux" in user_agent_string:
        os_info = "Linux"
    elif "Android" in user_agent_string:
        os_info = "Android"
    elif "iPhone" in user_agent_string or "iPad" in user_agent_string:
        os_info = "iOS"

    # Определяем браузер
    browser = "Неизвестный браузер"
    if "Chrome" in user_agent_string and "Chromium" not in user_agent_string:
        browser = "Chrome"
    elif "Firefox" in user_agent_string:
        browser = "Firefox"
    elif "Safari" in user_agent_string and "Chrome" not in user_agent_string:
        browser = "Safari"
    elif "Edge" in user_agent_string:
        browser = "Microsoft Edge"
    elif "Opera" in user_agent_string or "OPR" in user_agent_string:
        browser = "Opera"

    # Определяем тип устройства
    device_type = "Компьютер"
    if "Mobile" in user_agent_string:
        device_type = "Мобильный телефон"
    elif "Tablet" in user_agent_string or "iPad" in user_agent_string:
        device_type = "Планшет"

    return {
        "os": os_info,
        "browser": browser,
        "device_type": device_type,
        "full_info": user_agent_string
    }

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Проверяем, не заблокирован ли вход
    if is_login_blocked():
        blocked_until = datetime.fromtimestamp(float(request.cookies.get(LOGIN_BLOCKED_UNTIL_COOKIE)))
        remaining_time = blocked_until - datetime.now()
        minutes = int(remaining_time.total_seconds() / 60)
        flash(f'Слишком много неудачных попыток входа. Попробуйте снова через {minutes} минут.', 'error')
        return render_template('login.html')

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        is_teacher = request.form.get('is_teacher') == 'on'
        device_info = request.user_agent.string

        # Определяем, в какой таблице искать пользователя
        if is_teacher:
            user = Teacher.query.filter(Teacher.username.ilike(username)).first()
        else:
            user = User.query.filter(User.username.ilike(username)).first()
        
        if user and user.check_password(password):
            if user.is_blocked:
                flash('Ваш аккаунт заблокирован. Причина: ' + user.block_reason, 'error')
                return increment_login_attempts()
            
            if not user.is_active:
                flash('Пожалуйста, подтвердите ваш email перед входом.', 'error')
                return increment_login_attempts()
            
            # Проверяем, есть ли активная сессия
            if is_teacher:
                active_session = UserSession.query.filter_by(teacher_id=user.id, user_type='teacher', is_active=True).first()
            else:
                active_session = UserSession.query.filter_by(user_id=user.id, user_type='user', is_active=True).first()
            
            if active_session:
                # Парсим информацию об устройстве
                device_details = parse_user_agent(active_session.device_info or "Неизвестное устройство")
                flash(f'Вы уже вошли в систему с другого устройства. Информация об устройстве: {device_details["os"]}, {device_details["browser"]}, {device_details["device_type"]}', 'error')
                return increment_login_attempts()
            
            # Создаем новую сессию
            if is_teacher:
                session_token = create_user_session(None, device_info, 'teacher', user.id)
            else:
                session_token = create_user_session(user.id, device_info, 'user')
            
            # Сохраняем токен в сессии Flask и делаем её постоянной
            session['session_token'] = session_token
            session['user_type'] = 'teacher' if is_teacher else 'user'
            session.permanent = True
            
            login_user(user)
            user.last_login = datetime.now()
            db.session.commit()
            
            flash('Вы успешно вошли в систему!', 'success')
            # Сбрасываем счетчик попыток входа
            
            # Определяем куда перенаправить пользователя
            if is_teacher:
                redirect_url = url_for('teacher_profile')
            else:
                redirect_url = url_for('profile')
            
            response = make_response(redirect(redirect_url))
            response.set_cookie(
                LOGIN_ATTEMPTS_COOKIE,
                '0',  # Явно устанавливаем 0
                max_age=0,
                secure=False,
                httponly=True,
                samesite='Lax'
            )
            response.set_cookie(
                LOGIN_BLOCKED_UNTIL_COOKIE,
                '',
                max_age=0,
                secure=False,
                httponly=True,
                samesite='Lax'
            )
            return response
        else:
            attempts = get_login_attempts() + 1
            if attempts >= MAX_LOGIN_ATTEMPTS:
                flash(f'Слишком много неудачных попыток входа. Попробуйте снова через {LOGIN_TIMEOUT // 60} минут.', 'error')
                return block_login()
            else:
                flash(f'Неверное имя пользователя или пароль. Осталось попыток: {MAX_LOGIN_ATTEMPTS - attempts}', 'error')
                return increment_login_attempts()
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    # Определяем тип пользователя и деактивируем сессию
    user_type = session.get('user_type', 'user')
    if user_type == 'teacher':
        deactivate_user_session(None, 'teacher', current_user.id)
    else:
        deactivate_user_session(current_user.id, 'user')
    
    # Очищаем сессию Flask
    session.pop('session_token', None)
    session.pop('user_type', None)
    
    logout_user()
    flash('Вы успешно вышли из системы', 'success')
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
    search_query = sanitize_input(request.args.get('search', ''), 100)
    search_type = request.args.get('search_type', 'username')
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Количество пользователей на странице
    
    # Валидация входных данных
    valid_search_types = ['username', 'email', 'id']
    if search_type not in valid_search_types:
        search_type = 'username'
    
    if page < 1:
        page = 1
    
    # Базовый запрос
    query = User.query
    
    # Применяем фильтры поиска
    if search_query:
        if search_type == 'username':
            query = query.filter(User.username.ilike('%' + search_query + '%'))
        elif search_type == 'email':
            query = query.filter(User.email.ilike('%' + search_query + '%'))
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
    
    username = sanitize_input(request.form.get('username'), 80)
    email = sanitize_input(request.form.get('email'), 120)
    password = request.form.get('password')
    phone = sanitize_input(request.form.get('phone'), 20)
    student_name = sanitize_input(request.form.get('student_name'), 100)
    parent_name = sanitize_input(request.form.get('parent_name'), 100)
    category = request.form.get('category')
    is_admin = 'is_admin' in request.form
    
    if not all([username, email, password, phone, student_name, parent_name, category]):
        flash('Все поля должны быть заполнены', 'danger')
        return redirect(url_for('admin_users'))
    
    # Изменяем проверку уникальности логина на регистронезависимую
    if User.query.filter(User.username.ilike(username)).first():
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
    
    if category not in ['1-2', '3', '4', '5', '6', '7', '8', '9', '10', '11']:
        flash('Неверная категория', 'error')
        return redirect(url_for('admin_users'))
    
    user = User(
        username=username,
        email=email,
        phone=phone,
        student_name=student_name,  # Добавляем имя учащегося
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
    username = sanitize_input(request.form.get('username'), 80)
    email = sanitize_input(request.form.get('email'), 120)
    student_name = sanitize_input(request.form.get('student_name'), 100)
    parent_name = sanitize_input(request.form.get('parent_name'), 100)
    phone = sanitize_input(request.form.get('phone'), 20)
    category = request.form.get('category')
    password = request.form.get('password')
    is_admin = 'is_admin' in request.form
    tickets = request.form.get('tickets')
    
    if username != user.username and User.query.filter(User.username.ilike(username)).first():
        flash('Пользователь с таким логином уже существует', 'danger')
        return redirect(url_for('admin_users'))
    
    if email != user.email and User.query.filter_by(email=email).first():
        flash('Пользователь с таким email уже существует', 'danger')
        return redirect(url_for('admin_users'))
    
    if phone != user.phone and User.query.filter_by(phone=phone).first():
        flash('Пользователь с таким номером телефона уже существует', 'danger')
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
    user.student_name = student_name
    user.parent_name = parent_name
    user.phone = phone
    user.category = category
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
    
    try:
        # Удаляем связанные записи в правильном порядке
        # 1. Удаляем реферальные ссылки пользователя
        ReferralLink.query.filter_by(user_id=user.id).delete()
        
        # 2. Удаляем рефералы, где пользователь является приглашенным
        Referral.query.filter_by(referred_id=user.id).delete()
        
        # 3. Удаляем рефералы, где пользователь является пригласившим
        Referral.query.filter_by(referrer_id=user.id).delete()
        
        # 4. Удаляем сессии пользователя
        UserSession.query.filter_by(user_id=user.id, user_type='user').delete()
        
        # 5. Удаляем самого пользователя
        db.session.delete(user)
        db.session.commit()
        
        flash('Пользователь успешно удален', 'success')
        
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при удалении пользователя: {e}")
        flash('Произошла ошибка при удалении пользователя', 'danger')
    
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
        block_reason = sanitize_input(request.form.get('block_reason'), 500)
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

@app.route('/admin/users/mass-email', methods=['POST'])
@login_required
def admin_mass_email():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'У вас нет доступа к этой странице'})
    
    try:
        # Проверяем, что данные пришли в формате JSON
        if not request.is_json:
            return jsonify({'success': False, 'message': 'Неверный формат данных'})
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Данные не получены'})
        
        subject = sanitize_input(data.get('subject', ''), 200)
        message = validate_text_content(data.get('message', ''), 5000)
        
        if not subject or not message:
            return jsonify({'success': False, 'message': 'Тема и текст письма обязательны'})
        
        # Получаем всех активных пользователей с email
        users = User.query.filter(User.is_active == True, User.email.isnot(None)).all()
        
        if not users:
            return jsonify({'success': False, 'message': 'Нет пользователей для отправки писем'})
        
        # Отправляем письма всем пользователям
        sent_count = 0
        failed_count = 0
        
        for user in users:
            try:
                # Используем существующую функцию отправки email
                send_admin_notification(subject, message, user.email)
                sent_count += 1
            except Exception as e:
                failed_count += 1
                print(f"Ошибка отправки письма пользователю {user.email}: {e}")
        
        if failed_count == 0:
            return jsonify({
                'success': True, 
                'message': f'Письма успешно отправлены {sent_count} пользователям'
            })
        else:
            return jsonify({
                'success': True, 
                'message': f'Отправлено {sent_count} писем, {failed_count} писем не удалось отправить'
            })
            
    except Exception as e:
        print(f"Ошибка массовой рассылки: {e}")
        return jsonify({'success': False, 'message': f'Произошла ошибка при отправке писем: {str(e)}'})

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
    unique_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(8)}{ext}"
    return unique_name

@app.route('/admin/tournaments/add', methods=['POST'])
@login_required
def admin_add_tournament():
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    title = sanitize_input(request.form.get('title'), 200)
    description = validate_text_content(request.form.get('description'), 2000)
    rules = validate_text_content(request.form.get('rules'), 2000)
    start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%dT%H:%M')
    duration = int(request.form.get('duration'))
    
    # Обработка изображения
    image = request.files.get('image')
    image_filename = None
    if image and image.filename:
        image_filename = upload_file_to_s3(image, 'tournaments')
    
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
    
    tournament.title = sanitize_input(request.form.get('title'), 200)
    tournament.description = validate_text_content(request.form.get('description'), 2000)
    tournament.rules = validate_text_content(request.form.get('rules'), 2000)
    tournament.start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%dT%H:%M')
    tournament.duration = int(request.form.get('duration'))
    
    # Обработка изображения
    image = request.files.get('image')
    if image and image.filename:
        # Удаляем старое изображение
        if tournament.image:
            delete_file_from_s3(tournament.image, 'tournaments')
        
        # Загружаем новое изображение
        image_filename = upload_file_to_s3(image, 'tournaments')
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
    if tournament.start_date <= datetime.now():
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
        delete_file_from_s3(tournament.image, 'tournaments')
    
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
        if (solved_count or 0) > 0:
            solve_percentage = (correct_count or 0) / (solved_count or 0) * 100
        else:
            solve_percentage = 0
            
        tasks_data.append({
            'id': task_id,
            'title': title,
            'points': points,
            'solved_count': solved_count or 0,
            'correct_count': correct_count or 0,
            'solve_percentage': round(solve_percentage, 2)  # Процент правильных решений от попыток
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
    
    # Получаем номер страницы из параметров запроса
    page = request.args.get('page', 1, type=int)
    per_page = 12  # Количество призов на странице (3x4 сетка)
    
    # Получаем активные призы с пагинацией, отсортированные по стоимости
    pagination = Prize.query.filter_by(is_active=True).order_by(Prize.points_cost.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    prizes = pagination.items
    
    return render_template('admin/prizes.html', 
                         title='Управление призами',
                         prizes=prizes,
                         pagination=pagination)

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
    is_unique = 'is_unique' in request.form
    
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
        image_filename = upload_file_to_s3(image, 'prizes')
    
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
            delete_file_from_s3(prize.image, 'prizes')
        
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
            # Удаляем старое изображение
            if prize.image:
                delete_file_from_s3(prize.image, 'prizes')
            
            # Загружаем новое изображение
            image_filename = upload_file_to_s3(image, 'prizes')
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
    category = request.form.get('category')
    topic = request.form.get('topic')
    solution_text = request.form.get('solution_text')
    
    if not all([title, description, points, correct_answer, category]):
        flash('Все обязательные поля должны быть заполнены', 'danger')
        return redirect(url_for('configure_tournament', tournament_id=tournament_id))
    
    try:
        points = int(points)
        if points < 1:
            raise ValueError
    except ValueError:
        flash('Количество баллов должно быть положительным числом', 'danger')
        return redirect(url_for('configure_tournament', tournament_id=tournament_id))
    
    # Обработка изображения задачи
    image = request.files.get('image')
    image_filename = None
    if image and image.filename:
        image_filename = upload_file_to_s3(image, 'tasks')
    
    # Обработка изображения решения
    solution_image = request.files.get('solution_image')
    solution_image_filename = None
    if solution_image and solution_image.filename:
        solution_image_filename = upload_file_to_s3(solution_image, 'tasks')
    
    task = Task(
        tournament_id=tournament_id,
        title=title,
        description=description,
        image=image_filename,
        points=points,
        correct_answer=correct_answer,
        category=category,
        topic=topic,
        solution_text=solution_text,
        solution_image=solution_image_filename
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
    topic = request.form.get('topic')
    solution_text = request.form.get('solution_text')
    
    if not all([title, description, points, correct_answer]):
        flash('Все обязательные поля должны быть заполнены', 'danger')
        return redirect(url_for('configure_tournament', tournament_id=tournament_id))
    
    try:
        points = int(points)
        if points < 1:
            raise ValueError
    except ValueError:
        flash('Количество баллов должно быть положительным числом', 'danger')
        return redirect(url_for('configure_tournament', tournament_id=tournament_id))
    
    # Обработка изображения задачи
    image = request.files.get('image')
    if image and image.filename:
        # Удаляем старое изображение
        if task.image:
            delete_file_from_s3(task.image, 'tasks')
        
        # Загружаем новое изображение
        image_filename = upload_file_to_s3(image, 'tasks')
        task.image = image_filename
    
    # Обработка изображения решения
    solution_image = request.files.get('solution_image')
    if solution_image and solution_image.filename:
        # Удаляем старое изображение решения
        if task.solution_image:
            delete_file_from_s3(task.solution_image, 'tasks')
        
        # Загружаем новое изображение решения
        solution_image_filename = upload_file_to_s3(solution_image, 'tasks')
        task.solution_image = solution_image_filename
    
    task.title = title
    task.description = description
    task.points = points
    task.correct_answer = correct_answer
    task.topic = topic
    task.solution_text = solution_text
    
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
    
    # Удаляем изображение задачи
    if task.image:
        delete_file_from_s3(task.image, 'tasks')
    
    # Удаляем изображение решения
    if task.solution_image:
        delete_file_from_s3(task.solution_image, 'tasks')
    
    db.session.delete(task)
    db.session.commit()
    
    flash('Задача успешно удалена', 'success')
    return redirect(url_for('configure_tournament', tournament_id=tournament_id))

def is_password_strong(password):
    """
    Проверяет, соответствует ли пароль строгим требованиям безопасности:
    - Минимум 8 символов
    - Хотя бы одна заглавная буква
    - Хотя бы одна строчная буква
    - Хотя бы одна цифра
    - Хотя бы один специальный символ
    """
    if len(password) < 8:
        return False, "Пароль должен содержать минимум 8 символов"
    
    if not any(c.isupper() for c in password):
        return False, "Пароль должен содержать хотя бы одну заглавную букву"
    
    if not any(c.islower() for c in password):
        return False, "Пароль должен содержать хотя бы одну строчную букву"
    
    if not any(c.isdigit() for c in password):
        return False, "Пароль должен содержать хотя бы одну цифру"
    
    # Проверяем наличие специальных символов
    special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    if not any(c in special_chars for c in password):
        return False, "Пароль должен содержать хотя бы один специальный символ (!@#$%^&*()_+-=[]{}|;:,.<>?)"
    
    return True, "Пароль соответствует требованиям безопасности"

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

def sanitize_input(input_string, max_length=100):
    """Безопасно очищает входные данные"""
    if not input_string:
        return ''
    
    # Ограничиваем длину
    if len(input_string) > max_length:
        input_string = input_string[:max_length]
    
    # Удаляем потенциально опасные символы для SQL
    dangerous_chars = [';', '--', '/*', '*/', 'xp_', 'sp_', 'exec', 'execute', 'union', 'select', 'insert', 'update', 'delete', 'drop', 'create', 'alter']
    input_lower = input_string.lower()
    for char in dangerous_chars:
        if char in input_lower:
            return ''
    
    return input_string.strip()

def validate_email(email):
    """Валидация email адреса"""
    import re
    if not email:
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_phone(phone):
    """Валидация номера телефона"""
    import re
    if not phone:
        return False
    # Убираем все кроме цифр
    digits_only = re.sub(r'\D', '', phone)
    return len(digits_only) >= 9 and len(digits_only) <= 15

def validate_name(name, max_length=100):
    """Валидация имени (студента, родителя)"""
    if not name:
        return False
    if len(name) > max_length:
        return False
    # Проверяем, что имя содержит только буквы, пробелы, дефисы и точки
    import re
    pattern = r'^[а-яА-Яa-zA-Z\s\-\.]+$'
    return re.match(pattern, name) is not None

def validate_text_content(text, max_length=1000):
    """Валидация текстового контента (описания, правила)"""
    if not text:
        return False
    if len(text) > max_length:
        return False
    # Удаляем потенциально опасные HTML теги
    import re
    text = re.sub(r'<[^>]*>', '', text)
    return text.strip()

def validate_integer(value, min_val=None, max_val=None):
    """Валидация целого числа"""
    try:
        int_val = int(value)
        if min_val is not None and int_val < min_val:
            return False
        if max_val is not None and int_val > max_val:
            return False
        return True
    except (ValueError, TypeError):
        return False

def validate_float(value, min_val=None, max_val=None):
    """Валидация числа с плавающей точкой"""
    try:
        float_val = float(value)
        if min_val is not None and float_val < min_val:
            return False
        if max_val is not None and float_val > max_val:
            return False
        return True
    except (ValueError, TypeError):
        return False

@app.route('/check-username', methods=['POST'])
def check_username():
    data = request.get_json()
    username = data.get('username', '').strip()
    user_type = data.get('type', 'user')  # 'user' или 'teacher'
    
    if not username:
        return jsonify({'available': False})
    
    # Проверяем в зависимости от типа пользователя
    if user_type == 'teacher':
        existing_user = Teacher.query.filter(Teacher.username.ilike(username)).first()
    else:
        existing_user = User.query.filter(User.username.ilike(username)).first()
    
    return jsonify({'available': existing_user is None})

@app.route('/check-email', methods=['POST'])
def check_email():
    data = request.get_json()
    email = data.get('email', '').strip()
    user_type = data.get('type', 'user')  # 'user' или 'teacher'
    
    if not email:
        return jsonify({'available': False})
    
    # Проверяем в зависимости от типа пользователя
    if user_type == 'teacher':
        existing_user = Teacher.query.filter_by(email=email).first()
    else:
        existing_user = User.query.filter_by(email=email).first()
    
    return jsonify({'available': existing_user is None})

@app.route('/register', methods=['GET', 'POST'])
def register():
    # Получаем реферальный код и код учителя из параметров запроса
    referral_code = request.args.get('ref')
    teacher_code = request.args.get('teacher')
    referral_link = None
    teacher_invite_link = None
    
    if referral_code:
        referral_link = get_referral_link_by_code(referral_code)
    
    if teacher_code:
        teacher_invite_link = get_teacher_invite_link_by_code(teacher_code)
    
    if request.method == 'POST':
        username = sanitize_input(request.form.get('username'), 80)
        email = sanitize_input(request.form.get('email'), 120)
        phone = sanitize_input(request.form.get('phone'), 20)
        student_name = sanitize_input(request.form.get('student_name'), 100)
        parent_name = sanitize_input(request.form.get('parent_name'), 100)
        category = request.form.get('category')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        edu_id = request.form.get('educational_institution_id')
        edu_name = sanitize_input(request.form.get('educational_institution_name'), 500)
        # Получаем реферальный код из формы
        form_referral_code = sanitize_input(request.form.get('referral_code'), 50)
        if form_referral_code:
            referral_link = get_referral_link_by_code(form_referral_code)
        
        # Получаем код учителя из формы
        form_teacher_code = sanitize_input(request.form.get('teacher_code'), 50)
        if form_teacher_code:
            teacher_invite_link = get_teacher_invite_link_by_code(form_teacher_code)

        if not is_valid_username(username):
            flash('Логин может содержать только буквы латинского алфавита, цифры и знак подчеркивания. Минимальная длина - 3 символа, должен содержать хотя бы одну букву.', 'danger')
            return redirect(url_for('register'))

        if not validate_email(email):
            flash('Некорректный email адрес', 'danger')
            return redirect(url_for('register'))

        if not validate_name(student_name):
            flash('Имя учащегося может содержать только буквы, пробелы, дефисы и точки', 'danger')
            return redirect(url_for('register'))

        if parent_name and not validate_name(parent_name):
            flash('Имя родителя может содержать только буквы, пробелы, дефисы и точки', 'danger')
            return redirect(url_for('register'))

        if not validate_phone(phone):
            flash('Некорректный номер телефона', 'danger')
            return redirect(url_for('register'))

        is_strong, message = is_password_strong(password)
        if not is_strong:
            flash(message, 'danger')
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Пароли не совпадают', 'danger')
            return redirect(url_for('register'))

        # Получаем код страны и номер телефона
        phone_country = request.form.get('phone_country', '+375')
        phone_number = phone.strip()
        
        # Формируем полный номер телефона
        full_phone = phone_country + phone_number
        
        # Проверяем формат номера в зависимости от страны
        if phone_country == '+375':
            if not re.match(r'^[0-9]{9}$', phone_number):
                flash('Номер телефона Беларуси должен содержать 9 цифр', 'danger')
                return redirect(url_for('register'))
        elif phone_country == '+7':
            if not re.match(r'^[0-9]{10}$', phone_number):
                flash('Номер телефона России должен содержать 10 цифр', 'danger')
                return redirect(url_for('register'))
        else:
            flash('Неподдерживаемый код страны', 'danger')
            return redirect(url_for('register'))

        if not category or category not in ['1-2', '3', '4', '5', '6', '7', '8', '9', '10', '11']:
            flash('Пожалуйста, выберите группу', 'danger')
            return redirect(url_for('register'))

        # Изменяем проверку уникальности логина на регистронезависимую
        if User.query.filter(User.username.ilike(username)).first():
            flash('Пользователь с таким логином уже существует', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('Пользователь с таким email уже существует', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(phone=full_phone).first():
            flash('Пользователь с таким номером телефона уже существует', 'danger')
            return redirect(url_for('register'))

        user = User(
            username=username,
            email=email,
            phone=full_phone,
            student_name=student_name,  # Добавляем имя учащегося
            parent_name=parent_name,
            category=category
        )
        user.set_password(password)
        user.temp_password = password
        
        # Привязываем к учителю, если есть код приглашения
        if teacher_invite_link:
            user.teacher_id = teacher_invite_link.teacher_id
        
        # Обрабатываем учреждение образования
        if edu_id:
            user.educational_institution_id = int(edu_id)
        elif edu_name:
            # Проверяем, есть ли уже такое учреждение (на всякий случай)
            existing = EducationalInstitution.query.filter_by(name=edu_name).first()
            if existing:
                user.educational_institution_id = existing.id
            else:
                new_edu = EducationalInstitution(name=edu_name, address='')
                db.session.add(new_edu)
                db.session.commit()
                user.educational_institution_id = new_edu.id
        
        db.session.add(user)
        db.session.commit()

        # Обрабатываем реферальную ссылку
        if referral_link:
            try:
                create_referral(referral_link.user_id, user.id, referral_link.id)
                flash('Вы зарегистрировались по реферальной ссылке!', 'info')
            except Exception as e:
                print(f"Ошибка при создании реферала: {e}")

        # Обрабатываем приглашение учителя
        if teacher_invite_link:
            try:
                flash('Вы успешно прикреплены к учителю!', 'info')
            except Exception as e:
                print(f"Ошибка при прикреплении к учителю: {e}")

        # Отправляем письмо с подтверждением асинхронно
        send_confirmation_email(user)
        
        flash('Письмо с подтверждением отправлено на ваш email. Проверьте также папку "Спам", если письмо не пришло в течение нескольких минут.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', 
                          referral_code=referral_code, 
                          teacher_code=teacher_code,
                          teacher_invite_link=teacher_invite_link)

# Маршруты для учителей
@app.route('/teacher-register', methods=['GET', 'POST'])
def teacher_register():
    if request.method == 'POST':
        username = sanitize_input(request.form.get('username'), 80)
        email = sanitize_input(request.form.get('email'), 120)
        phone = sanitize_input(request.form.get('phone'), 20)
        full_name = sanitize_input(request.form.get('full_name'), 100)
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        edu_id = request.form.get('educational_institution_id')
        edu_name = sanitize_input(request.form.get('educational_institution_name'), 500)

        # Валидация данных
        if not is_valid_username(username):
            flash('Логин может содержать только буквы латинского алфавита, цифры и знак подчеркивания. Минимальная длина - 3 символа, должен содержать хотя бы одну букву.', 'danger')
            return redirect(url_for('teacher_register'))

        if not validate_email(email):
            flash('Некорректный email адрес', 'danger')
            return redirect(url_for('teacher_register'))

        if not validate_name(full_name):
            flash('ФИО может содержать только буквы, пробелы, дефисы и точки', 'danger')
            return redirect(url_for('teacher_register'))

        if not validate_phone(phone):
            flash('Некорректный номер телефона', 'danger')
            return redirect(url_for('teacher_register'))

        is_strong, message = is_password_strong(password)
        if not is_strong:
            flash(message, 'danger')
            return redirect(url_for('teacher_register'))

        if password != confirm_password:
            flash('Пароли не совпадают', 'danger')
            return redirect(url_for('teacher_register'))

        # Получаем код страны и номер телефона
        phone_country = request.form.get('phone_country', '+375')
        phone_number = phone.strip()
        
        # Формируем полный номер телефона
        full_phone = phone_country + phone_number
        
        # Проверяем формат номера в зависимости от страны
        if phone_country == '+375':
            if not re.match(r'^[0-9]{9}$', phone_number):
                flash('Номер телефона Беларуси должен содержать 9 цифр', 'danger')
                return redirect(url_for('teacher_register'))
        elif phone_country == '+7':
            if not re.match(r'^[0-9]{10}$', phone_number):
                flash('Номер телефона России должен содержать 10 цифр', 'danger')
                return redirect(url_for('teacher_register'))
        else:
            flash('Неподдерживаемый код страны', 'danger')
            return redirect(url_for('teacher_register'))

        # Проверяем уникальность данных
        if Teacher.query.filter(Teacher.username.ilike(username)).first():
            flash('Учитель с таким логином уже существует', 'danger')
            return redirect(url_for('teacher_register'))

        if Teacher.query.filter_by(email=email).first():
            flash('Учитель с таким email уже существует', 'danger')
            return redirect(url_for('teacher_register'))

        if Teacher.query.filter_by(phone=full_phone).first():
            flash('Учитель с таким номером телефона уже существует', 'danger')
            return redirect(url_for('teacher_register'))

        teacher = Teacher(
            username=username,
            email=email,
            phone=full_phone,
            full_name=full_name
        )
        teacher.set_password(password)
        teacher.temp_password = password
        
        # Обрабатываем учреждение образования
        if edu_id:
            teacher.educational_institution_id = int(edu_id)
        elif edu_name:
            # Проверяем, есть ли уже такое учреждение
            existing = EducationalInstitution.query.filter_by(name=edu_name).first()
            if existing:
                teacher.educational_institution_id = existing.id
            else:
                new_edu = EducationalInstitution(name=edu_name, address='')
                db.session.add(new_edu)
                db.session.commit()
                teacher.educational_institution_id = new_edu.id
        
        db.session.add(teacher)
        db.session.commit()

        # Создаем пригласительную ссылку для учителя
        create_teacher_invite_link(teacher.id)

        # Отправляем письмо с подтверждением
        send_teacher_confirmation_email(teacher)
        
        flash('Письмо с подтверждением отправлено на ваш email. Проверьте также папку "Спам", если письмо не пришло в течение нескольких минут.', 'success')
        return redirect(url_for('login'))

    return render_template('teacher_register.html')

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

@app.route('/confirm-teacher/<token>')
def confirm_teacher_email(token):
    """Подтверждение email для учителя"""
    teacher = Teacher.query.filter_by(email_confirmation_token=token).first()
    if teacher:
        teacher.is_active = True
        teacher.email_confirmation_token = None
        db.session.commit()
        
        # Отправляем письмо с учетными данными
        password = teacher.temp_password
        if password:
            send_teacher_credentials_email(teacher, password)
            teacher.temp_password = None
            db.session.commit()
        
        flash('Email успешно подтвержден! Теперь вы можете войти как учитель.', 'success')
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
    current_time = datetime.now()
    
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
    
    user_rank = current_user.category_rank
    settings = TournamentSettings.get_settings()
    
    return render_template('profile.html', 
                         title='Личный кабинет', 
                         user_rank=user_rank,
                         next_tournament=next_tournament,
                         now=current_time,
                         settings=settings)

@app.route('/teacher-profile')
@login_required
def teacher_profile():
    """Личный кабинет учителя"""
    # Проверяем, что пользователь является учителем
    if not isinstance(current_user, Teacher):
        flash('Доступ только для учителей', 'error')
        return redirect(url_for('home'))
    
    # Получаем или создаем пригласительную ссылку
    invite_link = create_teacher_invite_link(current_user.id)
    
    # Получаем статистику учеников
    students = User.query.filter_by(teacher_id=current_user.id).all()
    
    # Подсчитываем статистику
    total_students = len(students)
    active_students = len([s for s in students if s.tournaments_count > 0])
    
    # Пагинация для списка учеников
    page = request.args.get('page', 1, type=int)
    per_page = 15  # Количество учеников на странице
    
    # Получаем учеников с пагинацией
    students_paginated = User.query.filter_by(teacher_id=current_user.id)\
        .order_by(User.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    
    # Получаем информацию об учениках для текущей страницы
    students_info = []
    for student in students_paginated.items:
        # Получаем последний турнир ученика
        last_participation = TournamentParticipation.query.filter_by(user_id=student.id)\
            .order_by(TournamentParticipation.participation_date.desc()).first()
        
        students_info.append({
            'id': student.id,
            'username': student.username,
            'student_name': student.student_name,
            'parent_name': student.parent_name,
            'email': student.email,
            'phone': student.phone,
            'category': student.category,
            'balance': student.balance,
            'tickets': student.tickets,
            'tournaments_count': student.tournaments_count,
            'created_at': student.created_at.strftime('%d.%m.%Y'),
            'last_participation': last_participation.participation_date.strftime('%d.%m.%Y') if last_participation else 'Не участвовал',
            'is_active': student.is_active,
            'is_blocked': student.is_blocked
        })
    
    return render_template('teacher_profile.html',
                         title='Личный кабинет учителя',
                         invite_link=invite_link,
                         total_students=total_students,
                         active_students=active_students,
                         students_info=students_info,
                         students_paginated=students_paginated)

@app.route('/teacher/student/<int:student_id>/details')
@login_required
def teacher_student_details(student_id):
    """Просмотр подробной информации об учащемся учителем"""
    # Проверяем, что текущий пользователь - учитель
    if not hasattr(current_user, 'full_name') or not current_user.full_name:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    # Получаем учащегося и проверяем, что он принадлежит текущему учителю
    student = User.query.filter_by(id=student_id, teacher_id=current_user.id).first()
    if not student:
        flash('Учащийся не найден или не принадлежит вам', 'danger')
        return redirect(url_for('teacher_profile'))
    
    # Получаем статистику учащегося
    from sqlalchemy import func, case
    
    # Общая статистика
    total_tournaments = student.tournaments_count
    total_balance = student.balance
    
    # Место в рейтинге категории (берем из поля category_rank)
    category_rank = student.category_rank
    
    # Статистика по турнирам
    tournaments_stats = db.session.query(
        func.count(TournamentParticipation.id).label('total_participations'),
        func.sum(TournamentParticipation.score).label('total_score'),
        func.avg(TournamentParticipation.score).label('avg_score'),
        func.max(TournamentParticipation.score).label('best_score'),
        func.min(TournamentParticipation.place).label('best_place')
    ).filter(
        TournamentParticipation.user_id == student.id
    ).first()
    
    # Статистика по решенным задачам
    tasks_stats = db.session.query(
        func.count(SolvedTask.id).label('total_solved'),
        func.sum(case((SolvedTask.is_correct == True, 1), else_=0)).label('correct_solved'),
        func.sum(case((SolvedTask.is_correct == True, Task.points), else_=0)).label('total_points')
    ).join(
        Task, SolvedTask.task_id == Task.id
    ).filter(
        SolvedTask.user_id == student.id
    ).first()
    
    # Получаем историю турниров учащегося
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
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
        (Task.id == SolvedTask.task_id) & (SolvedTask.user_id == student.id)
    ).filter(
        TournamentParticipation.user_id == student.id
    ).group_by(
        Tournament.id,
        TournamentParticipation.score,
        TournamentParticipation.place
    ).order_by(
        Tournament.start_date.desc()
    )
    
    tournaments_paginated = tournaments_query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Преобразуем результаты в список словарей
    tournament_list = []
    for tournament, score, place, solved_tasks, earned_points, correct_tasks, total_tasks in tournaments_paginated.items:
        success_rate = round((correct_tasks or 0) / (total_tasks or 1) * 100, 1)
        
        tournament_list.append({
            'id': tournament.id,
            'name': tournament.title,
            'start_date': tournament.start_date,
            'status': tournament.status,
            'solved_tasks': solved_tasks or 0,
            'earned_points': earned_points or 0,
            'score': score or 0,
            'place': place,
            'success_rate': success_rate
        })
    
    # Подготавливаем данные для шаблона
    student_stats = {
        'total_tournaments': total_tournaments,
        'total_balance': total_balance,
        'category_rank': category_rank,
        'total_participations': tournaments_stats.total_participations or 0,
        'total_score': tournaments_stats.total_score or 0,
        'avg_score': round(tournaments_stats.avg_score or 0, 1),
        'best_score': tournaments_stats.best_score or 0,
        'best_place': tournaments_stats.best_place,
        'total_solved_tasks': tasks_stats.total_solved or 0,
        'correct_solved_tasks': tasks_stats.correct_solved or 0,
        'total_points': tasks_stats.total_points or 0
    }
    
    return render_template('teacher_student_details.html',
                         student=student,
                         student_stats=student_stats,
                         tournaments=tournament_list,
                         pagination=tournaments_paginated)

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
    
    # Получаем курс валют
    from currency_service import currency_service
    currency_rate = currency_service.get_byn_to_rub_rate()
    currency_rate_formatted = currency_service.get_formatted_rate()
    
    # URL документа пользовательского соглашения (локальный файл)
    agreement_url = url_for('static', filename='Пользовательское соглашение.pdf')
    
    return render_template('buy_tickets.html', 
                         title='Покупка билетов',
                         base_price=base_price,
                         discounts=discounts_data,
                         currency_rate=currency_rate,
                         currency_rate_formatted=currency_rate_formatted,
                         agreement_url=agreement_url)

@app.route('/create-payment', methods=['POST'])
@login_required
def create_payment():
    """Создание платежа для покупки жетонов"""
    if current_user.is_admin:
        return jsonify({'success': False, 'error': 'Администраторы не могут покупать жетоны'})
    
    data = request.get_json()
    quantity = data.get('quantity', 0)
    payment_system = data.get('payment_system', '')
    
    if not quantity or quantity < 1:
        return jsonify({'success': False, 'error': 'Укажите корректное количество жетонов'})
    
    if payment_system not in ['yukassa', 'express_pay', 'bepaid']:
        return jsonify({'success': False, 'error': 'Неверная платежная система'})
    
    base_price = TicketPackage.query.filter_by(is_active=True).first()
    if not base_price:
        return jsonify({'success': False, 'error': 'В данный момент покупка жетонов недоступна'})
    
    # Получаем скидку для указанного количества
    discount = TicketDiscount.get_discount_for_quantity(quantity)
    
    # Рассчитываем итоговую стоимость в BYN
    total_price_byn = base_price.price * quantity * (1 - discount / 100)
    
    # Конвертируем валюту в зависимости от платежной системы
    from currency_service import currency_service
    if payment_system == 'yukassa':
        total_price = currency_service.convert_byn_to_rub(total_price_byn)
        currency = 'RUB'
    else:
        total_price = total_price_byn
        currency = 'BYN'
    
    # Создаем запись о покупке
    purchase = TicketPurchase(
        user_id=current_user.id,
        quantity=quantity,
        amount=total_price_byn,  # Сохраняем сумму в BYN
        discount=discount,
        payment_system=payment_system,
        payment_status='pending',
        currency=currency
    )
    
    db.session.add(purchase)
    db.session.commit()
    
    try:
        if payment_system == 'yukassa':
            # Интеграция с ЮKassa
            from yukassa_service import yukassa_service
            
            # Создаем описание платежа
            description = f"Покупка {quantity} жетонов для участия в турнирах"
            
            # URL для возврата после оплаты
            return_url = url_for('purchase_history', _external=True)
            
            # Создаем платеж в ЮKassa
            payment_info = yukassa_service.create_payment(
                amount=total_price,
                description=description,
                return_url=return_url,
                capture=True  # Автоматическое списание
            )
            
            # Сохраняем данные платежа
            purchase.payment_id = payment_info['id']
            purchase.payment_status = yukassa_service.get_payment_status(payment_info)
            purchase.payment_url = payment_info['confirmation']['confirmation_url']
            purchase.payment_created_at = datetime.now()
            
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': f'Платеж создан успешно',
                'payment_url': purchase.payment_url
            })
            
        elif payment_system == 'express_pay':
            # Интеграция с Express-Pay
            from express_pay_service import express_pay_service
            
            # Получаем способ оплаты из запроса
            payment_method = data.get('payment_method', 'epos')  # epos или erip
            
            # Создаем описание платежа
            description = f"Покупка {quantity} жетонов для участия в турнирах"
            
            # URL для возврата после оплаты
            return_url = url_for('purchase_history', _external=True)
            
            # Создаем ID заказа (используем только ID покупки)
            order_id = str(purchase.id)
            
            # Создаем платеж в Express-Pay
            payment_info = express_pay_service.create_payment(
                amount=total_price,
                order_id=order_id,
                description=description,
                return_url=return_url,
                payment_method=payment_method
            )
            
            # Сохраняем данные платежа
            invoice_no = payment_info.get('InvoiceNo')
            if invoice_no:
                purchase.payment_id = str(invoice_no)
            else:
                raise Exception("Express-Pay не вернул номер счета")
                
            # Устанавливаем начальный статус как pending
            purchase.payment_status = 'pending'
            purchase.payment_method = payment_method
            purchase.payment_url = payment_info.get('InvoiceUrl')  # URL для оплаты
            purchase.payment_created_at = datetime.now()
            
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': f'Платеж создан успешно',
                'payment_url': purchase.payment_url
            })
            
        elif payment_system == 'bepaid':
            # Заглушка для bePaid
            return jsonify({
                'success': False,
                'error': 'Система bePaid пока не поддерживается'
            })
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Ошибка при создании платежа: {str(e)}'})

@app.route('/process-ticket-purchase', methods=['POST'])
@login_required
def process_ticket_purchase():
    """Старый маршрут отключен для безопасности - покупка только через платежные системы"""
    flash('Покупка жетонов возможна только через платежные системы. Пожалуйста, используйте кнопку "Оформить покупку".', 'warning')
    return redirect(url_for('buy_tickets'))

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

@app.route('/check-payment-status/<payment_id>')
@login_required
def check_payment_status(payment_id):
    """Проверка статуса платежа"""
    try:
        # Находим покупку
        purchase = TicketPurchase.query.filter_by(payment_id=payment_id).first()
        if not purchase:
            return jsonify({'error': 'Purchase not found'}), 404
        
        # Проверяем, что покупка принадлежит текущему пользователю
        if purchase.user_id != current_user.id:
            return jsonify({'error': 'Access denied'}), 403
        
        # Получаем актуальную информацию о платеже в зависимости от платежной системы
        old_status = purchase.payment_status
        
        if purchase.payment_system == 'yukassa':
            from yukassa_service import yukassa_service
            payment_info = yukassa_service.get_payment_info(payment_id)
            new_status = yukassa_service.get_payment_status_with_expiry(payment_info)
            status_description = yukassa_service.get_payment_status_description(new_status)
        elif purchase.payment_system == 'express_pay':
            from express_pay_service import ExpressPayService
            express_pay_service = ExpressPayService()
            
            # Проверяем, что payment_id не None
            if not payment_id or payment_id == 'None' or payment_id == 'null':
                return jsonify({'error': 'Invalid payment ID'}), 400
                
            # Получаем статус через специальный endpoint
            status_response = express_pay_service.get_payment_status(payment_id)
            status_code = status_response.get('Status')
            new_status = express_pay_service.parse_payment_status(status_code)
            status_description = express_pay_service.get_payment_status_description(new_status)
        else:
            return jsonify({'error': 'Unsupported payment system'}), 400
        
        purchase.payment_status = new_status
        
        # Если платеж успешен, начисляем жетоны
        if new_status == 'succeeded' and old_status != 'succeeded':
            current_user.tickets += purchase.quantity
            purchase.payment_confirmed_at = datetime.now()
            print(f"Проверка статуса: начислено {purchase.quantity} жетонов пользователю {current_user.id}")
        
        db.session.commit()
        
        return jsonify({
            'status': new_status,
            'status_description': status_description,
            'payment_id': payment_id,
            'amount': purchase.amount,
            'quantity': purchase.quantity,
            'old_status': old_status
        })
        
    except Exception as e:
        print(f"Ошибка при проверке статуса платежа {payment_id}: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/webhook/yukassa/<webhook_token>', methods=['POST'])
def yukassa_webhook(webhook_token):
    """Обработка webhook'ов от ЮKassa"""
    # Проверяем токен webhook'а
    expected_token = os.environ.get('YUKASSA_WEBHOOK_TOKEN')
    if webhook_token != expected_token:
        print(f"Webhook: неверный токен. Ожидалось: {expected_token}, получено: {webhook_token}")
        return jsonify({'error': 'Invalid webhook token'}), 403
    
    try:
        # Логируем входящий webhook
        print(f"Получен webhook от ЮKassa: {request.headers}")
        print(f"Тело webhook: {request.get_json()}")
        
        # Получаем данные от ЮKassa
        data = request.get_json()
        
        if not data:
            print("Webhook: пустое тело запроса")
            return jsonify({'error': 'Empty request body'}), 400
        
        # Проверяем подпись (в тестовой среде пропускаем)
        from yukassa_service import yukassa_service
        
        # Получаем информацию о платеже
        payment_id = data.get('object', {}).get('id')
        event_type = data.get('event', 'unknown')
        print(f"Webhook: обработка платежа {payment_id}, событие: {event_type}")
        
        if not payment_id:
            print("Webhook: отсутствует ID платежа")
            return jsonify({'error': 'No payment ID'}), 400
        
        # Получаем актуальную информацию о платеже
        payment_info = yukassa_service.get_payment_info(payment_id)
        
        # Находим покупку по ID платежа
        purchase = TicketPurchase.query.filter_by(payment_id=payment_id).first()
        if not purchase:
            print(f"Webhook: покупка с payment_id {payment_id} не найдена")
            return jsonify({'error': 'Purchase not found'}), 404
        
        # Обновляем статус платежа с учетом истечения времени
        old_status = purchase.payment_status
        new_status = yukassa_service.get_payment_status_with_expiry(payment_info)
        purchase.payment_status = new_status
        
        # Логируем детали платежа
        print(f"Webhook: платеж {payment_id}")
        print(f"  - Старый статус: {old_status}")
        print(f"  - Новый статус: {new_status}")
        print(f"  - Событие: {event_type}")
        print(f"  - Сумма: {payment_info.get('amount', {}).get('value')} {payment_info.get('amount', {}).get('currency')}")
        
        # Обрабатываем разные статусы
        if new_status == 'succeeded' and old_status != 'succeeded':
            # Платеж успешно завершен
            user = User.query.get(purchase.user_id)
            if user:
                user.tickets += purchase.quantity
                purchase.payment_confirmed_at = datetime.now()
                print(f"Webhook: начислено {purchase.quantity} жетонов пользователю {user.id}")
        
        elif new_status == 'canceled':
            # Платеж отменен
            print(f"Webhook: платеж {payment_id} отменен")
            
        elif new_status == 'failed':
            # Платеж завершился с ошибкой
            print(f"Webhook: платеж {payment_id} завершился с ошибкой")
            
        elif new_status == 'pending':
            # Платеж ожидает оплаты
            print(f"Webhook: платеж {payment_id} ожидает оплаты")
            
        elif new_status == 'waiting_for_capture':
            # Платеж ожидает подтверждения
            print(f"Webhook: платеж {payment_id} ожидает подтверждения")
            
        elif new_status == 'expired':
            # Платеж истек
            print(f"Webhook: платеж {payment_id} истек (время ожидания превышено)")
        
        db.session.commit()
        print(f"Webhook: статус платежа {payment_id} обновлен с {old_status} на {new_status}")
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        print(f"Webhook: ошибка обработки: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/webhook/express-pay/<webhook_token>', methods=['POST'])
def express_pay_webhook(webhook_token):
    """Обработка webhook'ов от Express-Pay с проверкой цифровой подписи"""
    # Проверяем токен webhook'а
    expected_token = os.environ.get('EXPRESS_PAY_WEBHOOK_TOKEN')
    if webhook_token != expected_token:
        print(f"Webhook: неверный токен. Ожидалось: {expected_token}, получено: {webhook_token}")
        return jsonify({'error': 'Invalid webhook token'}), 403
    
    try:
        # Логируем входящий webhook
        print(f"Получен webhook от Express-Pay: {request.headers}")
        print(f"Тело webhook: {request.get_json()}")
        
        # Получаем данные от Express-Pay
        data = request.get_json()
        
        if not data:
            print("Webhook: пустое тело запроса")
            return jsonify({'error': 'Empty request body'}), 400
        
        # Проверяем обязательные поля
        cmd_type = data.get('CmdType')
        if cmd_type is None:
            print("Webhook: отсутствует CmdType")
            return jsonify({'error': 'Missing CmdType'}), 400
        
        # Проверка цифровой подписи отключена
        # signature = request.args.get('Signature')
        # if signature:
        #     # Получаем секретное слово из конфигурации
        #     secret_word = os.environ.get('EXPRESS_PAY_SECRET_WORD')
        #     if not secret_word:
        #         print("Webhook: не настроено секретное слово для проверки подписи")
        #         return jsonify({'error': 'Signature verification not configured'}), 500
        #     
        #     # Проверяем подпись (HMAC-SHA1)
        #     import hmac
        #     data_string = json.dumps(data, separators=(',', ':'))
        #     expected_signature = hmac.new(
        #         secret_word.encode('utf-8'),
        #         data_string.encode('utf-8'),
        #         hashlib.sha1
        #     ).hexdigest()
        #     if signature != expected_signature:
        #         print(f"Webhook: неверная подпись. Ожидалось: {expected_signature}, получено: {signature}")
        #         return jsonify({'error': 'Invalid signature'}), 400
        
        print(f"Webhook: обработка уведомления типа {cmd_type}")
        
        # Обрабатываем разные типы уведомлений
        if cmd_type == 1:
            # Поступление нового платежа
            return handle_new_payment_notification(data)
        elif cmd_type == 2:
            # Отмена платежа
            return handle_payment_cancellation(data)
        elif cmd_type == 3:
            # Изменение статуса счета
            return handle_status_change_notification(data)
        else:
            print(f"Webhook: неизвестный тип уведомления: {cmd_type}")
            return jsonify({'error': 'Unknown notification type'}), 400
        
    except Exception as e:
        print(f"Webhook: ошибка обработки: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

def handle_new_payment_notification(data):
    """Обработка уведомления о поступлении нового платежа"""
    try:
        account_no = data.get('AccountNo')
        payment_no = data.get('PaymentNo')
        amount = data.get('Amount')
        created = data.get('Created')
        service = data.get('Service')
        
        print(f"Webhook: новый платеж - AccountNo: {account_no}, PaymentNo: {payment_no}, Amount: {amount}")
        
        # Находим покупку по номеру лицевого счета (AccountNo)
        purchase = TicketPurchase.query.filter_by(payment_id=str(account_no)).first()
        if not purchase:
            print(f"Webhook: покупка с payment_id {account_no} не найдена")
            return jsonify({'error': 'Purchase not found'}), 404
        
        # Обновляем информацию о платеже
        purchase.payment_status = 'succeeded'
        purchase.payment_confirmed_at = datetime.now()
        
        # Начисляем жетоны пользователю
        user = User.query.get(purchase.user_id)
        if user:
            user.tickets += purchase.quantity
            print(f"Webhook: начислено {purchase.quantity} жетонов пользователю {user.id}")
        
        db.session.commit()
        print(f"Webhook: платеж {account_no} успешно обработан")
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        print(f"Webhook: ошибка обработки нового платежа: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

def handle_payment_cancellation(data):
    """Обработка уведомления об отмене платежа"""
    try:
        account_no = data.get('AccountNo')
        payment_no = data.get('PaymentNo')
        
        print(f"Webhook: отмена платежа - AccountNo: {account_no}, PaymentNo: {payment_no}")
        
        # Находим покупку по номеру лицевого счета
        purchase = TicketPurchase.query.filter_by(payment_id=str(account_no)).first()
        if not purchase:
            print(f"Webhook: покупка с payment_id {account_no} не найдена")
            return jsonify({'error': 'Purchase not found'}), 404
        
        # Обновляем статус платежа
        purchase.payment_status = 'canceled'
        
        db.session.commit()
        print(f"Webhook: платеж {account_no} отменен")
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        print(f"Webhook: ошибка обработки отмены платежа: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

def handle_status_change_notification(data):
    """Обработка уведомления об изменении статуса счета"""
    try:
        status = data.get('Status')
        account_no = data.get('AccountNo')
        invoice_no = data.get('InvoiceNo')
        amount = data.get('Amount')
        created = data.get('Created')
        
        print(f"Webhook: изменение статуса - AccountNo: {account_no}, InvoiceNo: {invoice_no}, Status: {status}")
        
        # Находим покупку по номеру счета (InvoiceNo)
        purchase = TicketPurchase.query.filter_by(payment_id=str(invoice_no)).first()
        if not purchase:
            print(f"Webhook: покупка с payment_id {invoice_no} не найдена")
            return jsonify({'error': 'Purchase not found'}), 404
        
        # Определяем новый статус на основе кода статуса
        old_status = purchase.payment_status
        new_status = None
        
        if status == 1:
            new_status = 'pending'  # Ожидает оплату
        elif status == 2:
            new_status = 'expired'  # Просрочен
        elif status == 3 or status == 6:
            new_status = 'succeeded'  # Оплачен или Оплачен с помощью банковской карты
        elif status == 4:
            new_status = 'partial'  # Оплачен частично
        elif status == 5:
            new_status = 'canceled'  # Отменен
        elif status == 7:
            new_status = 'refunded'  # Платеж возвращен
        else:
            print(f"Webhook: неизвестный статус: {status}")
            new_status = 'unknown'
        
        # Обновляем статус платежа
        purchase.payment_status = new_status
        
        # Если статус изменился на "оплачен" и ранее не был оплачен, начисляем жетоны
        if new_status == 'succeeded' and old_status != 'succeeded':
            user = User.query.get(purchase.user_id)
            if user:
                user.tickets += purchase.quantity
                purchase.payment_confirmed_at = datetime.now()
                print(f"Webhook: начислено {purchase.quantity} жетонов пользователю {user.id}")
        
        db.session.commit()
        print(f"Webhook: статус платежа {invoice_no} обновлен с {old_status} на {new_status}")
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        print(f"Webhook: ошибка обработки изменения статуса: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

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
    
    # Подсчитываем реальное количество участий в турнирах
    actual_tournaments_participated = len(user.tournament_participations)
    total_tournaments_participated = actual_tournaments_participated
    
    # Подсчитываем победы (место = 1)
    total_tournaments_won = sum(1 for p in user.tournament_participations if p.place == 1)
    
    # Вычисляем средний балл
    if actual_tournaments_participated > 0:
        average_tournament_score = sum(p.score for p in user.tournament_participations) / actual_tournaments_participated
    else:
        average_tournament_score = 0
    
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
    now = datetime.now()  # Московское время
    tournaments = Tournament.query.filter(Tournament.status != 'finished').all()
    
    for tournament in tournaments:
        if tournament.start_date <= now and now <= tournament.start_date + timedelta(minutes=tournament.duration):
            tournament.status = 'started'
        elif now > tournament.start_date + timedelta(minutes=tournament.duration):
            tournament.status = 'finished'
    
    db.session.commit()

def restore_scheduler_jobs():
    """Восстанавливает задачи планировщика из БД при запуске приложения"""
    try:
        # Получаем только задачи текущего сервера
        active_jobs = SchedulerJob.query.filter_by(
            is_active=True, 
            server_id=SERVER_ID
        ).all()
        restored_count = 0
        
        for job in active_jobs:
            try:
                # Определяем функцию и аргументы в зависимости от типа задачи
                if job.job_type == 'start':
                    job_func = start_tournament_job
                    args = [job.tournament_id]
                    interval_hours = None
                elif job.job_type == 'end':
                    job_func = end_tournament_job
                    args = [job.tournament_id]
                    interval_hours = None
                elif job.job_type == 'cleanup_sessions':
                    job_func = cleanup_old_sessions
                    args = []
                    interval_hours = 24  # Интервальная задача каждые 24 часа
                elif job.job_type == 'check_expired_payments':
                    job_func = check_expired_payments
                    args = []
                    interval_hours = 1  # Интервальная задача каждый час
                elif job.job_type == 'check_referral_bonuses':
                    job_func = check_and_pay_referral_bonuses
                    args = []
                    interval_hours = 1  # Интервальная задача каждые 6 часов
                else:
                    # Неизвестный тип задачи, пропускаем
                    continue
                
                # Проверяем, не истекло ли время выполнения (только для обычных задач)
                if interval_hours is None and job.run_date <= datetime.now():
                    # Время истекло, удаляем задачу из БД
                    db.session.delete(job)
                    db.session.commit()
                    continue
                
                # Добавляем задачу в планировщик
                if interval_hours:
                    # Интервальная задача
                    scheduler.add_job(
                        job_func,
                        trigger='interval',
                        hours=interval_hours,
                        id=job.job_id,
                        replace_existing=True
                    )
                else:
                    # Обычная задача
                    scheduler.add_job(
                        job_func,
                        trigger=DateTrigger(run_date=job.run_date),
                        args=args,
                        id=job.job_id,
                        replace_existing=True
                    )
                # Обновляем updated_at
                job.updated_at = datetime.now()
                db.session.commit()
                
                restored_count += 1
                
            except Exception as e:
                print(f"Ошибка при восстановлении задачи {job.job_id}: {e}")
                # Удаляем проблемную задачу из БД
                db.session.delete(job)
                db.session.commit()
        
        print(f"Восстановлено {restored_count} задач планировщика для сервера {SERVER_ID}")
        
    except Exception as e:
        print(f"Ошибка при восстановлении задач планировщика: {e}")

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
    if datetime.now() > tournament.start_date + timedelta(minutes=tournament.duration):
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
        is_correct=is_correct,
        user_answer=user_answer
    )
    db.session.add(solution)
    
    # Обновляем время окончания участия в турнире
    if participation:
        participation.end_time = current_time
    
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
    
    # Проверяем, завершился ли турнир
    if tournament.status != 'finished':
        flash('Результаты турнира будут доступны только после его завершения', 'warning')
        return redirect(url_for('tournament_history'))
    
    # Проверяем, участвовал ли пользователь в этом турнире
    participation = TournamentParticipation.query.filter_by(
        user_id=current_user.id,
        tournament_id=tournament_id
    ).first()
    
    if not participation:
        flash('Вы не участвовали в этом турнире', 'danger')
        return redirect(url_for('tournament_history'))
    
    # Получаем все задачи турнира для категории пользователя
    user_tasks = Task.query.filter_by(
        tournament_id=tournament_id,
        category=current_user.category
    ).order_by(Task.id).all()
    
    # Получаем решенные задачи пользователя
    solved_tasks = SolvedTask.query.filter_by(
        user_id=current_user.id
    ).join(Task).filter(Task.tournament_id == tournament_id).all()
    
    # Создаем словарь решенных задач для быстрого поиска
    solved_tasks_dict = {task.task_id: task for task in solved_tasks}
    
    # Подготавливаем данные о задачах
    tasks_data = []
    for task in user_tasks:
        solved_task = solved_tasks_dict.get(task.id)
        tasks_data.append({
            'task': task,
            'is_solved': solved_task is not None,
            'is_correct': solved_task.is_correct if solved_task else False,
            'user_answer': solved_task.user_answer if solved_task else None,
            'solved_at': solved_task.solved_at if solved_task else None
        })
    
    # Считаем статистику
    solved_count = len([t for t in tasks_data if t['is_solved']])
    correct_count = len([t for t in tasks_data if t['is_correct']])
    earned_points = sum(t['task'].points for t in tasks_data if t['is_correct'])
    total_points = sum(t['task'].points for t in tasks_data)
    
    # Вычисляем процент правильных ответов
    success_rate = round((correct_count / len(tasks_data)) * 100, 1) if tasks_data and len(tasks_data) > 0 else 0
    
    # Вычисляем время участия
    if participation.end_time:
        # Если есть время окончания, используем его
        time_spent = (participation.end_time - participation.start_time).total_seconds()
    else:
        # Если нет времени окончания, используем текущее время
        time_spent = (datetime.now() - participation.start_time).total_seconds()
    
    # Собираем темы для повторения
    topics_to_review = set()  # Темы неправильно решенных задач
    additional_topics = set()  # Темы нерешенных задач
    
    for task_data in tasks_data:
        task = task_data['task']
        if task.topic:  # Проверяем, что тема указана
            if task_data['is_solved'] and not task_data['is_correct']:
                # Неправильно решенная задача - добавляем в обязательное повторение
                topics_to_review.add(task.topic)
            elif not task_data['is_solved']:
                # Нерешенная задача - добавляем в дополнительное повторение
                additional_topics.add(task.topic)
    
    # Убираем дубликаты из дополнительных тем (если тема уже в обязательных)
    additional_topics = additional_topics - topics_to_review
    
    return render_template('tournament_results.html',
                         tournament=tournament,
                         tasks_data=tasks_data,
                         solved_count=solved_count,
                         correct_count=correct_count,
                         earned_points=earned_points,
                         total_points=total_points,
                         success_rate=success_rate,
                         participation=participation,
                         time_spent=time_spent,
                         topics_to_review=sorted(list(topics_to_review)),
                         additional_topics=sorted(list(additional_topics)),
                         now=datetime.now())

@app.route('/tournament/history')
@login_required
def tournament_history():
    if hasattr(current_user, 'is_admin') and current_user.is_admin:
        flash('Администраторы не могут участвовать в турнирах', 'warning')
        return redirect(url_for('home'))
    
    # Проверяем, является ли пользователь учителем
    if not hasattr(current_user, 'tournaments_count'):
        flash('Эта страница доступна только учащимся', 'warning')
        return redirect(url_for('teacher_profile'))
    
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
            'status': tournament.status,
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
    from sqlalchemy import func, case

    users_by_category = {}
    categories = ['1-2', '3', '4', '5', '6', '7', '8', '9', '10', '11']
    
    # Получаем параметры пагинации и категории
    selected_category = request.args.get('category', '1-2')
    per_page = 20  # Количество записей на странице
    
    # Проверяем, должен ли показываться полный рейтинг
    show_full_rating = False
    if current_user.is_authenticated:
        # Проверяем тип пользователя
        if hasattr(current_user, 'is_admin') and current_user.is_admin:
            # Для администраторов проверяем параметр режима
            mode = request.args.get('mode')
            show_full_rating = mode == 'full'
        elif hasattr(current_user, 'tournaments_count'):
            # Для обычных пользователей проверяем участие в турнирах
            show_full_rating = current_user.tournaments_count > 0
        # Для учителей показываем только топ-10 (show_full_rating остается False)
    
    for category in categories:
        # Получаем номер страницы для конкретной категории
        page = request.args.get(f'page_{category}', 1, type=int)
        
        # Базовый запрос для получения пользователей категории
        users_stats = (
            db.session.query(
                User,
                func.count(SolvedTask.id).label('solved_tasks_count'),
                func.sum(case((SolvedTask.is_correct == True, 1), else_=0)).label('correct_tasks_count')
            )
            .outerjoin(SolvedTask, User.id == SolvedTask.user_id)
            .filter(User.is_admin == False, User.category == category)
            .group_by(User.id)
            .order_by(User.balance.desc())
        )
        
        if show_full_rating:
            # Для полного рейтинга применяем пагинацию
            total_users = users_stats.count()
            total_pages = (total_users + per_page - 1) // per_page
            
            # Получаем записи для текущей страницы
            users_stats = users_stats.offset((page - 1) * per_page).limit(per_page).all()
            
            has_next = page < total_pages
            has_prev = page > 1
        else:
            # Для топ-10 ограничиваем количество
            users_stats = users_stats.limit(10).all()
            has_next = False
            has_prev = False
            total_pages = 1
        
        # Обрабатываем статистику для пользователей
        users = []
        for user, solved_tasks_count, correct_tasks_count in users_stats:
            user.solved_tasks_count = correct_tasks_count or 0
            user.success_rate = round((correct_tasks_count / solved_tasks_count * 100) if solved_tasks_count else 0, 1)
            user.is_current_user = False  # По умолчанию не текущий пользователь
            users.append(user)
        
        # Проверяем, нужно ли добавить текущего пользователя (только для топ-10)
        if not show_full_rating and current_user.is_authenticated and hasattr(current_user, 'category') and current_user.category == category:
            # Проверяем, есть ли текущий пользователь в списке
            current_user_in_list = any(user.id == current_user.id for user in users)
            
            if not current_user_in_list:
                # Получаем статистику для текущего пользователя
                current_user_stats = (
                    db.session.query(
                        User,
                        func.count(SolvedTask.id).label('solved_tasks_count'),
                        func.sum(case((SolvedTask.is_correct == True, 1), else_=0)).label('correct_tasks_count')
                    )
                    .outerjoin(SolvedTask, User.id == SolvedTask.user_id)
                    .filter(User.id == current_user.id)
                    .group_by(User.id)
                    .first()
                )
                
                if current_user_stats:
                    user, solved_tasks_count, correct_tasks_count = current_user_stats
                    user.solved_tasks_count = correct_tasks_count or 0
                    user.success_rate = round((correct_tasks_count / solved_tasks_count * 100) if solved_tasks_count else 0, 1)
                    user.is_current_user = True  # Флаг для выделения текущего пользователя
                    users.append(user)
            else:
                # Если текущий пользователь в списке, помечаем его
                for user in users:
                    if user.id == current_user.id:
                        user.is_current_user = True
                        break
        
        users_by_category[category] = {
            'users': users,
            'has_next': has_next,
            'has_prev': has_prev,
            'show_full_rating': show_full_rating,
            'current_page': page if show_full_rating else 1,
            'total_pages': total_pages
        }

    user_rank = None
    if current_user.is_authenticated and hasattr(current_user, 'category_rank'):
        user_rank = current_user.category_rank

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        category = request.args.get('category', '1-2')
        users_data = users_by_category.get(category, {'users': [], 'has_next': False})
        return jsonify({
            'users': [{
                'username': user.username,
                'student_name': user.student_name,
                'balance': user.balance,
                'solved_tasks_count': user.solved_tasks_count,
                'success_rate': user.success_rate,
                'tournaments_count': user.tournaments_count,
                'category_rank': user.category_rank,
                'total_tournament_time': user.total_tournament_time,
                'is_current_user': getattr(user, 'is_current_user', False)
            } for user in users_data['users']],
            'has_next': users_data['has_next'],
            'has_prev': users_data.get('has_prev', False),
            'current_page': users_data.get('current_page', 1),
            'total_pages': users_data.get('total_pages', 1)
        })

    return render_template('rating.html', 
                         users_by_category=users_by_category,
                         user_rank=user_rank,
                         show_full_rating=show_full_rating,
                         selected_category=selected_category)

@app.route('/rating/load-more')
def load_more_users():
    # Пагинация больше не используется, так как показываем только топ-10
    return jsonify({
        'users': [],
        'has_next': False
    })

@app.route('/shop')
@login_required
def shop():
    # Получаем параметры из запроса
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', 'price_asc')  # По умолчанию сортировка по цене по возрастанию
    per_page = 9  # Количество призов на странице (3x3 сетка)
    
    # Базовый запрос
    query = Prize.query.filter(Prize.is_active == True)
    
    # Применяем сортировку
    if sort == 'price_asc':
        query = query.order_by(Prize.points_cost.asc())
    elif sort == 'price_desc':
        query = query.order_by(Prize.points_cost.desc())
    elif sort == 'name_asc':
        query = query.order_by(Prize.name.asc())
    elif sort == 'name_desc':
        query = query.order_by(Prize.name.desc())
    else:
        # По умолчанию сортировка по цене по возрастанию
        query = query.order_by(Prize.points_cost.asc())
    
    # Получаем активные призы с пагинацией
    pagination = query.paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    prizes = pagination.items
    settings = ShopSettings.get_settings()
    can_shop = settings.can_user_shop(current_user)
    
    return render_template('shop.html', 
                         prizes=prizes,
                         pagination=pagination,
                         settings=settings,
                         can_shop=can_shop,
                         cart_items_count=len(current_user.cart_items),
                         current_sort=sort)

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
    
    # Проверяем, открыт ли магазин
    settings = ShopSettings.get_settings()
    if not settings.is_open:
        return jsonify({'success': False, 'message': 'Магазин временно закрыт'})
    
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
    
    # Проверяем, открыт ли магазин
    settings = ShopSettings.get_settings()
    if not settings.is_open:
        return jsonify({'success': False, 'message': 'Магазин временно закрыт'})
    
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
    
    # Проверяем, открыт ли магазин
    settings = ShopSettings.get_settings()
    if not settings.is_open:
        return jsonify({'success': False, 'message': 'Магазин временно закрыт'})
    
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
    
    # Получаем параметр страницы
    page = request.args.get('page', 1, type=int)
    per_page = 20  # количество записей на странице
    
    # Получаем заявки с пагинацией, отсортированные по дате (новые сверху)
    orders = PrizePurchase.query.order_by(PrizePurchase.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
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
        settings.is_season_active = 'is_season_active' in request.form
        settings.allow_category_change = 'allow_category_change' in request.form
        settings.closed_season_message = request.form.get('closed_season_message', '')
        db.session.commit()
        flash('Настройки турниров обновлены', 'success')
        return redirect(url_for('tournament_settings'))
    
    return render_template('admin/tournament_settings.html', settings=settings)

@app.route('/admin/news')
@login_required
def admin_news():
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    news_list = News.query.order_by(News.created_at.desc()).all()
    return render_template('admin/news.html', news_list=news_list)

@app.route('/admin/news/add', methods=['GET', 'POST'])
@login_required
def admin_add_news():
    if not current_user.is_admin:
        flash('У вас нет доступа к этой страницы', 'danger')
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        short_description = request.form.get('short_description')
        full_content = request.form.get('full_content')
        is_published = 'is_published' in request.form
        
        if not title or not short_description or not full_content:
            flash('Все поля обязательны для заполнения', 'error')
            return render_template('admin/add_news.html')
        
        # Создаем новость
        news = News(
            title=title,
            short_description=short_description,
            full_content=full_content,
            is_published=is_published
        )
        
        db.session.add(news)
        db.session.flush()  # Получаем ID новости
        
        # Обработка множественных изображений
        uploaded_files = request.files.getlist('images')
        captions = request.form.getlist('captions')
        main_image_index = request.form.get('main_image_index', type=int)
        
        main_image_set = False  # Флаг для отслеживания главного изображения
        
        for i, file in enumerate(uploaded_files):
            if file and file.filename:
                # Загружаем изображение в S3
                image_filename = upload_file_to_s3(file, 'news')
                if image_filename:
                    # Получаем подпись для изображения
                    caption = captions[i] if i < len(captions) else None
                    
                    # Определяем, является ли это главным изображением
                    is_main = (main_image_index is not None and i == main_image_index) or (i == 0 and main_image_index is None and not main_image_set)
                    
                    # Создаем запись об изображении
                    news_image = NewsImage(
                        news_id=news.id,
                        image_filename=image_filename,
                        caption=caption,
                        order_index=i,
                        is_main=is_main
                    )
                    
                    db.session.add(news_image)
                    
                    # Если это главное изображение, сохраняем его в поле image для обратной совместимости
                    if is_main:
                        news.image = image_filename
                        main_image_set = True
        
        db.session.commit()
        
        flash('Новость успешно добавлена', 'success')
        return redirect(url_for('admin_news'))
    
    return render_template('admin/add_news.html')

@app.route('/admin/news/<int:news_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_edit_news(news_id):
    if not current_user.is_admin:
        flash('У вас нет доступа к этой страницы', 'danger')
        return redirect(url_for('home'))
    
    news = News.query.get_or_404(news_id)
    
    if request.method == 'POST':
        news.title = request.form.get('title')
        news.short_description = request.form.get('short_description')
        news.full_content = request.form.get('full_content')
        news.is_published = 'is_published' in request.form
        
        # Обработка удаления существующих изображений
        existing_image_ids = request.form.getlist('existing_image_ids')
        
        for image in news.images:
            if str(image.id) not in existing_image_ids:
                # Удаляем изображение из S3
                delete_file_from_s3(image.image_filename, 'news')
                # Удаляем запись из базы
                db.session.delete(image)
        
        # Обработка новых изображений
        uploaded_files = request.files.getlist('images')
        captions = request.form.getlist('captions')
        main_image_index = request.form.get('main_image_index', type=int)
        
        # Получаем текущий максимальный order_index
        max_order = db.session.query(db.func.max(NewsImage.order_index)).filter_by(news_id=news.id).scalar() or -1
        
        new_images_added = False
        main_image_set = False  # Флаг для отслеживания главного изображения
        
        for i, file in enumerate(uploaded_files):
            if file and file.filename:
                # Загружаем изображение в S3
                image_filename = upload_file_to_s3(file, 'news')
                if image_filename:
                    new_images_added = True
                    # Получаем подпись для изображения
                    caption = captions[i] if i < len(captions) else None
                    
                    # Определяем, является ли это главным изображением
                    # Если main_image_index указан и равен текущему индексу, или если это первое изображение и главное не выбрано
                    is_main = (main_image_index is not None and i == main_image_index) or (i == 0 and main_image_index is None and not main_image_set)
                    
                    # Создаем запись об изображении
                    news_image = NewsImage(
                        news_id=news.id,
                        image_filename=image_filename,
                        caption=caption,
                        order_index=max_order + 1 + i,
                        is_main=is_main
                    )
                    
                    db.session.add(news_image)
                    
                    # Если это главное изображение, обновляем поле image
                    if is_main:
                        news.image = image_filename
                        main_image_set = True
        
        # Обновляем главное изображение среди существующих
        if main_image_index is not None and not new_images_added:
            # Сбрасываем все флаги is_main
            NewsImage.query.filter_by(news_id=news.id).update({'is_main': False})
            
            # Устанавливаем новый главный флаг
            remaining_images = list(news.images)  # Преобразуем в список для индексации
            if main_image_index < len(remaining_images):
                main_image = remaining_images[main_image_index]
                main_image.is_main = True
                news.image = main_image.image_filename
            else:
                # Если индекс неверный, сбрасываем главное изображение
                news.image = None
        elif not new_images_added and not news.images:
            # Если нет новых изображений и нет существующих, сбрасываем главное изображение
            news.image = None
        
        db.session.commit()
        flash('Новость успешно обновлена', 'success')
        return redirect(url_for('admin_news'))
    
    return render_template('admin/edit_news.html', news=news)

@app.route('/admin/news/<int:news_id>/delete', methods=['POST'])
@login_required
def admin_delete_news(news_id):
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    news = News.query.get_or_404(news_id)
    
    # Удаляем все изображения из S3
    for image in news.images:
        delete_file_from_s3(image.image_filename, 'news')
    
    # Удаляем главное изображение из S3 (для обратной совместимости)
    if news.image:
        delete_file_from_s3(news.image, 'news')
    
    db.session.delete(news)
    db.session.commit()
    
    flash('Новость успешно удалена', 'success')
    return redirect(url_for('admin_news'))

@app.route('/admin/teachers')
@login_required
def admin_teachers():
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    # Получаем параметры сортировки и пагинации
    page = request.args.get('page', 1, type=int)
    sort_by = request.args.get('sort', 'created_at')  # created_at, tournaments, active_students
    sort_order = request.args.get('order', 'desc')  # asc, desc
    per_page = 20  # Количество учителей на странице
    
    # Получаем всех учителей для подсчета статистики
    all_teachers = Teacher.query.all()
    
    # Подсчитываем статистику для всех учителей
    for teacher in all_teachers:
        students = teacher.students
        total_tournaments = sum(student.tournaments_count or 0 for student in students)
        active_students = sum(1 for student in students if student.tournaments_count and student.tournaments_count > 0)
        
        teacher.total_students_tournaments = total_tournaments
        teacher.active_students_count = active_students
    
    # Сортируем учителей
    if sort_by == 'tournaments':
        all_teachers.sort(key=lambda x: x.total_students_tournaments, reverse=(sort_order == 'desc'))
    elif sort_by == 'active_students':
        all_teachers.sort(key=lambda x: x.active_students_count, reverse=(sort_order == 'desc'))
    else:  # sort_by == 'created_at'
        all_teachers.sort(key=lambda x: x.created_at, reverse=(sort_order == 'desc'))
    
    # Создаем пагинацию вручную
    from flask_sqlalchemy import Pagination
    total_teachers = len(all_teachers)
    start = (page - 1) * per_page
    end = start + per_page
    teachers = all_teachers[start:end]
    
    teachers_pagination = Pagination(
        query=None,
        page=page,
        per_page=per_page,
        total=total_teachers,
        items=teachers
    )
    
    return render_template('admin/teachers.html', 
                         teachers=teachers,
                         teachers_pagination=teachers_pagination,
                         sort_by=sort_by,
                         sort_order=sort_order)

@app.route('/admin/teachers/<int:teacher_id>/toggle-block', methods=['POST'])
@login_required
def admin_toggle_teacher_block(teacher_id):
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    teacher = Teacher.query.get_or_404(teacher_id)
    
    if teacher.is_blocked:
        teacher.is_blocked = False
        teacher.block_reason = None
        flash(f'Учитель {teacher.full_name} разблокирован', 'success')
    else:
        teacher.is_blocked = True
        teacher.block_reason = request.form.get('reason', 'Блокировка администратором')
        flash(f'Учитель {teacher.full_name} заблокирован', 'warning')
    
    db.session.commit()
    return redirect(url_for('admin_teachers'))

@app.route('/admin/teachers/<int:teacher_id>/details')
@login_required
def admin_teacher_details(teacher_id):
    if not current_user.is_admin:
        flash('У вас нет доступа к этой странице', 'danger')
        return redirect(url_for('home'))
    
    teacher = Teacher.query.get_or_404(teacher_id)
    
    # Подсчитываем статистику учеников
    students = teacher.students
    total_students = len(students)
    
    # Подсчитываем активных учеников (участвовавших в турнирах)
    active_students = sum(1 for student in students if student.tournaments_count and student.tournaments_count > 0)
    
    # Подсчитываем общее количество турниров учеников
    total_tournaments = sum(student.tournaments_count or 0 for student in students)
    
    # Подсчитываем учеников из того же учреждения образования
    same_institution_students = 0
    if teacher.educational_institution:
        same_institution_students = sum(1 for student in students 
                                     if student.educational_institution and 
                                     student.educational_institution.id == teacher.educational_institution.id)
    
    # Получаем номер страницы для учеников
    students_page = request.args.get('students_page', 1, type=int)
    students_per_page = 10  # Количество учеников на странице
    
    # Получаем учеников с пагинацией
    students_pagination = None
    if students:
        # Создаем пагинацию для учеников
        from flask_sqlalchemy import Pagination
        total_students_count = len(students)
        start = (students_page - 1) * students_per_page
        end = start + students_per_page
        paginated_students = students[start:end]
        
        students_pagination = Pagination(
            query=None,  # Не используем query для пагинации
            page=students_page,
            per_page=students_per_page,
            total=total_students_count,
            items=paginated_students
        )
        students_to_show = paginated_students
    else:
        students_to_show = []
    

    
    return render_template('admin/teacher_details.html',
                         teacher=teacher,
                         total_students=total_students,
                         active_students=active_students,
                         total_tournaments=total_tournaments,
                         same_institution_students=same_institution_students,
                         students=students_to_show,
                         students_pagination=students_pagination)

@app.before_first_request
def clear_sessions():
    # Очищаем все токены сессий при запуске приложения
    cleanup_all_sessions()
    with app.app_context():
        # Сначала создаем все таблицы
        print("Создание таблиц базы данных...")
        db.create_all()

        # Затем создаем администратора
        print("Создание администратора...")
        create_admin_user()

        # Только после создания таблиц выполняем остальные операции
        print("Очистка сессий...")
        cleanup_all_sessions()

        print("Восстановление задач планировщика...")
        restore_scheduler_jobs()

        print("Инициализация задач планировщика...")
        initialize_scheduler_jobs()

        print("Проверка истекших платежей...")
        check_expired_payments()

        print("Приложение готово к запуску!")
    # # Добавляем задачу очистки сессий (только на одном сервере)
    # add_scheduler_job(
    #     cleanup_old_sessions,
    #     datetime.now() + timedelta(hours=24),  # run_date не используется для interval
    #     None,
    #     'cleanup_sessions',
    #     interval_hours=24  # Интервальная задача каждые 24 часа
    # )
    #


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
    
    is_strong, message = is_password_strong(new_password)
    if not is_strong:
        return jsonify({
            'success': False,
            'message': message
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
    # Используем те же категории, что и в интерфейсе рейтинга
    categories = ['1-2', '3', '4', '5', '6', '7', '8', '9', '10', '11']
    
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
    #if response.status_code == 200 and request.endpoint in ['submit_answer', 'buy_tickets', 'use_tickets']:
    if response.status_code == 200 and request.endpoint in []:
        update_category_ranks()
    return response

@app.route('/update-profile', methods=['POST'])
@login_required
def update_profile():
    data = request.get_json()
    
    # Получаем данные из запроса
    student_name = data.get('student_name', '').strip()
    parent_name = data.get('parent_name', '').strip()
    phone = data.get('phone', '').strip()
    category = data.get('category')
    educational_institution_name = data.get('educational_institution_name', '').strip()
    educational_institution_id = data.get('educational_institution_id', '').strip()
    new_password = data.get('new_password', '').strip()
    
    # Проверяем обязательные поля
    if not student_name:
        return jsonify({'success': False, 'message': 'Пожалуйста, введите фамилию и имя учащегося'})
    
    if not parent_name:
        return jsonify({'success': False, 'message': 'Пожалуйста, введите ФИО законного представителя'})
    
    if not phone:
        return jsonify({'success': False, 'message': 'Пожалуйста, введите номер телефона'})
    
    if not category:
        return jsonify({'success': False, 'message': 'Пожалуйста, выберите группу'})
    
    if not educational_institution_name:
        return jsonify({'success': False, 'message': 'Пожалуйста, введите учреждение образования'})
    
    # Валидация имени учащегося
    if len(student_name) < 2:
        return jsonify({'success': False, 'message': 'Фамилия и имя учащегося должны содержать минимум 2 символа'})
    
    if not re.match(r'^[а-яёА-ЯЁ\s]+$', student_name):
        return jsonify({'success': False, 'message': 'Фамилия и имя учащегося должны содержать только русские буквы'})
    
    # Валидация имени родителя
    if len(parent_name) < 2:
        return jsonify({'success': False, 'message': 'ФИО законного представителя должно содержать минимум 2 символа'})
    
    if not re.match(r'^[а-яёА-ЯЁ\s]+$', parent_name):
        return jsonify({'success': False, 'message': 'ФИО законного представителя должно содержать только русские буквы'})
    
    # Валидация телефона
    if phone.startswith('+375'):
        if not re.match(r'^\+375\d{9}$', phone):
            return jsonify({'success': False, 'message': 'Неверный формат номера телефона для Беларуси (+375XXXXXXXXX)'})
    elif phone.startswith('+7'):
        if not re.match(r'^\+7\d{10}$', phone):
            return jsonify({'success': False, 'message': 'Неверный формат номера телефона для России (+7XXXXXXXXXX)'})
    else:
        return jsonify({'success': False, 'message': 'Неверный формат номера телефона'})
    
    # Проверяем, не занят ли телефон другим пользователем
    existing_user = User.query.filter_by(phone=phone).first()
    if existing_user and existing_user.id != current_user.id:
        return jsonify({'success': False, 'message': 'Этот номер телефона уже используется другим пользователем'})
    
    # Проверяем категорию
    valid_categories = ['1-2', '3', '4', '5', '6', '7', '8', '9', '10', '11']
    if category not in valid_categories:
        return jsonify({'success': False, 'message': 'Неверная категория'})
    
    # Проверяем статус сезона
    settings = TournamentSettings.get_settings()
    if settings.is_season_active and category != current_user.category:
        if not settings.allow_category_change:
            return jsonify({'success': False, 'message': 'Изменение группы временно недоступно'})
        else:
            return jsonify({'success': False, 'message': 'Изменение группы недоступно во время активного сезона'})
    
    # Валидация пароля
    if new_password:
        is_strong, message = is_password_strong(new_password)
        if not is_strong:
            return jsonify({'success': False, 'message': message})
    
    try:
        # Обрабатываем учреждение образования
        if educational_institution_id:
            # Если указан ID, используем существующее учреждение
            current_user.educational_institution_id = int(educational_institution_id)
        else:
            # Если ID не указан, создаем новое учреждение или находим существующее
            existing_institution = EducationalInstitution.query.filter_by(name=educational_institution_name).first()
            if existing_institution:
                current_user.educational_institution_id = existing_institution.id
            else:
                # Создаем новое учреждение
                new_institution = EducationalInstitution(
                    name=educational_institution_name,
                    address=''  # Пустой адрес для новых учреждений
                )
                db.session.add(new_institution)
                db.session.flush()  # Получаем ID нового учреждения
                current_user.educational_institution_id = new_institution.id
        
        # Обновляем данные пользователя
        current_user.student_name = student_name
        current_user.parent_name = parent_name
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
        # Очищаем счет, время решения задач и ранги для всех пользователей
        users = User.query.filter_by(is_admin=False).all()
        for user in users:
            user.balance = 0
            user.total_tournament_time = 0
            user.tournaments_count = 0  # Очищаем количество турниров
            user.category_rank = None  # Обнуляем ранг в категории
        
        # Очищаем историю решенных задач
        SolvedTask.query.delete()
        
        # Очищаем историю участия в турнирах
        TournamentParticipation.query.delete()
        
        # Очищаем все задачи
        Task.query.delete()
        
        # Очищаем все турниры
        Tournament.query.delete()
        
        # Очищаем настройки турниров
        TournamentSettings.query.delete()
        
        # Создаем новые настройки турниров с дефолтными значениями
        settings = TournamentSettings()
        db.session.add(settings)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Данные пользователей, турниров и задач успешно очищены'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Произошла ошибка при очистке данных: {str(e)}'
        }), 500

@app.route('/reset-session', methods=['POST'])
def reset_session():
    """Сброс сессии пользователя без авторизации (для входа с другого устройства)"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not username or not password:
            return jsonify({'success': False, 'message': 'Необходимо указать логин и пароль'})
        
        # Ищем пользователя (регистронезависимый поиск)
        user = User.query.filter(User.username.ilike(username)).first()
        
        if not user:
            return jsonify({'success': False, 'message': 'Неверный логин или пароль'})
        
        if not user.check_password(password):
            return jsonify({'success': False, 'message': 'Неверный логин или пароль'})
        
        if user.is_blocked:
            return jsonify({'success': False, 'message': 'Ваш аккаунт заблокирован'})
        
        if not user.is_active:
            return jsonify({'success': False, 'message': 'Пожалуйста, подтвердите ваш email перед входом'})
        
        # Проверяем, есть ли активная сессия
        active_session = UserSession.query.filter_by(user_id=user.id, is_active=True).first()
        if not active_session:
            return jsonify({'success': False, 'message': 'У вас нет активных сессий для сброса'})
        
        # Деактивируем все сессии пользователя
        deactivate_user_session(user.id)
        
        return jsonify({
            'success': True, 
            'message': 'Сессия на другом устройстве успешно закрыта'
        })
        
    except Exception as e:
        print(f"Ошибка при сбросе сессии: {e}")
        return jsonify({'success': False, 'message': 'Произошла ошибка при сбросе сессии'})

@app.route('/logout-all-devices', methods=['POST'])
@login_required
def logout_all_devices():
    """Принудительный выход из всех устройств"""
    # Деактивируем все сессии пользователя
    deactivate_user_session(current_user.id)
    
    # Очищаем текущую сессию
    session.pop('session_token', None)
    logout_user()
    
    flash('Вы успешно вышли из всех устройств', 'success')
    return redirect(url_for('login'))

class UserSession(db.Model):
    __tablename__ = "user_sessions"

    id = db.Column(db.Integer, primary_key=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True, nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), index=True, nullable=True)
    user_type = db.Column(db.String(20), default='user', index=True)  # 'user' или 'teacher'
    is_active = db.Column(db.Boolean, default=False)
    session_token = db.Column(db.String(255), unique=True, index=True)
    device_info = db.Column(db.String(255), nullable=True)
    last_active = db.Column(db.DateTime, default=datetime.now)
    created_at = db.Column(db.DateTime, default=datetime.now)

    user = db.relationship('User', backref=db.backref('sessions', lazy=True))
    teacher = db.relationship('Teacher', backref=db.backref('sessions', lazy=True))

    def update_last_active(self):
        self.last_active = datetime.now()
        db.session.commit()

class News(db.Model):
    __tablename__ = "news"

    id = db.Column(db.Integer, primary_key=True, index=True)
    title = db.Column(db.String(200), nullable=False)
    short_description = db.Column(db.Text, nullable=False)
    full_content = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(500), nullable=True)  # Главное изображение (для обратной совместимости)
    is_published = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Связь с изображениями
    images = db.relationship('NewsImage', backref='news', lazy=True, cascade='all, delete-orphan', order_by='NewsImage.order_index')

class NewsImage(db.Model):
    __tablename__ = "news_images"
    
    id = db.Column(db.Integer, primary_key=True, index=True)
    news_id = db.Column(db.Integer, db.ForeignKey('news.id', ondelete='CASCADE'), nullable=False)
    image_filename = db.Column(db.String(500), nullable=False)  # Имя файла в S3
    caption = db.Column(db.String(200), nullable=True)  # Подпись к изображению
    order_index = db.Column(db.Integer, default=0)  # Порядок отображения
    is_main = db.Column(db.Boolean, default=False)  # Главное изображение
    created_at = db.Column(db.DateTime, default=datetime.now)

class SchedulerJob(db.Model):
    __tablename__ = "scheduler_jobs"
    
    id = db.Column(db.Integer, primary_key=True, index=True)
    job_id = db.Column(db.String(100), unique=True, nullable=False, index=True)  # Уникальный ID задачи
    job_type = db.Column(db.String(50), nullable=False)  # Тип задачи (start_tournament, end_tournament, cleanup_sessions)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=True)  # ID турнира (если применимо)
    run_date = db.Column(db.DateTime, nullable=False)  # Время выполнения
    is_active = db.Column(db.Boolean, default=True)  # Активна ли задача
    server_id = db.Column(db.String(100), nullable=False, index=True)  # Уникальный ID сервера
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Связь с турниром (если задача связана с турниром)
    tournament = db.relationship('Tournament', backref=db.backref('scheduler_jobs', lazy=True))

class EducationalInstitution(db.Model):
    __tablename__ = "educational_institutions"
    
    id = db.Column(db.Integer, primary_key=True, index=True)
    name = db.Column(db.String(500), nullable=False)  # Название учреждения образования
    address = db.Column(db.Text, nullable=False)  # Адрес учреждения
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

class ReferralLink(db.Model):
    __tablename__ = "referral_links"
    
    id = db.Column(db.Integer, primary_key=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    referral_code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # Связи
    user = db.relationship('User', backref=db.backref('referral_links', lazy=True, cascade='all, delete-orphan'))
    referrals = db.relationship('Referral', backref='referral_link', lazy=True, cascade='all, delete-orphan')

class Referral(db.Model):
    __tablename__ = "referrals"
    
    id = db.Column(db.Integer, primary_key=True, index=True)
    referrer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)  # Кто пригласил
    referred_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)  # Кого пригласили
    referral_link_id = db.Column(db.Integer, db.ForeignKey('referral_links.id'), nullable=False)
    bonus_paid = db.Column(db.Boolean, default=False)  # Выплачен ли бонус
    bonus_paid_at = db.Column(db.DateTime, nullable=True)  # Когда выплачен бонус
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # Связи
    referrer = db.relationship('User', foreign_keys=[referrer_id], backref=db.backref('referrals_sent', lazy=True, cascade='all, delete-orphan'))
    referred = db.relationship('User', foreign_keys=[referred_id], backref=db.backref('referrals_received', lazy=True, cascade='all, delete-orphan'))

class Teacher(UserMixin, db.Model):
    __tablename__ = "teachers"
    
    id = db.Column(db.Integer, primary_key=True, index=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    hashed_password = db.Column(db.String(128), nullable=False, index=True)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    full_name = db.Column(db.String(100), nullable=False)  # ФИО учителя
    is_active = db.Column(db.Boolean, default=False, index=True)
    is_blocked = db.Column(db.Boolean, default=False, index=True)
    block_reason = db.Column(db.Text, nullable=True)
    email_confirmation_token = db.Column(db.String(100), unique=True, nullable=True, index=True)
    session_token = db.Column(db.String(100), unique=True, nullable=True, index=True)
    temp_password = db.Column(db.String(128), nullable=True)
    reset_password_token = db.Column(db.String(100), unique=True, nullable=True, index=True)
    reset_password_token_expires = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Связь с образовательным учреждением
    educational_institution_id = db.Column(db.Integer, db.ForeignKey('educational_institutions.id'), nullable=True)
    educational_institution = db.relationship('EducationalInstitution', backref=db.backref('teachers', lazy=True))
    
    def set_password(self, password):
        self.hashed_password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.hashed_password, password)

    def generate_confirmation_token(self):
        token = secrets.token_urlsafe(32)
        self.email_confirmation_token = token
        db.session.commit()
        return token
    
    def get_id(self):
        """Возвращает ID для Flask-Login с префиксом 't' для учителей"""
        return f't{self.id}'

class TeacherInviteLink(db.Model):
    __tablename__ = "teacher_invite_links"
    
    id = db.Column(db.Integer, primary_key=True, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False, index=True)
    invite_code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # Связи
    teacher = db.relationship('Teacher', backref=db.backref('invite_links', lazy=True))

def cleanup_all_sessions():
    """Деактивирует все активные сессии при перезагрузке сервера"""
    try:
        UserSession.query.filter_by(is_active=True).update({'is_active': False})
        db.session.commit()
    except Exception as e:
        print(f"Ошибка при очистке сессий: {e}")

@atexit.register
def cleanup_on_exit():
    """Вызывается при завершении работы приложения"""
    cleanup_all_sessions()

def signal_handler(signum, frame):
    """Обработчик сигналов завершения"""
    print(f"Получен сигнал {signum}, завершаем работу...")
    cleanup_all_sessions()
    exit(0)

# Регистрируем обработчики сигналов
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

def cleanup_old_sessions():
    """Удаляет устаревшие сессии и пользователей с неподтвержденными email из базы данных"""
    try:
        # Удаляем сессии старше 1 недели
        one_week_ago = datetime.now() - timedelta(days=7)
        deleted_sessions = UserSession.query.filter(
            UserSession.created_at < one_week_ago,
            UserSession.is_active == False
        ).delete()
        
        # Удаляем пользователей с неподтвержденными email старше 3 дней
        thirty_days_ago = datetime.now() - timedelta(days=3)
        deleted_users = User.query.filter(
            User.is_active == False,
            User.email_confirmation_token.isnot(None),
            User.created_at < thirty_days_ago,
            User.is_admin == False  # Не удаляем администраторов
        ).delete()
        
        db.session.commit()
        
        print(f"Очистка завершена: удалено {deleted_sessions} сессий и {deleted_users} пользователей с неподтвержденными email")
        
        # НЕ удаляем запись о задаче из БД, так как это интервальная задача
        # которая должна выполняться каждые 24 часа
        
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при очистке устаревших сессий и пользователей: {e}")

# Настраиваем периодическую очистку сессий
#add_scheduler_job(
#    cleanup_old_sessions,
#    datetime.now() + timedelta(hours=24),  # Первый запуск через 24 часа
#    None,
#    'cleanup_sessions'
#)



# Константы для защиты от брутфорса
MAX_LOGIN_ATTEMPTS = 5  # Максимальное количество попыток
LOGIN_TIMEOUT = 1800  # Время блокировки в секундах (30 минут)
LOGIN_ATTEMPTS_COOKIE = 'login_attempts'
LOGIN_BLOCKED_UNTIL_COOKIE = 'login_blocked_until'

def get_login_attempts():
    """Получает количество попыток входа из куки"""
    attempts = request.cookies.get(LOGIN_ATTEMPTS_COOKIE)
    try:
        return int(attempts) if attempts else 0
    except (ValueError, TypeError):
        return 0

def increment_login_attempts():
    """Увеличивает счетчик попыток входа"""
    attempts = get_login_attempts() + 1
    response = make_response(redirect(url_for('login')))
    response.set_cookie(
        LOGIN_ATTEMPTS_COOKIE,
        str(attempts),
        max_age=LOGIN_TIMEOUT,
        secure=False,  # Изменено на False, так как SESSION_COOKIE_SECURE тоже False
        httponly=True,
        samesite='Lax'
    )
    return response

def reset_login_attempts():
    """Сбрасывает счетчик попыток входа"""
    response = make_response(redirect(url_for('home')))
    response.set_cookie(
        LOGIN_ATTEMPTS_COOKIE,
        '0',  # Явно устанавливаем 0
        max_age=0,
        secure=False,  # Изменено на False
        httponly=True,
        samesite='Lax'
    )
    response.set_cookie(
        LOGIN_BLOCKED_UNTIL_COOKIE,
        '',
        max_age=0,
        secure=False,  # Изменено на False
        httponly=True,
        samesite='Lax'
    )
    return response

def is_login_blocked():
    """Проверяет, заблокирован ли вход"""
    blocked_until = request.cookies.get(LOGIN_BLOCKED_UNTIL_COOKIE)
    if blocked_until:
        try:
            blocked_time = datetime.fromtimestamp(float(blocked_until))
            if datetime.now() < blocked_time:
                return True
        except (ValueError, TypeError):
            pass
    return False

def block_login():
    """Блокирует вход на определенное время"""
    blocked_until = datetime.now() + timedelta(seconds=LOGIN_TIMEOUT)
    response = make_response(redirect(url_for('login')))
    response.set_cookie(
        LOGIN_BLOCKED_UNTIL_COOKIE,
        str(blocked_until.timestamp()),
        max_age=LOGIN_TIMEOUT,
        secure=False,  # Изменено на False
        httponly=True,
        samesite='Lax'
    )
    return response

# Функции для работы с реферальными ссылками
def generate_referral_code():
    """Генерирует уникальный реферальный код"""
    while True:
        code = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=8))
        if not ReferralLink.query.filter_by(referral_code=code).first():
            return code

def create_referral_link(user_id):
    """Создает реферальную ссылку для пользователя"""
    # Проверяем, есть ли уже активная ссылка
    existing_link = ReferralLink.query.filter_by(user_id=user_id, is_active=True).first()
    if existing_link:
        return existing_link
    
    # Создаем новую ссылку
    referral_code = generate_referral_code()
    new_link = ReferralLink(
        user_id=user_id,
        referral_code=referral_code,
        is_active=True
    )
    db.session.add(new_link)
    db.session.commit()
    return new_link

def get_referral_link_by_code(code):
    """Получает реферальную ссылку по коду"""
    return ReferralLink.query.filter_by(referral_code=code, is_active=True).first()

def create_referral(referrer_id, referred_id, referral_link_id):
    """Создает запись о реферале"""
    referral = Referral(
        referrer_id=referrer_id,
        referred_id=referred_id,
        referral_link_id=referral_link_id,
        bonus_paid=False
    )
    db.session.add(referral)
    db.session.commit()
    return referral

def pay_referral_bonus(referral_id):
    """Выплачивает бонус за реферала"""
    referral = Referral.query.get(referral_id)
    if not referral or referral.bonus_paid:
        return False
    
    try:
        # Начисляем бонусы рефереру
        referrer = User.query.get(referral.referrer_id)
        if referrer:
            referrer.balance += REFERRAL_BONUS_POINTS
            referrer.tickets += REFERRAL_BONUS_TICKETS
            
            # Отмечаем бонус как выплаченный
            referral.bonus_paid = True
            referral.bonus_paid_at = datetime.now()
            
            db.session.commit()
            return True
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при выплате реферального бонуса: {e}")
        return False
    
    return False

# Функции для работы с пригласительными ссылками учителей
def generate_teacher_invite_code():
    """Генерирует уникальный код приглашения для учителя"""
    while True:
        code = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=10))
        if not TeacherInviteLink.query.filter_by(invite_code=code).first():
            return code

def create_teacher_invite_link(teacher_id):
    """Создает пригласительную ссылку для учителя"""
    # Проверяем, есть ли уже активная ссылка
    existing_link = TeacherInviteLink.query.filter_by(teacher_id=teacher_id, is_active=True).first()
    if existing_link:
        return existing_link
    
    invite_code = generate_teacher_invite_code()
    new_link = TeacherInviteLink(
        teacher_id=teacher_id,
        invite_code=invite_code,
        is_active=True
    )
    db.session.add(new_link)
    db.session.commit()
    return new_link

def get_teacher_invite_link_by_code(code):
    """Получает пригласительную ссылку учителя по коду"""
    return TeacherInviteLink.query.filter_by(invite_code=code, is_active=True).first()

def check_and_pay_referral_bonuses():
    """Проверяет и выплачивает бонусы за рефералов, которые участвовали в турнирах"""
    try:
        # Находим рефералов, которые участвовали в турнирах, но бонус еще не выплачен
        referrals_to_pay = db.session.query(Referral).join(
            User, Referral.referred_id == User.id
        ).filter(
            Referral.bonus_paid == False,
            User.tournaments_count > 0
        ).all()
        
        paid_count = 0
        for referral in referrals_to_pay:
            if pay_referral_bonus(referral.id):
                paid_count += 1
        
        if paid_count > 0:
            print(f"Выплачено {paid_count} реферальных бонусов")
        
        return paid_count
        
    except Exception as e:
        print(f"Ошибка при проверке реферальных бонусов: {e}")
        return 0

@app.route('/rating/search')
def rating_search():
    query = sanitize_input(request.args.get('q', ''), 100)
    category = request.args.get('category', '')
    
    # Валидация входных данных
    if not query:  # Ограничиваем длину запроса
        return jsonify({'users': []})
    
    # Проверяем, что категория содержит только допустимые значения
    valid_categories = ['1-2', '3', '4', '5', '6', '7', '8', '9', '10', '11']
    if category and category not in valid_categories:
        return jsonify({'users': []})
    
    # Проверяем, должен ли показываться полный рейтинг
    show_full_rating = False
    if current_user.is_authenticated:
        # Проверяем тип пользователя
        if hasattr(current_user, 'is_admin') and current_user.is_admin:
            # Для администраторов проверяем параметр режима
            mode = request.args.get('mode')
            show_full_rating = mode == 'full'
        elif hasattr(current_user, 'tournaments_count'):
            # Для обычных пользователей проверяем участие в турнирах
            show_full_rating = current_user.tournaments_count > 0
        # Для учителей показываем только топ-10 (show_full_rating остается False)
    
    # Базовый запрос для поиска
    search_query = (
        db.session.query(
            User,
            func.count(SolvedTask.id).label('solved_tasks_count'),
            func.sum(case((SolvedTask.is_correct == True, 1), else_=0)).label('correct_tasks_count')
        )
        .outerjoin(SolvedTask, User.id == SolvedTask.user_id)
        .filter(User.is_admin == False)
        .filter(
            db.or_(
                User.username.ilike('%' + query + '%'),
                User.student_name.ilike('%' + query + '%')
            )
        )
    )
    
    # Фильтруем по категории, если указана
    if category:
        search_query = search_query.filter(User.category == category)
    
    # Группируем и сортируем
    search_query = search_query.group_by(User.id).order_by(User.balance.desc())
    
    # Применяем лимит в зависимости от прав пользователя
    if show_full_rating:
        search_results = search_query.limit(50).all()  # Больше результатов для полного рейтинга
    else:
        search_results = search_query.limit(10).all()  # Стандартный лимит
    
    # Обрабатываем результаты
    users = []
    for user, solved_tasks_count, correct_tasks_count in search_results:
        user.solved_tasks_count = correct_tasks_count or 0
        user.success_rate = round((correct_tasks_count / solved_tasks_count * 100) if solved_tasks_count else 0, 1)
        user.is_current_user = False
        
        # Ранг пользователя уже есть в поле category_rank
        # user.category_rank уже содержит актуальное значение
        
        # Используем поля из модели User для статистики турниров
        user.tournaments_count = user.tournaments_count or 0
        user.total_tournament_time = user.total_tournament_time or 0
        
        users.append({
            'id': user.id,
            'username': user.username,
            'student_name': user.student_name,
            'category': user.category,
            'balance': user.balance,
            'solved_tasks_count': user.solved_tasks_count,
            'success_rate': user.success_rate,
            'category_rank': user.category_rank,
            'tournaments_count': user.tournaments_count,
            'total_tournament_time': user.total_tournament_time,
            'is_current_user': user.id == current_user.id if current_user.is_authenticated else False
        })
    
    return jsonify({'users': users})

@app.context_processor
def inject_s3_utils():
    """Добавляет функции S3 в контекст шаблонов"""
    return {
        'get_s3_url': get_s3_url,
        'get_file_url': get_file_url
    }

@app.context_processor
def inject_csrf_token():
    """Добавляет CSRF токен в контекст шаблонов"""
    return dict(csrf_token=lambda: secrets.token_urlsafe(32))

def cleanup_other_servers_jobs():
    """Удаляет задачи других серверов, которые могли остаться после перезапуска"""
    try:
        # Удаляем задачи других серверов, которые старше 1 часа
        one_hour_ago = datetime.now() - timedelta(hours=1)
        other_servers_jobs = SchedulerJob.query.filter(
            SchedulerJob.server_id != SERVER_ID,
            SchedulerJob.created_at < one_hour_ago
        ).all()
        
        for job in other_servers_jobs:
            db.session.delete(job)
        
        if other_servers_jobs:
            db.session.commit()
            print(f"Удалено {len(other_servers_jobs)} задач других серверов")
            
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при очистке задач других серверов: {e}")

def check_expired_payments():
    """Проверяет и обновляет статусы истекших платежей для всех платежных систем"""
    try:
        # Проверяем платежи ЮKassa
        check_yukassa_expired_payments()
        
        # Проверяем платежи Express-Pay
        check_express_pay_expired_payments()
        
    except Exception as e:
        print(f"Ошибка при проверке истекших платежей: {e}")

def check_yukassa_expired_payments():
    """Проверяет и обновляет статусы истекших платежей ЮKassa"""
    try:
        from yukassa_service import yukassa_service
        
        # Получаем все pending платежи ЮKassa
        pending_purchases = TicketPurchase.query.filter_by(
            payment_status='pending',
            payment_system='yukassa'
        ).all()
        
        expired_count = 0
        for purchase in pending_purchases:
            if purchase.payment_id:
                try:
                    # Получаем актуальную информацию о платеже
                    payment_info = yukassa_service.get_payment_info(purchase.payment_id)
                    
                    # Проверяем, истек ли платеж
                    if yukassa_service.is_payment_expired(payment_info):
                        purchase.payment_status = 'expired'
                        expired_count += 1
                        print(f"Платеж ЮKassa {purchase.payment_id} помечен как истекший")
                        
                except Exception as e:
                    print(f"Ошибка при проверке платежа ЮKassa {purchase.payment_id}: {e}")
                    continue
        
        if expired_count > 0:
            db.session.commit()
            print(f"Обновлено {expired_count} истекших платежей ЮKassa")
        
    except Exception as e:
        print(f"Ошибка при проверке истекших платежей ЮKassa: {e}")
        db.session.rollback()

def check_express_pay_expired_payments():
    """Проверяет и обновляет статусы истекших платежей Express-Pay"""
    try:
        from express_pay_service import ExpressPayService
        
        # Получаем все pending платежи Express-Pay
        pending_purchases = TicketPurchase.query.filter_by(
            payment_status='pending',
            payment_system='express_pay'
        ).all()
        
        if not pending_purchases:
            return
        
        # Создаем экземпляр сервиса Express-Pay
        express_pay_service = ExpressPayService()
        
        expired_count = 0
        for purchase in pending_purchases:
            # Проверяем, что payment_id не None и не пустой
            if not purchase.payment_id or purchase.payment_id == 'None' or purchase.payment_id == 'null':
                print(f"Пропускаем покупку {purchase.id}: payment_id отсутствует или равен None")
                continue
            try:
                old_status = purchase.payment_status
                # Получаем актуальный статус платежа через специальный endpoint
                status_response = express_pay_service.get_payment_status(purchase.payment_id)
                status_code = status_response.get('Status')
                status = express_pay_service.parse_payment_status(status_code)
                purchase.payment_status = status

                # Если статус изменился на 'succeeded', начисляем жетоны
                if status == 'succeeded' and old_status != 'succeeded':
                    user = User.query.get(purchase.user_id)
                    if user:
                        user.tickets += purchase.quantity
                        purchase.payment_confirmed_at = datetime.now()
                        print(f"Автоматическая проверка: начислено {purchase.quantity} жетонов пользователю {user.id}")

                # Если платеж истек или отменен, увеличиваем счетчик
                if status in ['expired', 'canceled']:
                    expired_count += 1
                    print(f"Платеж Express-Pay {purchase.payment_id} помечен как {status}")
            except Exception as e:
                print(f"Ошибка при проверке платежа Express-Pay {purchase.payment_id}: {e}")
                continue
        
        if expired_count > 0:
            db.session.commit()
            print(f"Обновлено {expired_count} истекших платежей Express-Pay")
        
    except Exception as e:
        print(f"Ошибка при проверке истекших платежей Express-Pay: {e}")
        db.session.rollback()

def initialize_scheduler_jobs():
    """Инициализация задач планировщика"""
    try:
        # Настраиваем периодическую проверку истекших платежей (только если задача еще не существует)
        existing_job = SchedulerJob.query.filter_by(
            job_type='check_expired_payments',
            is_active=True
        ).first()

        if not existing_job:
            add_scheduler_job(
                check_expired_payments,
                datetime.now() + timedelta(hours=1),  # Первый запуск через 1 час
                None,
                'check_expired_payments',
                interval_hours=1  # Повторять каждый час
            )
            print("Создана задача проверки истекших платежей")
        else:
            print("Задача проверки истекших платежей уже существует")

        # Настраиваем периодическую проверку реферальных бонусов (только если задача еще не существует)
        existing_referral_job = SchedulerJob.query.filter_by(
            job_type='check_referral_bonuses',
            is_active=True
        ).first()

        if not existing_referral_job:
            add_scheduler_job(
                check_and_pay_referral_bonuses,
                datetime.now() + timedelta(hours=1),  # Первый запуск через 2 часа
                None,
                'check_referral_bonuses',
                interval_hours=1  # Повторять каждые 1 часов
            )
            print("Создана задача проверки реферальных бонусов")
        else:
            print("Задача проверки реферальных бонусов уже существует")

        # Настраиваем периодическую очистку сессий (только если задача еще не существует)
        existing_cleanup_job = SchedulerJob.query.filter_by(
            job_type='cleanup_sessions',
            is_active=True
        ).first()

        if not existing_cleanup_job:
            add_scheduler_job(
                cleanup_old_sessions,
                datetime.now() + timedelta(hours=24),  # run_date не используется для interval
                None,
                'cleanup_sessions',
                interval_hours=24  # Интервальная задача каждые 24 часа
            )
            print("Создана задача очистки сессий")
        else:
            print("Задача очистки сессий уже существует")
    except Exception as e:
        print(f"Ошибка при инициализации задач планировщика: {e}")

@app.route('/reset-tutorial', methods=['POST'])
@login_required
def reset_tutorial():
    """Сброс обучения для пользователя"""
    response = make_response(jsonify({'success': True}))
    
    # Удаляем старый куки (для обратной совместимости)
    response.delete_cookie('tutorial_completed')
    
    # Удаляем куки для конкретного пользователя
    cookie_name = f'tutorial_completed_{current_user.id}'
    response.delete_cookie(cookie_name)
    
    return response

@app.route('/api/search-educational-institutions')
def search_educational_institutions():
    query = sanitize_input(request.args.get('q', ''), 200)
    # Валидация входных данных
    if not query:  # Ограничиваем длину запроса
        return jsonify({'institutions': []})
    results = EducationalInstitution.query.filter(EducationalInstitution.name.ilike('%' + query + '%')).limit(50).all()
    institutions = [{'id': inst.id, 'name': inst.name, 'address': inst.address} for inst in results]
    return jsonify({'institutions': institutions})

# Маршруты для реферальной системы
@app.route('/referral')
@login_required
def referral_dashboard():
    """Страница реферальной системы"""
    # Получаем или создаем реферальную ссылку
    referral_link = create_referral_link(current_user.id)
    
    # Получаем статистику рефералов
    referrals = Referral.query.filter_by(referrer_id=current_user.id).all()
    
    # Подсчитываем статистику
    total_referrals = len(referrals)
    paid_referrals = len([r for r in referrals if r.bonus_paid])
    pending_referrals = total_referrals - paid_referrals
    
    # Пагинация для списка рефералов
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Количество рефералов на странице
    
    # Получаем рефералов с пагинацией
    referrals_paginated = Referral.query.filter_by(referrer_id=current_user.id)\
        .order_by(Referral.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    
    # Получаем список рефералов с информацией для текущей страницы
    referrals_info = []
    for referral in referrals_paginated.items:
        referred_user = User.query.get(referral.referred_id)
        if referred_user:
            referrals_info.append({
                'username': referred_user.username,
                'student_name': referred_user.student_name,
                'created_at': referral.created_at.strftime('%d.%m.%Y'),
                'tournaments_count': referred_user.tournaments_count,
                'bonus_paid': referral.bonus_paid,
                'bonus_paid_at': referral.bonus_paid_at.strftime('%d.%m.%Y %H:%M') if referral.bonus_paid_at else None
            })
    
    return render_template('referral.html', 
                         referral_link=referral_link,
                         referrals_info=referrals_info,
                         referrals_paginated=referrals_paginated,
                         total_referrals=total_referrals,
                         paid_referrals=paid_referrals,
                         pending_referrals=pending_referrals,
                         bonus_points=REFERRAL_BONUS_POINTS,
                         bonus_tickets=REFERRAL_BONUS_TICKETS)



@app.route('/referral/copy-link', methods=['POST'])
@login_required
def copy_referral_link():
    """Копирует реферальную ссылку в буфер обмена"""
    referral_link = ReferralLink.query.filter_by(user_id=current_user.id, is_active=True).first()
    if not referral_link:
        return jsonify({'success': False, 'error': 'Реферальная ссылка не найдена'})
    
    referral_url = url_for('register', ref=referral_link.referral_code, _external=True)
    return jsonify({
        'success': True,
        'referral_url': referral_url,
        'message': 'Ссылка скопирована в буфер обмена'
    })



if __name__ == '__main__':
    #logging.basicConfig(filename='err.log', level=logging.DEBUG)
    logging.basicConfig(level=logging.DEBUG)

    app.run(host='0.0.0.0', port=8000, debug=DEBAG)