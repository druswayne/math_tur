import threading
from flask_mail import Message, Mail
from flask import current_app
from queue import Queue
import time

# Очередь для хранения писем
email_queue = Queue()


def send_email_async(app, mail, msg, mail_config=None):
    """Отправка письма в отдельном потоке"""
    with app.app_context():
        try:
            if mail_config:
                # Создаем отдельный экземпляр Mail с административными настройками
                admin_mail = Mail()
                admin_mail.init_app(app)
                admin_mail.server = mail_config['MAIL_SERVER']
                admin_mail.port = mail_config['MAIL_PORT']
                admin_mail.use_ssl = mail_config['MAIL_USE_SSL']
                admin_mail.use_tls = mail_config['MAIL_USE_TLS']
                admin_mail.username = mail_config['MAIL_USERNAME']
                admin_mail.password = mail_config['MAIL_PASSWORD']
                admin_mail.send(msg)
            else:
                # Используем стандартную конфигурацию
                mail.send(msg)
        except Exception as e:
            print(f"Ошибка отправки письма: {e}")


def send_bulk_emails_async(app, mail, messages, mail_config=None):
    """Массовая отправка писем в отдельном потоке"""
    with app.app_context():
        try:
            if mail_config:
                # Создаем отдельный экземпляр Mail с административными настройками
                admin_mail = Mail()
                admin_mail.init_app(app)
                admin_mail.server = mail_config['MAIL_SERVER']
                admin_mail.port = mail_config['MAIL_PORT']
                admin_mail.use_ssl = mail_config['MAIL_USE_SSL']
                admin_mail.use_tls = mail_config['MAIL_USE_TLS']
                admin_mail.username = mail_config['MAIL_USERNAME']
                admin_mail.password = mail_config['MAIL_PASSWORD']
                with admin_mail.connect() as conn:
                    for i, msg in enumerate(messages):
                        conn.send(msg)
                        # Добавляем задержку в 2 секунды между письмами (кроме последнего)
                        if i < len(messages) - 1:
                            time.sleep(2)
            else:
                # Используем стандартную конфигурацию
                with mail.connect() as conn:
                    for i, msg in enumerate(messages):
                        conn.send(msg)
                        # Добавляем задержку в 2 секунды между письмами (кроме последнего)
                        if i < len(messages) - 1:
                            time.sleep(2)
        except Exception as e:
            print(f"Ошибка массовой отправки писем: {e}")


def process_email_queue():
    """Обработка очереди писем"""
    while True:
        try:
            if not email_queue.empty():
                item = email_queue.get()

                # Проверяем тип элемента в очереди
                if len(item) == 3:
                    # Одиночное письмо
                    app, mail, msg = item
                    send_email_async(app, mail, msg)
                elif len(item) == 4 and item[0] == 'bulk':
                    # Массовая отправка
                    _, app, mail, messages = item
                    send_bulk_emails_async(app, mail, messages)
                elif len(item) == 4 and item[0] != 'bulk':
                    # Одиночное письмо с дополнительной конфигурацией
                    app, mail, msg, mail_config = item
                    send_email_async(app, mail, msg, mail_config)
                elif len(item) == 5 and item[0] == 'bulk':
                    # Массовая отправка с дополнительной конфигурацией
                    _, app, mail, messages, mail_config = item
                    send_bulk_emails_async(app, mail, messages, mail_config)

                email_queue.task_done()
            else:
                # Если очередь пуста, ждем немного дольше
                time.sleep(5)
        except Exception as e:
            print(f"Ошибка в обработке очереди email: {e}")
            time.sleep(10)  # Ждем дольше при ошибке


def add_to_queue(app, mail, msg, mail_config=None):
    """Добавление письма в очередь"""
    try:
        if mail_config:
            email_queue.put((app, mail, msg, mail_config))
        else:
            email_queue.put((app, mail, msg))
    except Exception as e:
        print(f"Ошибка добавления письма в очередь: {e}")


def add_bulk_to_queue(app, mail, messages, mail_config=None):
    """Добавление массовых писем в очередь"""
    try:
        if mail_config:
            email_queue.put(('bulk', app, mail, messages, mail_config))
        else:
            email_queue.put(('bulk', app, mail, messages))
    except Exception as e:
        print(f"Ошибка добавления массовых писем в очередь: {e}")


# Запускаем обработчик очереди в отдельном потоке
def start_email_worker():
    worker = threading.Thread(target=process_email_queue, daemon=True)
    worker.start() 
