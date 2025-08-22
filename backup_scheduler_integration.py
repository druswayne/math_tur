#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Интеграция сервиса бекапов с существующим планировщиком APScheduler
Добавляет функцию создания бекапов в основной планировщик приложения
"""

import os
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Загружаем переменные окружения из основного .env файла
load_dotenv()

logger = logging.getLogger(__name__)

def create_database_backup():
    """
    Функция для создания бекапа БД
    Используется в планировщике APScheduler
    """
    try:
        from remote_backup_service import RemoteBackupService
        
        logger.info("🔄 Запуск запланированного создания бекапа БД...")
        
        # Создаем экземпляр сервиса бекапов
        backup_service = RemoteBackupService()
        
        # Создаем бекап
        success = backup_service.create_backup()
        
        if success:
            logger.info("✅ Запланированный бекап создан успешно")
        else:
            logger.error("❌ Ошибка при создании запланированного бекапа")
            
        return success
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при создании бекапа: {e}")
        return False

def add_backup_job_to_scheduler(scheduler, app):
    """
    Добавляет задачу создания бекапа в планировщик
    """
    try:
        from app import add_scheduler_job
        
        # Получаем настройки времени из конфигурации
        backup_hour = int(os.environ.get('BACKUP_TIME_HOUR',))
        backup_minute = int(os.environ.get('BACKUP_TIME_MINUTE',))
        
        # Проверяем, не существует ли уже задача бекапа
        from app import SchedulerJob
        existing_backup_job = SchedulerJob.query.filter_by(
            job_type='database_backup',
            is_active=True
        ).first()
        
        if existing_backup_job:
            logger.info("📅 Задача создания бекапа уже существует в планировщике")
            return True
        
        # Вычисляем время первого запуска (сегодня в указанное время)
        now = datetime.now()
        first_run = now.replace(hour=backup_hour, minute=backup_minute, second=0, microsecond=0)
        
        # Если указанное время уже прошло сегодня, запускаем завтра
        if first_run <= now:
            first_run += timedelta(days=1)
        
        # Добавляем задачу в планировщик
        add_scheduler_job(
            create_database_backup,
            first_run,
            None,  # tournament_id не нужен для бекапов
            'database_backup',
            interval_hours=24  # Повторять каждый день
        )
        
        logger.info(f"📅 Задача создания бекапа добавлена в планировщик. Первый запуск: {first_run}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при добавлении задачи бекапа в планировщик: {e}")
        return False

def remove_backup_job_from_scheduler():
    """
    Удаляет задачу создания бекапа из планировщика
    """
    try:
        from app import SchedulerJob, db
        
        # Находим и деактивируем задачу бекапа
        backup_jobs = SchedulerJob.query.filter_by(
            job_type='database_backup',
            is_active=True
        ).all()
        
        for job in backup_jobs:
            job.is_active = False
            logger.info(f"🗑️ Задача бекапа {job.job_id} деактивирована")
        
        db.session.commit()
        logger.info(f"📅 Удалено {len(backup_jobs)} задач создания бекапа")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении задач бекапа: {e}")
        return False

def test_backup_service():
    """
    Тестирует сервис бекапов
    """
    try:
        from remote_backup_service import RemoteBackupService
        
        logger.info("🧪 Тестирование сервиса бекапов...")
        
        backup_service = RemoteBackupService()
        
        # Тестируем создание бекапа
        success = backup_service.create_backup()
        
        if success:
            logger.info("✅ Тест сервиса бекапов прошел успешно")
        else:
            logger.error("❌ Тест сервиса бекапов не прошел")
            
        return success
        
    except Exception as e:
        logger.error(f"❌ Ошибка при тестировании сервиса бекапов: {e}")
        return False

def get_backup_status():
    """
    Возвращает статус последних бекапов
    """
    try:
        from pathlib import Path
        from datetime import datetime
        
        backup_dir = Path("backups")
        if not backup_dir.exists():
            return {"status": "no_backups", "message": "Папка бекапов не найдена"}
        
        # Получаем список файлов бекапов
        backup_files = list(backup_dir.glob("backup_*.zip"))
        
        if not backup_files:
            return {"status": "no_backups", "message": "Бекапы не найдены"}
        
        # Сортируем по времени создания (новые первыми)
        backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        # Получаем информацию о последних бекапах
        recent_backups = []
        for backup_file in backup_files[:5]:  # Последние 5 бекапов
            stat = backup_file.stat()
            backup_info = {
                "filename": backup_file.name,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created_at": datetime.fromtimestamp(stat.st_mtime).strftime('%d.%m.%Y %H:%M:%S'),
                "age_hours": round((datetime.now().timestamp() - stat.st_mtime) / 3600, 1)
            }
            recent_backups.append(backup_info)
        
        return {
            "status": "success",
            "total_backups": len(backup_files),
            "recent_backups": recent_backups,
            "backup_dir": str(backup_dir.absolute())
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка при получении статуса бекапов: {e}")
        return {"status": "error", "message": str(e)}

def main():
    """
    Точка входа для тестирования и управления бекапами
    """
    import sys
    
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python backup_scheduler_integration.py test     - Тестировать сервис бекапов")
        print("  python backup_scheduler_integration.py status   - Показать статус бекапов")
        print("  python backup_scheduler_integration.py create   - Создать бекап сейчас")
        print("  python backup_scheduler_integration.py add      - Добавить задачу в планировщик")
        print("  python backup_scheduler_integration.py remove   - Удалить задачу из планировщика")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "test":
        success = test_backup_service()
        sys.exit(0 if success else 1)
        
    elif command == "status":
        status = get_backup_status()
        print(f"Статус бекапов: {status}")
        sys.exit(0)
        
    elif command == "create":
        success = create_database_backup()
        sys.exit(0 if success else 1)
        
    elif command == "add":
        # Для добавления в планировщик нужно запускать из контекста Flask приложения
        print("Для добавления задачи в планировщик используйте функцию add_backup_job_to_scheduler()")
        sys.exit(0)
        
    elif command == "remove":
        success = remove_backup_job_from_scheduler()
        sys.exit(0 if success else 1)
        
    else:
        print(f"Неизвестная команда: {command}")
        sys.exit(1)

if __name__ == "__main__":
    main()
