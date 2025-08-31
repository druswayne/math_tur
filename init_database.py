#!/usr/bin/env python3
"""
Скрипт для инициализации базы данных
Создает все таблицы и базовые данные для проекта школьных турниров
"""

import os
import sys
from datetime import datetime

# Добавляем текущую директорию в путь для импорта
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db, create_admin_user, cleanup_all_sessions, restore_scheduler_jobs, initialize_scheduler_jobs, check_expired_payments

def init_database():
    """Инициализация базы данных"""
    print("🚀 Начинаю инициализацию базы данных...")
    
    with app.app_context():
        try:
            # 1. Создание всех таблиц
            print("📋 Создание таблиц базы данных...")
            db.create_all()
            print("✅ Таблицы созданы успешно")
            
            # 2. Создание администратора
            print("👤 Создание администратора...")
            create_admin_user()
            print("✅ Администратор создан")
            
            # 3. Очистка сессий
            print("🧹 Очистка сессий...")
            cleanup_all_sessions()
            print("✅ Сессии очищены")
            
            # 4. Восстановление задач планировщика
            print("⏰ Восстановление задач планировщика...")
            restore_scheduler_jobs()
            print("✅ Задачи планировщика восстановлены")
            
            # 5. Инициализация задач планировщика
            print("🔧 Инициализация задач планировщика...")
            initialize_scheduler_jobs()
            print("✅ Задачи планировщика инициализированы")
            
            # 6. Проверка истекших платежей
            print("💳 Проверка истекших платежей...")
            check_expired_payments()
            print("✅ Проверка платежей завершена")
            
            print("\n🎉 База данных успешно инициализирована!")
            print("\n📋 Информация для входа:")
            print("   Логин: admin")
            print("   Пароль: admin123")
            print("   Email: admin@school-tournaments.ru")
            
        except Exception as e:
            print(f"❌ Ошибка при инициализации базы данных: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    return True

def check_database_connection():
    """Проверка подключения к базе данных"""
    print("🔍 Проверка подключения к базе данных...")
    
    try:
        with app.app_context():
            # Проверяем подключение
            db.engine.execute("SELECT 1")
            print("✅ Подключение к базе данных успешно")
            return True
    except Exception as e:
        print(f"❌ Ошибка подключения к базе данных: {e}")
        print("\n🔧 Убедитесь, что:")
        print("   1. PostgreSQL запущен")
        print("   2. База данных создана")
        print("   3. Переменная SQLALCHEMY_DATABASE_URI настроена правильно")
        print("   4. Пользователь имеет права доступа к базе данных")
        return False

def show_database_info():
    """Показывает информацию о базе данных"""
    print("\n📊 Информация о базе данных:")
    
    try:
        with app.app_context():
            # Получаем список таблиц
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            
            print(f"   Количество таблиц: {len(tables)}")
            print("   Список таблиц:")
            for table in sorted(tables):
                print(f"     - {table}")
                
    except Exception as e:
        print(f"❌ Ошибка при получении информации о базе данных: {e}")

if __name__ == "__main__":
    print("=" * 60)
    print("🐘 Инициализация базы данных PostgreSQL")
    print("=" * 60)
    
    # Проверяем подключение
    if not check_database_connection():
        sys.exit(1)
    
    # Инициализируем базу данных
    if init_database():
        show_database_info()
        print("\n✅ Инициализация завершена успешно!")
        print("🚀 Теперь можно запускать приложение: python app.py")
    else:
        print("\n❌ Инициализация завершена с ошибками!")
        sys.exit(1) 