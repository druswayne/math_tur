import boto3
from botocore.config import Config
from werkzeug.utils import secure_filename
import os
from datetime import datetime
import secrets

# Конфигурация S3
S3_CONFIG = {
    'endpoint_url': 'https://s3.twcstorage.ru',
    'aws_access_key_id': '3PC256ZI3DL5QZDFHUOH',
    'aws_secret_access_key': 'P3aJ4D6GxALUx4o3c3QylSBD9DytCnsGe5o1tIDR',
    'region_name': 'ru-1',
    'bucket_name': '5e984fdc-c435406b-ee7b-4296-aaed-0ceae9456f42'
}

# Создаем клиент S3
s3_client = boto3.client(
    's3',
    endpoint_url=S3_CONFIG['endpoint_url'],
    aws_access_key_id=S3_CONFIG['aws_access_key_id'],
    aws_secret_access_key=S3_CONFIG['aws_secret_access_key'],
    region_name=S3_CONFIG['region_name'],
    config=Config(
        signature_version='s3v4',
        s3={'addressing_style': 'path'}
    )
)

def generate_unique_filename(filename):
    """Генерирует уникальное имя файла, сохраняя расширение"""
    ext = os.path.splitext(filename)[1]
    unique_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(8)}{ext}"
    return unique_name

def upload_file_to_s3(file, folder):
    """
    Загружает файл в S3
    :param file: FileStorage объект
    :param folder: папка в S3 (например, 'prizes', 'tasks', 'tournaments')
    :return: имя файла в S3 или None в случае ошибки
    """
    try:
        if file and file.filename:
            filename = secure_filename(file.filename)
            unique_filename = generate_unique_filename(filename)
            s3_key = f"{folder}/{unique_filename}"
            
            # Определяем Content-Type в зависимости от расширения файла
            extra_args = {'ACL': 'public-read'}
            
            # Для PDF файлов устанавливаем правильный Content-Type
            if filename.lower().endswith('.pdf'):
                extra_args['ContentType'] = 'application/pdf'
                extra_args['ContentDisposition'] = 'inline'  # Открывать в браузере, а не скачивать
            elif filename.lower().endswith(('.jpg', '.jpeg')):
                extra_args['ContentType'] = 'image/jpeg'
            elif filename.lower().endswith('.png'):
                extra_args['ContentType'] = 'image/png'
            elif filename.lower().endswith('.gif'):
                extra_args['ContentType'] = 'image/gif'
            elif filename.lower().endswith('.webp'):
                extra_args['ContentType'] = 'image/webp'
            
            # Загружаем файл в S3
            s3_client.upload_fileobj(
                file,
                S3_CONFIG['bucket_name'],
                s3_key,
                ExtraArgs=extra_args
            )
            
            return unique_filename
    except Exception as e:
        print(f"Ошибка при загрузке файла в S3: {str(e)}")
        return None

def delete_file_from_s3(filename, folder):
    """
    Удаляет файл из S3
    :param filename: имя файла
    :param folder: папка в S3
    :return: True если успешно, False в случае ошибки
    """
    try:
        if filename:
            s3_key = f"{folder}/{filename}"
            s3_client.delete_object(
                Bucket=S3_CONFIG['bucket_name'],
                Key=s3_key
            )
            return True
    except Exception as e:
        print(f"Ошибка при удалении файла из S3: {str(e)}")
        return False

def get_s3_url(filename, folder):
    """
    Возвращает публичный URL файла в S3
    :param filename: имя файла
    :param folder: папка в S3
    :return: URL файла
    """
    if filename:
        return f"{S3_CONFIG['endpoint_url']}/{S3_CONFIG['bucket_name']}/{folder}/{filename}"
    return None

def get_file_url(file_path):
    """
    Возвращает публичный URL файла в S3 по полному пути
    :param file_path: полный путь к файлу в S3 (например, 'static/Пользовательское соглашение.pdf')
    :return: URL файла
    """
    if file_path:
        return f"{S3_CONFIG['endpoint_url']}/{S3_CONFIG['bucket_name']}/{file_path}"
    return None 