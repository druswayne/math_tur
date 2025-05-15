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

def process_email_queue():
    """Обработка очереди писем"""
    while True:
        if not email_queue.empty():
            app, mail, msg = email_queue.get()
            send_email_async(app, mail, msg)
            email_queue.task_done()
        time.sleep(0.1)  # Небольшая задержка для снижения нагрузки на CPU

def add_to_queue(app, mail, msg):
    """Добавление письма в очередь"""
    email_queue.put((app, mail, msg))

# Запускаем обработчик очереди в отдельном потоке
def start_email_worker():
    worker = threading.Thread(target=process_email_queue, daemon=True)
    worker.start() 