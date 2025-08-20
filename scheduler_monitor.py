#!/usr/bin/env python3
"""
Мониторинг планировщика - показывает состояние планировщика в реальном времени
"""

import os
import time
import psutil
from datetime import datetime

def check_scheduler_status():
    """Проверяет статус планировщика"""
    print(f"🕐 {datetime.now().strftime('%H:%M:%S')} - Проверка планировщика...")
    
    # Проверяем файловую блокировку
    lock_file = '/tmp/math_tur_scheduler.lock'
    if os.path.exists(lock_file):
        try:
            with open(lock_file, 'r') as f:
                pid = int(f.read().strip())
            
            # Проверяем, жив ли процесс
            if psutil.pid_exists(pid):
                process = psutil.Process(pid)
                print(f"✅ Планировщик активен: PID {pid}, CPU: {process.cpu_percent():.1f}%")
                return True
            else:
                print(f"❌ Планировщик НЕ активен: PID {pid} не существует")
                return False
        except Exception as e:
            print(f"❌ Ошибка чтения блокировки: {e}")
            return False
    else:
        print("❌ Файл блокировки не найден")
        return False

def check_gunicorn_workers():
    """Проверяет воркеры Gunicorn"""
    workers = []
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if 'gunicorn' in proc.info['name'] and 'worker' in ' '.join(proc.info['cmdline']):
                workers.append({
                    'pid': proc.info['pid'],
                    'cpu': proc.cpu_percent(),
                    'memory': proc.memory_percent()
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    print(f"👷 Найдено {len(workers)} воркеров Gunicorn:")
    for worker in workers:
        print(f"   PID {worker['pid']}: CPU {worker['cpu']:.1f}%, Memory {worker['memory']:.1f}%")
    
    return workers

def check_db_locks():
    """Проверяет БД блокировки"""
    try:
        from app import db, SchedulerLock
        locks = SchedulerLock.query.filter_by(is_active=True).all()
        
        if locks:
            print(f"🗄️ БД блокировки: {len(locks)} активных")
            for lock in locks:
                # Проверяем, жив ли процесс
                if psutil.pid_exists(lock.worker_pid):
                    status = "✅ активен"
                else:
                    status = "❌ процесс мертв"
                print(f"   {lock.lock_name}: PID {lock.worker_pid} ({status}), истекает {lock.expires_at}")
        else:
            print("🗄️ БД блокировки: нет активных")
            
    except Exception as e:
        print(f"🗄️ Ошибка проверки БД блокировок: {e}")

def monitor_scheduler():
    """Основной цикл мониторинга"""
    print("🚀 Запуск мониторинга планировщика")
    print("Нажмите Ctrl+C для выхода")
    print("=" * 60)
    
    try:
        while True:
            # Очищаем экран (для Unix/Linux)
            if os.name != 'nt':
                os.system('clear')
            
            print("📊 МОНИТОРИНГ ПЛАНИРОВЩИКА")
            print("=" * 60)
            
            # Проверяем статус планировщика
            scheduler_active = check_scheduler_status()
            print()
            
            # Проверяем воркеры
            workers = check_gunicorn_workers()
            print()
            
            # Проверяем БД блокировки
            use_db_lock = os.environ.get('USE_DB_LOCK', 'false').lower() == 'true'
            if use_db_lock:
                check_db_locks()
                print()
            
            # Выводим общий статус
            if scheduler_active:
                print("🟢 Общий статус: Планировщик работает нормально")
            else:
                print("🔴 Общий статус: Планировщик НЕ активен!")
                print("   Рекомендация: перезапустите приложение")
            
            print("=" * 60)
            print(f"Следующая проверка через 10 секунд...")
            
            time.sleep(10)
            
    except KeyboardInterrupt:
        print("\n👋 Мониторинг остановлен")

if __name__ == '__main__':
    monitor_scheduler()
