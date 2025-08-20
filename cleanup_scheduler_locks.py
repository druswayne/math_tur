#!/usr/bin/env python3
"""
Скрипт для очистки блокировок планировщика
"""

import os
import sys
from datetime import datetime

def cleanup_file_lock():
    """Очищает файловую блокировку"""
    import platform
    
    if platform.system() == 'Windows':
        lock_file = os.path.join(os.environ.get('TEMP', 'C:\\temp'), 'math_tur_scheduler.lock')
    else:
        lock_file = '/tmp/math_tur_scheduler.lock'
    
    if os.path.exists(lock_file):
        try:
            with open(lock_file, 'r') as f:
                pid = f.read().strip()
            print(f"📁 Найдена файловая блокировка: PID {pid}")
            
            # Проверяем, существует ли процесс
            try:
                os.kill(int(pid), 0)  # Проверяем существование процесса
                print(f"⚠️ Процесс {pid} все еще работает")
                response = input("Удалить блокировку? (y/N): ")
                if response.lower() != 'y':
                    print("❌ Отменено")
                    return False
            except OSError:
                print(f"✅ Процесс {pid} не существует, можно безопасно удалить")
            
            os.remove(lock_file)
            print("✅ Файловая блокировка удалена")
            return True
        except Exception as e:
            print(f"❌ Ошибка при удалении файловой блокировки: {e}")
            return False
    else:
        print("📁 Файловая блокировка не найдена")
        return True

def cleanup_db_locks():
    """Очищает БД блокировки"""
    try:
        from app import db, SchedulerLock
        
        # Получаем все активные блокировки
        locks = SchedulerLock.query.filter_by(is_active=True).all()
        
        if not locks:
            print("🗄️ Активные БД блокировки не найдены")
            return True
        
        print(f"🗄️ Найдено {len(locks)} активных БД блокировок:")
        for lock in locks:
            print(f"   - {lock.lock_name}: PID {lock.worker_pid}, истекает {lock.expires_at}")
        
        # Очищаем истекшие блокировки
        expired_locks = SchedulerLock.query.filter(
            SchedulerLock.expires_at < datetime.now()
        ).all()
        
        if expired_locks:
            print(f"🗄️ Удаляем {len(expired_locks)} истекших блокировок...")
            for lock in expired_locks:
                db.session.delete(lock)
            db.session.commit()
            print("✅ Истекшие блокировки удалены")
        
        # Спрашиваем про активные блокировки
        active_locks = SchedulerLock.query.filter_by(is_active=True).all()
        if active_locks:
            response = input("Удалить все активные блокировки? (y/N): ")
            if response.lower() == 'y':
                for lock in active_locks:
                    db.session.delete(lock)
                db.session.commit()
                print("✅ Все активные блокировки удалены")
            else:
                print("❌ Активные блокировки оставлены")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при очистке БД блокировок: {e}")
        return False

def show_lock_status():
    """Показывает статус блокировок"""
    print("🔍 Статус блокировок:")
    print("-" * 40)
    
    # Файловая блокировка
    import platform
    if platform.system() == 'Windows':
        lock_file = os.path.join(os.environ.get('TEMP', 'C:\\temp'), 'math_tur_scheduler.lock')
    else:
        lock_file = '/tmp/math_tur_scheduler.lock'
    if os.path.exists(lock_file):
        try:
            with open(lock_file, 'r') as f:
                pid = f.read().strip()
            print(f"📁 Файловая блокировка: PID {pid}")
        except:
            print("📁 Файловая блокировка: ошибка чтения")
    else:
        print("📁 Файловая блокировка: не найдена")
    
    # БД блокировки
    try:
        from app import db, SchedulerLock
        locks = SchedulerLock.query.filter_by(is_active=True).all()
        if locks:
            print(f"🗄️ БД блокировки: {len(locks)} активных")
            for lock in locks:
                print(f"   - {lock.lock_name}: PID {lock.worker_pid}, истекает {lock.expires_at}")
        else:
            print("🗄️ БД блокировки: нет активных")
    except Exception as e:
        print(f"🗄️ БД блокировки: ошибка - {e}")
    
    print()

def main():
    """Основная функция"""
    print("🧹 Очистка блокировок планировщика")
    print("=" * 40)
    
    # Показываем текущий статус
    show_lock_status()
    
    # Очищаем файловую блокировку
    print("1. Очистка файловой блокировки...")
    cleanup_file_lock()
    
    # Очищаем БД блокировки
    print("\n2. Очистка БД блокировок...")
    cleanup_db_locks()
    
    # Показываем финальный статус
    print("\n3. Финальный статус:")
    show_lock_status()
    
    print("✅ Очистка завершена!")

if __name__ == '__main__':
    main()
