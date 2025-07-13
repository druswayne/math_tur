import threading
from flask_mail import Message
from flask import current_app
from queue import Queue
import time

# Очередь для хранения писем
email_queue = Queue()


def send_email_async(app, mail, msg):
    """Отправка письма в отдельном потоке"""
    with app.app_context():
        try:
            mail.send(msg)
        except Exception as e:
            print(f"Ошибка отправки письма: {e}")


def send_bulk_emails_async(app, mail, messages):
    """Массовая отправка писем в отдельном потоке"""
    with app.app_context():
        try:
            with mail.connect() as conn:
                for msg in messages:
                    conn.send(msg)
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

                email_queue.task_done()
            else:
                # Если очередь пуста, ждем немного дольше
                time.sleep(5)
        except Exception as e:
            print(f"Ошибка в обработке очереди email: {e}")
            time.sleep(10)  # Ждем дольше при ошибке


def add_to_queue(app, mail, msg):
    """Добавление письма в очередь"""
    try:
        email_queue.put((app, mail, msg))
    except Exception as e:
        print(f"Ошибка добавления письма в очередь: {e}")


def add_bulk_to_queue(app, mail, messages):
    """Добавление массовых писем в очередь"""
    try:
        email_queue.put(('bulk', app, mail, messages))
    except Exception as e:
        print(f"Ошибка добавления массовых писем в очередь: {e}")


# Запускаем обработчик очереди в отдельном потоке
def start_email_worker():
    worker = threading.Thread(target=process_email_queue, daemon=True)
    worker.start() 
