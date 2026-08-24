#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
python restore_database.py restore backup_school_tournaments_20250828_002103.zip
Скрипт для восстановления базы данных из бекапа
Использует SSH подключение к серверу для восстановления через psql
"""

import os
import sys
import zipfile
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DatabaseRestoreService:
    def __init__(self):
        """Инициализация сервиса восстановления"""
        self.backup_dir = Path("backups")
        
        # Настройки подключения к серверу БД
        self.db_host = "193.47.42.117"
        self.db_port = "5431"
        self.db_name = "school_tournaments"
        self.db_user = "admin"
        self.db_password = "S3cureP@ssw0rd!"
        
        # Настройки SSH
        self.ssh_host = os.environ.get('SSH_HOST', self.db_host)
        self.ssh_user = os.environ.get('SSH_USER', 'root')
        self.ssh_password = os.environ.get('SSH_PASSWORD')
        self.ssh_key_path = os.environ.get('SSH_KEY_PATH')
    
    def list_available_backups(self):
        """Показывает список доступных бекапов"""
        if not self.backup_dir.exists():
            logger.error("❌ Папка backups не найдена")
            return []
        
        backup_files = list(self.backup_dir.glob("backup_*.zip"))
        backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        if not backup_files:
            logger.info("📭 Бекапы не найдены")
            return []
        
        logger.info(f"📋 Найдено {len(backup_files)} бекапов:")
        for i, backup_file in enumerate(backup_files[:10], 1):  # Показываем последние 10
            stat = backup_file.stat()
            size_mb = stat.st_size / (1024 * 1024)
            created_at = datetime.fromtimestamp(stat.st_mtime).strftime('%d.%m.%Y %H:%M:%S')
            logger.info(f"  {i}. {backup_file.name} ({size_mb:.2f} MB) - {created_at}")
        
        return backup_files
    
    def extract_backup(self, backup_path):
        """Извлекает SQL файл из ZIP архива"""
        try:
            with zipfile.ZipFile(backup_path, 'r') as zipf:
                # Ищем SQL файл в архиве
                sql_files = [f for f in zipf.namelist() if f.endswith('.sql')]
                if not sql_files:
                    logger.error("❌ SQL файл не найден в архиве")
                    return None
                
                sql_filename = sql_files[0]
                extracted_path = self.backup_dir / f"temp_{sql_filename}"
                
                # Извлекаем файл
                with zipf.open(sql_filename) as source, open(extracted_path, 'wb') as target:
                    target.write(source.read())
                
                logger.info(f"✅ Извлечен SQL файл: {extracted_path}")
                return extracted_path
                
        except Exception as e:
            logger.error(f"❌ Ошибка при извлечении бекапа: {e}")
            return None
    
    def restore_database_via_ssh(self, sql_file_path):
        """Восстанавливает базу данных через SSH"""
        try:
            import paramiko
            
            logger.info("🔗 Подключение к серверу через SSH...")
            
            # Создаем SSH клиент
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Подключаемся к серверу
            if self.ssh_key_path and os.path.exists(self.ssh_key_path):
                ssh.connect(
                    self.ssh_host,
                    username=self.ssh_user,
                    key_filename=self.ssh_key_path
                )
            else:
                ssh.connect(
                    self.ssh_host,
                    username=self.ssh_user,
                    password=self.ssh_password
                )
            
            # Загружаем SQL файл на сервер
            remote_sql_path = f"/tmp/restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
            logger.info(f"📤 Загрузка SQL файла на сервер: {remote_sql_path}")
            
            sftp = ssh.open_sftp()
            sftp.put(str(sql_file_path), remote_sql_path)
            sftp.close()
            
            # Команда для восстановления БД
            restore_command = f"""
                export PGPASSWORD='{self.db_password}'
                psql -h {self.db_host} -p {self.db_port} -U {self.db_user} -d {self.db_name} -f {remote_sql_path}
            """
            
            logger.warning("⚠️ ВНИМАНИЕ: Начинается восстановление базы данных!")
            logger.warning("⚠️ Это может занять несколько минут и перезаписать существующие данные!")
            
            # Запрашиваем подтверждение
            confirm = input("Продолжить восстановление? (yes/no): ").lower().strip()
            if confirm != 'yes':
                logger.info("❌ Восстановление отменено пользователем")
                # Удаляем временный файл с сервера
                ssh.exec_command(f"rm -f {remote_sql_path}")
                ssh.close()
                return False
            
            logger.info("🔄 Начинаем восстановление базы данных...")
            stdin, stdout, stderr = ssh.exec_command(restore_command)
            
            # Ждем завершения команды
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status != 0:
                error_output = stderr.read().decode('utf-8')
                logger.error(f"❌ Ошибка восстановления БД: {error_output}")
                return False
            
            # Читаем вывод команды
            output = stdout.read().decode('utf-8')
            logger.info("✅ Восстановление завершено успешно!")
            logger.info(f"📊 Вывод команды: {output}")
            
            # Удаляем временный файл с сервера
            ssh.exec_command(f"rm -f {remote_sql_path}")
            ssh.close()
            
            return True
            
        except ImportError:
            logger.error("❌ Модуль paramiko не установлен. Установите: pip install paramiko")
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка при восстановлении через SSH: {e}")
            return False
    
    def cleanup_temp_files(self, temp_file_path):
        """Удаляет временные файлы"""
        try:
            if temp_file_path and temp_file_path.exists():
                temp_file_path.unlink()
                logger.info(f"🧹 Удален временный файл: {temp_file_path}")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось удалить временный файл: {e}")
    
    def restore_from_backup(self, backup_filename=None):
        """Основной метод восстановления из бекапа"""
        try:
            # Если файл не указан, показываем список доступных
            if not backup_filename:
                backup_files = self.list_available_backups()
                if not backup_files:
                    return False
                
                # Запрашиваем выбор бекапа
                try:
                    choice = int(input(f"Выберите номер бекапа (1-{min(len(backup_files), 10)}): ")) - 1
                    if 0 <= choice < len(backup_files):
                        backup_path = backup_files[choice]
                    else:
                        logger.error("❌ Неверный номер бекапа")
                        return False
                except ValueError:
                    logger.error("❌ Введите корректный номер")
                    return False
            else:
                backup_path = self.backup_dir / backup_filename
                if not backup_path.exists():
                    logger.error(f"❌ Файл бекапа не найден: {backup_path}")
                    return False
            
            logger.info(f"🔄 Восстановление из бекапа: {backup_path.name}")
            
            # Извлекаем SQL файл
            sql_file_path = self.extract_backup(backup_path)
            if not sql_file_path:
                return False
            
            try:
                # Восстанавливаем БД
                success = self.restore_database_via_ssh(sql_file_path)
                return success
            finally:
                # Очищаем временные файлы
                self.cleanup_temp_files(sql_file_path)
                
        except Exception as e:
            logger.error(f"❌ Ошибка при восстановлении: {e}")
            return False

def main():
    """Точка входа"""
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python restore_database.py list                    - Показать список бекапов")
        print("  python restore_database.py restore                 - Восстановить из выбранного бекапа")
        print("  python restore_database.py restore <filename>      - Восстановить из указанного файла")
        print("  python restore_database.py help                    - Показать эту справку")
        sys.exit(1)
    
    command = sys.argv[1]
    restore_service = DatabaseRestoreService()
    
    if command == "list":
        restore_service.list_available_backups()
        sys.exit(0)
        
    elif command == "restore":
        backup_filename = sys.argv[2] if len(sys.argv) > 2 else None
        success = restore_service.restore_from_backup(backup_filename)
        sys.exit(0 if success else 1)
        
    elif command == "help":
        print("Скрипт восстановления базы данных из бекапа")
        print("\nКоманды:")
        print("  list     - Показать список доступных бекапов")
        print("  restore  - Восстановить базу данных из бекапа")
        print("  help     - Показать эту справку")
        print("\nПримеры:")
        print("  python restore_database.py list")
        print("  python restore_database.py restore")
        print("  python restore_database.py restore backup_school_tournaments_20241201_020000.zip")
        sys.exit(0)
        
    else:
        print(f"Неизвестная команда: {command}")
        print("Используйте 'python restore_database.py help' для справки")
        sys.exit(1)

if __name__ == "__main__":
    main()
