#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис для создания удаленных бекапов PostgreSQL
Использует SSH подключение к серверу БД для выполнения pg_dump
"""

import os
import sys
import time
import zipfile
import logging
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
from dotenv import load_dotenv

# Загружаем переменные окружения из основного .env файла
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('backup_service.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class RemoteBackupService:
    def __init__(self):
        """Инициализация сервиса бекапов"""
        self.backup_dir = Path("backups")
        self.backup_dir.mkdir(exist_ok=True)
        
        # Настройки подключения к серверу БД
        self.db_host = "193.47.42.117"
        self.db_port = "5432"
        self.db_name = "school_tournaments"
        self.db_user = "admin"
        self.db_password = "S3cureP@ssw0rd!"
        
        # Настройки SSH (если используется)
        self.ssh_host = os.environ.get('SSH_HOST', self.db_host)
        self.ssh_user = os.environ.get('SSH_USER', 'root')
        self.ssh_password = os.environ.get('SSH_PASSWORD')
        self.ssh_key_path = os.environ.get('SSH_KEY_PATH')
        
        # Настройки email
        self.email_enabled = os.environ.get('BACKUP_EMAIL_ENABLED', 'true').lower() == 'true'
        self.email_recipients = os.environ.get('BACKUP_EMAIL_RECIPIENTS', '').split(',')
        
        # Настройки ротации
        self.keep_days = int(os.environ.get('BACKUP_KEEP_DAYS', '7'))
        self.max_backup_size_mb = int(os.environ.get('BACKUP_MAX_SIZE_MB', '100'))
        
    def create_backup_filename(self):
        """Создает имя файла для бекапа"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"backup_school_tournaments_{timestamp}.sql"
    
    def create_backup_using_ssh(self):
        """Создает бекап через SSH подключение"""
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
            
            # Создаем имя файла для бекапа
            backup_filename = self.create_backup_filename()
            remote_backup_path = f"/tmp/{backup_filename}"
            
            # Команда для создания бекапа на сервере
            pg_dump_command = f"""
                export PGPASSWORD='{self.db_password}'
                pg_dump -h {self.db_host} -p {self.db_port} -U {self.db_user} -d {self.db_name} \
                    --verbose --no-password --clean --if-exists --create > {remote_backup_path}
            """
            
            logger.info("📦 Создание бекапа на сервере...")
            stdin, stdout, stderr = ssh.exec_command(pg_dump_command)
            
            # Ждем завершения команды
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status != 0:
                error_output = stderr.read().decode('utf-8')
                logger.error(f"❌ Ошибка создания бекапа: {error_output}")
                return None
            
            # Проверяем размер файла
            stdin, stdout, stderr = ssh.exec_command(f"ls -lh {remote_backup_path}")
            file_info = stdout.read().decode('utf-8').strip()
            logger.info(f"📊 Информация о файле: {file_info}")
            
            # Скачиваем файл с сервера
            local_backup_path = self.backup_dir / backup_filename
            logger.info(f"⬇️ Скачивание бекапа: {local_backup_path}")
            
            sftp = ssh.open_sftp()
            sftp.get(remote_backup_path, str(local_backup_path))
            sftp.close()
            
            # Удаляем временный файл с сервера
            ssh.exec_command(f"rm -f {remote_backup_path}")
            
            ssh.close()
            
            # Проверяем размер скачанного файла
            file_size_mb = local_backup_path.stat().st_size / (1024 * 1024)
            logger.info(f"✅ Бекап создан: {local_backup_path} ({file_size_mb:.2f} MB)")
            
            return local_backup_path
            
        except ImportError:
            logger.error("❌ Модуль paramiko не установлен. Установите: pip install paramiko")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при создании бекапа через SSH: {e}")
            return None
    
    def create_backup_using_psql(self):
        """Создает бекап используя psql (если установлен локально)"""
        try:
            backup_filename = self.create_backup_filename()
            local_backup_path = self.backup_dir / backup_filename
            
            # Команда для создания бекапа
            cmd = [
                'pg_dump',
                '-h', self.db_host,
                '-p', self.db_port,
                '-U', self.db_user,
                '-d', self.db_name,
                '--verbose',
                '--clean',
                '--if-exists',
                '--create'
            ]
            
            # Устанавливаем пароль как переменную окружения
            env = os.environ.copy()
            env['PGPASSWORD'] = self.db_password
            
            logger.info("📦 Создание бекапа через pg_dump...")
            
            with open(local_backup_path, 'w', encoding='utf-8') as f:
                result = subprocess.run(
                    cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    env=env,
                    text=True
                )
            
            if result.returncode != 0:
                logger.error(f"❌ Ошибка создания бекапа: {result.stderr}")
                return None
            
            # Проверяем размер файла
            file_size_mb = local_backup_path.stat().st_size / (1024 * 1024)
            logger.info(f"✅ Бекап создан: {local_backup_path} ({file_size_mb:.2f} MB)")
            
            return local_backup_path
            
        except FileNotFoundError:
            logger.error("❌ pg_dump не найден. Установите PostgreSQL клиент.")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при создании бекапа: {e}")
            return None
    
    def compress_backup(self, backup_path):
        """Сжимает бекап в ZIP архив"""
        try:
            zip_path = backup_path.with_suffix('.zip')
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(backup_path, backup_path.name)
            
            # Удаляем исходный файл
            backup_path.unlink()
            
            # Проверяем размер сжатого файла
            compressed_size_mb = zip_path.stat().st_size / (1024 * 1024)
            logger.info(f"🗜️ Бекап сжат: {zip_path} ({compressed_size_mb:.2f} MB)")
            
            return zip_path
            
        except Exception as e:
            logger.error(f"❌ Ошибка при сжатии бекапа: {e}")
            return backup_path
    
    def send_backup_email(self, backup_path):
        """Отправляет бекап на email"""
        if not self.email_enabled or not self.email_recipients:
            logger.info("📧 Отправка email отключена")
            return True
        
        try:
            from flask import Flask
            from flask_mail import Mail, Message
            
            # Создаем временное Flask приложение для отправки email
            app = Flask(__name__)
            app.config['MAIL_SERVER'] = 'mail.liga-znatokov.by'
            app.config['MAIL_PORT'] = 465
            app.config['MAIL_USE_SSL'] = True
            app.config['MAIL_USE_TLS'] = False
            app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
            app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
            
            mail = Mail(app)
            
            with app.app_context():
                # Создаем сообщение
                subject = f"Резервная копия БД - {datetime.now().strftime('%d.%m.%Y %H:%M')}"
                body = f"""
                Автоматическая резервная копия базы данных school_tournaments.
                
                Дата создания: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
                Размер файла: {backup_path.stat().st_size / (1024 * 1024):.2f} MB
                
                Файл прикреплен к письму.
                """
                
                msg = Message(
                    subject=subject,
                    sender=app.config['MAIL_USERNAME'],
                    recipients=self.email_recipients,
                    body=body
                )
                
                # Прикрепляем файл
                with open(backup_path, 'rb') as f:
                    msg.attach(
                        filename=backup_path.name,
                        content_type='application/zip',
                        data=f.read()
                    )
                
                # Отправляем email
                mail.send(msg)
                
            logger.info(f"📧 Бекап отправлен на {', '.join(self.email_recipients)}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке email: {e}")
            return False
    
    def cleanup_old_backups(self):
        """Удаляет старые бекапы"""
        try:
            cutoff_date = datetime.now() - timedelta(days=self.keep_days)
            deleted_count = 0
            
            for backup_file in self.backup_dir.glob("backup_*.zip"):
                if backup_file.stat().st_mtime < cutoff_date.timestamp():
                    backup_file.unlink()
                    deleted_count += 1
                    logger.info(f"🗑️ Удален старый бекап: {backup_file.name}")
            
            if deleted_count > 0:
                logger.info(f"🧹 Удалено {deleted_count} старых бекапов")
            else:
                logger.info("🧹 Старые бекапы не найдены")
                
        except Exception as e:
            logger.error(f"❌ Ошибка при очистке старых бекапов: {e}")
    
    def validate_backup(self, backup_path):
        """Проверяет целостность бекапа"""
        try:
            # Проверяем, что файл не пустой
            if backup_path.stat().st_size == 0:
                logger.error("❌ Бекап пустой")
                return False
            
            # Проверяем размер файла
            file_size_mb = backup_path.stat().st_size / (1024 * 1024)
            if file_size_mb > self.max_backup_size_mb:
                logger.warning(f"⚠️ Бекап слишком большой: {file_size_mb:.2f} MB")
            
            # Проверяем, что это валидный SQL файл (если не сжат)
            if backup_path.suffix == '.sql':
                with open(backup_path, 'r', encoding='utf-8') as f:
                    first_line = f.readline().strip()
                    if not first_line.startswith('--'):
                        logger.warning("⚠️ Файл может быть не валидным SQL дампом")
            
            logger.info("✅ Бекап прошел валидацию")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка при валидации бекапа: {e}")
            return False
    
    def create_backup(self):
        """Основной метод создания бекапа"""
        logger.info("🚀 Начинаем создание резервной копии БД...")
        
        # Пытаемся создать бекап через SSH
        backup_path = self.create_backup_using_ssh()
        
        # Если SSH не сработал, пробуем через pg_dump
        if not backup_path:
            logger.info("🔄 Пробуем создать бекап через pg_dump...")
            backup_path = self.create_backup_using_psql()
        
        if not backup_path:
            logger.error("❌ Не удалось создать бекап")
            return False
        
        # Валидируем бекап
        if not self.validate_backup(backup_path):
            backup_path.unlink()
            return False
        
        # Сжимаем бекап
        compressed_backup = self.compress_backup(backup_path)
        
        # Отправляем на email
        email_sent = self.send_backup_email(compressed_backup)
        
        # Очищаем старые бекапы
        self.cleanup_old_backups()
        
        logger.info("🎉 Создание резервной копии завершено успешно!")
        return True

def main():
    """Точка входа для запуска из командной строки"""
    service = RemoteBackupService()
    success = service.create_backup()
    
    if success:
        print("✅ Резервная копия создана успешно")
        sys.exit(0)
    else:
        print("❌ Ошибка при создании резервной копии")
        sys.exit(1)

if __name__ == "__main__":
    main()
