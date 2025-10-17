#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для генерации сертификатов и дипломов участников турнира
"""

import os
import sys
from PIL import Image, ImageDraw, ImageFont
import psycopg2
from dotenv import load_dotenv
import re
import argparse
from urllib.parse import urlparse

# Загружаем переменные окружения
load_dotenv()

class CertificateGenerator:
    def __init__(self, overwrite=False, quality=40, certificate_quality=15, compression_mode=None):
        """Инициализация генератора сертификатов"""
        # Устанавливаем режим сжатия
        if compression_mode:
            quality, certificate_quality = self.get_compression_settings(compression_mode)
        
        # Парсим URI базы данных из переменной окружения
        database_uri = os.getenv('SQLALCHEMY_DATABASE_URI')
        if database_uri:
            parsed = urlparse(database_uri)
            # Декодируем пароль из URL-кодировки
            password = parsed.password
            if password:
                from urllib.parse import unquote
                password = unquote(password)
            
            self.db_config = {
                'host': parsed.hostname,
                'port': parsed.port or 5432,
                'database': parsed.path[1:],  # убираем первый символ '/'
                'user': parsed.username,
                'password': password
            }
        else:
            # Fallback на отдельные переменные
            self.db_config = {
                'host': os.getenv('DB_HOST', 'localhost'),
                'port': os.getenv('DB_PORT', '5432'),
                'database': os.getenv('DB_NAME', 'math_tur'),
                'user': os.getenv('DB_USER', 'postgres'),
                'password': os.getenv('DB_PASSWORD', '')
            }
        
        self.overwrite = overwrite
        self.quality = quality  # качество для дипломов
        self.certificate_quality = certificate_quality  # качество для сертификатов
        self.compression_mode = compression_mode  # режим сжатия
        
        # Пути к шаблонам
        self.certificate_template = 'doc/sertificat.jpg'
        self.diploma_template = 'doc/diplom.jpg'
        
        # Координаты для сертификата (ФИО)
        self.cert_name_coords = {
            'start': (311, 1520),
            'end': (2167, 1520),
            'max_height': 75
        }
        
        # Координаты для диплома
        self.diploma_coords = {
            'place': {'start': (350, 430), 'end': (450, 430)},
            'name': {'start': (180, 520), 'end': (725, 520)},
            'group': {'start': (470, 556), 'end': (540, 556)},
            'school_line1': {'start': (181, 643), 'end': (730, 643)},
            'school_line2': {'start': (181, 690), 'end': (730, 690)}
        }
        
        self.diploma_font_size = 20

    @staticmethod
    def arabic_to_roman(num):
        """Преобразование арабских цифр в римские"""
        val = [
            1000, 900, 500, 400,
            100, 90, 50, 40,
            10, 9, 5, 4,
            1
        ]
        syms = [
            "M", "CM", "D", "CD",
            "C", "XC", "L", "XL",
            "X", "IX", "V", "IV",
            "I"
        ]
        roman_num = ''
        i = 0
        while num > 0:
            for _ in range(num // val[i]):
                roman_num += syms[i]
                num -= val[i]
            i += 1
        return roman_num
    
    @staticmethod
    def get_compression_settings(mode):
        """Получить настройки сжатия в зависимости от режима"""
        compression_modes = {
            '1': {  # Максимальное сжатие (~100 КБ)
                'diploma_quality': 40,
                'certificate_quality': 15,
                'diploma_scale': 0.8,
                'certificate_scale': 0.7,
                'description': 'Максимальное (файлы ~100 КБ)'
            },
            '2': {  # Среднее сжатие (~200 КБ)
                'diploma_quality': 55,
                'certificate_quality': 35,
                'diploma_scale': 0.85,
                'certificate_scale': 0.8,
                'description': 'Среднее (файлы ~200 КБ)'
            },
            '3': {  # Минимальное сжатие (~500 КБ)
                'diploma_quality': 70,
                'certificate_quality': 55,
                'diploma_scale': 0.95,
                'certificate_scale': 0.9,
                'description': 'Минимальное (файлы ~500 КБ)'
            }
        }
        
        settings = compression_modes.get(mode, compression_modes['1'])
        return settings['diploma_quality'], settings['certificate_quality']
    
    @staticmethod
    def get_compression_scale(mode, is_certificate=True):
        """Получить масштаб изображения в зависимости от режима"""
        compression_modes = {
            '1': {'diploma_scale': 0.8, 'certificate_scale': 0.7},
            '2': {'diploma_scale': 0.85, 'certificate_scale': 0.8},
            '3': {'diploma_scale': 0.95, 'certificate_scale': 0.9}
        }
        
        settings = compression_modes.get(mode, compression_modes['1'])
        return settings['certificate_scale'] if is_certificate else settings['diploma_scale']
    
    @staticmethod
    def choose_compression_mode():
        """Интерактивный выбор режима сжатия"""
        print("\nВыберите режим сжатия:")
        print("1) Максимальное сжатие (файлы ~100 КБ)")
        print("2) Среднее сжатие (файлы ~200 КБ)")
        print("3) Минимальное сжатие (файлы ~500 КБ)")
        
        while True:
            choice = input("Введите номер режима (1-3): ").strip()
            if choice in ['1', '2', '3']:
                mode_names = {
                    '1': 'максимальное',
                    '2': 'среднее',
                    '3': 'минимальное'
                }
                print(f"Выбрано {mode_names[choice]} сжатие\n")
                return choice
            else:
                print("Некорректный выбор. Пожалуйста, введите 1, 2 или 3.")
    
    def get_db_connection(self):
        """Получение соединения с базой данных"""
        try:
            # Отладочная информация (без пароля)
            print(f"Подключение к БД: {self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']} пользователь: {self.db_config['user']}")
            
            conn = psycopg2.connect(**self.db_config)
            return conn
        except Exception as e:
            print(f"Ошибка подключения к базе данных: {e}")
            print(f"Проверьте настройки в файле .env")
            return None

    def get_tournament_participants(self, tournament_name):
        """Получение участников с установленным category_rank"""
        conn = self.get_db_connection()
        if not conn:
            return [], None
        
        try:
            cursor = conn.cursor()
            
            # Получаем всех участников с установленным category_rank
            cursor.execute("""
                SELECT 
                    u.id,
                    u.student_name,
                    u.category,
                    u.category_rank as place,
                    u.balance as score,
                    ei.name as school_name
                FROM "user" u
                LEFT JOIN educational_institutions ei ON u.educational_institution_id = ei.id
                WHERE u.category_rank IS NOT NULL
                AND u.student_name IS NOT NULL
                AND u.student_name != ''
                ORDER BY u.category_rank ASC
            """)
            
            participants = cursor.fetchall()
            print(f"Найдено участников с рейтингом: {len(participants)}")
            
            return participants, tournament_name
            
        except Exception as e:
            print(f"Ошибка при получении участников: {e}")
            return [], None
        finally:
            conn.close()

    def get_font_for_text(self, text, max_width, max_height, font_size=50):
        """Получение подходящего шрифта для текста"""
        try:
            # Пробуем разные шрифты для русского текста
            font_paths = [
                'C:/Windows/Fonts/arial.ttf',
                'C:/Windows/Fonts/calibri.ttf',
                'C:/Windows/Fonts/times.ttf',
                '/System/Library/Fonts/Arial.ttf',  # macOS
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',  # Linux
            ]
            
            font = None
            working_font_path = None
            for font_path in font_paths:
                if os.path.exists(font_path):
                    try:
                        font = ImageFont.truetype(font_path, font_size)
                        working_font_path = font_path
                        break
                    except:
                        continue
            
            if not font:
                font = ImageFont.load_default()
            
            # Проверяем размер текста
            bbox = font.getbbox(text)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            # Если текст не помещается, уменьшаем размер шрифта
            while (text_width > max_width or text_height > max_height) and font_size > 10:
                font_size -= 2
                try:
                    if working_font_path:
                        font = ImageFont.truetype(working_font_path, font_size)
                    else:
                        font = ImageFont.load_default()
                    bbox = font.getbbox(text)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                except:
                    break
            
            return font, text_width, text_height
            
        except Exception as e:
            print(f"Ошибка при получении шрифта: {e}")
            return ImageFont.load_default(), 0, 0

    def split_text_to_lines(self, text, max_width, font):
        """Разбивка текста на строки"""
        words = text.split()
        lines = []
        current_line = ""
        
        for word in words:
            test_line = current_line + (" " if current_line else "") + word
            bbox = font.getbbox(test_line)
            line_width = bbox[2] - bbox[0]
            
            if line_width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                    current_line = word
                else:
                    lines.append(word)
        
        if current_line:
            lines.append(current_line)
        
        return lines

    def generate_certificate(self, user_id, student_name, output_path):
        """Генерация сертификата для участника"""
        try:
            # Проверяем, существует ли уже файл
            if os.path.exists(output_path) and not self.overwrite:
                print(f"⚠️  Файл уже существует: {output_path}")
                response = input("Перезаписать? (y/N): ").strip().lower()
                if response != 'y':
                    print(f"Пропускаем создание сертификата для {student_name}")
                    return
            
            # Открываем шаблон
            image = Image.open(self.certificate_template)
            draw = ImageDraw.Draw(image)
            
            # Получаем координаты для ФИО
            start_x, start_y = self.cert_name_coords['start']
            end_x, end_y = self.cert_name_coords['end']
            max_height = self.cert_name_coords['max_height']
            
            # Вычисляем доступную ширину
            available_width = end_x - start_x
            
            # Получаем подходящий шрифт (увеличиваем размер в 1.5 раза)
            font, text_width, text_height = self.get_font_for_text(
                student_name, available_width, max_height, font_size=75  # было 50, стало 75 (1.5x)
            )
            
            # Вычисляем позицию для центрирования
            # start_y - это нижняя линия, поднимаем текст выше
            text_x = start_x + (available_width - text_width) // 2
            text_y = start_y - text_height - 10  # поднимаем на высоту текста + отступ
            
            # Рисуем текст
            draw.text((text_x, text_y), student_name, fill='black', font=font)
            
            # Дополнительное сжатие для сертификатов - уменьшаем размер изображения
            original_size = image.size
            scale = self.get_compression_scale(self.compression_mode or '1', is_certificate=True)
            new_size = (int(original_size[0] * scale), int(original_size[1] * scale))
            image_resized = image.resize(new_size, Image.Resampling.LANCZOS)
            
            # Сохраняем изображение со сжатием (более сильное сжатие для сертификатов)
            image_resized.save(output_path, 'JPEG', quality=self.certificate_quality, optimize=True, progressive=True)
            print(f"Сертификат создан: {output_path}")
            
        except Exception as e:
            print(f"Ошибка при создании сертификата для {student_name}: {e}")

    def generate_diploma(self, user_id, student_name, place, category, school_name, output_path):
        """Генерация диплома для призера"""
        try:
            # Проверяем, существует ли уже файл
            if os.path.exists(output_path) and not self.overwrite:
                print(f"⚠️  Файл уже существует: {output_path}")
                response = input("Перезаписать? (y/N): ").strip().lower()
                if response != 'y':
                    print(f"Пропускаем создание диплома для {student_name}")
                    return
            
            # Открываем шаблон
            image = Image.open(self.diploma_template)
            draw = ImageDraw.Draw(image)
            
            # Получаем шрифт
            font_paths = [
                'C:/Windows/Fonts/arial.ttf',
                'C:/Windows/Fonts/calibri.ttf',
                '/System/Library/Fonts/Arial.ttf',
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            ]
            
            font = None
            for font_path in font_paths:
                if os.path.exists(font_path):
                    try:
                        font = ImageFont.truetype(font_path, self.diploma_font_size)
                        break
                    except:
                        continue
            
            if not font:
                font = ImageFont.load_default()
            
            # 1. Место (римскими цифрами)
            place_text = self.arabic_to_roman(place)
            place_start = self.diploma_coords['place']['start']
            place_end = self.diploma_coords['place']['end']
            place_x = place_start[0] + (place_end[0] - place_start[0]) // 2
            place_y = place_start[1] - self.diploma_font_size // 2 + 6  # поднимаем над нижней линией + опускаем на 6px
            draw.text((place_x, place_y), place_text, fill='black', font=font, anchor='mm')
            
            # 2. ФИО
            name_start = self.diploma_coords['name']['start']
            name_end = self.diploma_coords['name']['end']
            name_width = name_end[0] - name_start[0]
            
            # Разбиваем ФИО на строки если нужно
            name_lines = self.split_text_to_lines(student_name, name_width, font)
            name_y = name_start[1] - self.diploma_font_size  # поднимаем над нижней линией
            
            for line in name_lines:
                bbox = font.getbbox(line)
                line_width = bbox[2] - bbox[0]
                line_x = name_start[0] + (name_width - line_width) // 2
                draw.text((line_x, name_y), line, fill='black', font=font)
                name_y += self.diploma_font_size + 5
            
            # 3. Группа (категория)
            group_text = category or "Не указана"
            group_start = self.diploma_coords['group']['start']
            group_end = self.diploma_coords['group']['end']
            group_x = group_start[0] + (group_end[0] - group_start[0]) // 2
            group_y = group_start[1] - self.diploma_font_size // 2 + 2  # поднимаем над нижней линией + опускаем на 2px
            draw.text((group_x, group_y), group_text, fill='black', font=font, anchor='mm')
            
            # 4. Название школы (две строки)
            if school_name:
                school_lines = self.split_text_to_lines(school_name, name_width, font)
                
                # Первая строка школы
                school1_start = self.diploma_coords['school_line1']['start']
                school1_end = self.diploma_coords['school_line1']['end']
                school1_width = school1_end[0] - school1_start[0]
                
                if len(school_lines) > 0:
                    line1 = school_lines[0]
                    bbox = font.getbbox(line1)
                    line1_width = bbox[2] - bbox[0]
                    line1_x = school1_start[0] + (school1_width - line1_width) // 2
                    line1_y = school1_start[1] - self.diploma_font_size  # поднимаем над нижней линией
                    draw.text((line1_x, line1_y), line1, fill='black', font=font)
                
                # Вторая строка школы
                if len(school_lines) > 1:
                    school2_start = self.diploma_coords['school_line2']['start']
                    school2_end = self.diploma_coords['school_line2']['end']
                    school2_width = school2_end[0] - school2_start[0]
                    
                    line2 = school_lines[1]
                    bbox = font.getbbox(line2)
                    line2_width = bbox[2] - bbox[0]
                    line2_x = school2_start[0] + (school2_width - line2_width) // 2
                    line2_y = school2_start[1] - self.diploma_font_size  # поднимаем над нижней линией
                    draw.text((line2_x, line2_y), line2, fill='black', font=font)
            
            # Дополнительное сжатие для дипломов - уменьшаем размер изображения
            original_size = image.size
            scale = self.get_compression_scale(self.compression_mode or '1', is_certificate=False)
            new_size = (int(original_size[0] * scale), int(original_size[1] * scale))
            image_resized = image.resize(new_size, Image.Resampling.LANCZOS)
            
            # Сохраняем изображение со сжатием
            image_resized.save(output_path, 'JPEG', quality=self.quality, optimize=True, progressive=True)
            print(f"Диплом создан: {output_path}")
            
        except Exception as e:
            print(f"Ошибка при создании диплома для {student_name}: {e}")

    def create_directories(self, tournament_name):
        """Создание необходимых папок"""
        base_path = f"doc/tournament/{tournament_name}"
        certificate_path = f"{base_path}/certificate"
        diploma_path = f"{base_path}/diploma"
        
        os.makedirs(certificate_path, exist_ok=True)
        os.makedirs(diploma_path, exist_ok=True)
        
        return certificate_path, diploma_path

    def generate_certificates_and_diplomas(self, tournament_name):
        """Основная функция генерации сертификатов и дипломов"""
        print(f"Начинаем генерацию сертификатов и дипломов")
        print(f"Название папки: {tournament_name}")
        
        # Получаем участников с рейтингом
        participants, _ = self.get_tournament_participants(tournament_name)
        
        if not participants:
            print("Участники с рейтингом не найдены")
            return
        
        # Создаем папки
        certificate_path, diploma_path = self.create_directories(tournament_name)
        
        # Обрабатываем каждого участника
        for participant in participants:
            user_id, student_name, category, place, score, school_name = participant
            
            if not student_name:
                print(f"Пропускаем пользователя {user_id}: нет ФИО")
                continue
            
            # Определяем тип документа
            if place and place <= 3:
                # Диплом для призеров (1-3 место)
                output_path = f"{diploma_path}/{user_id}.jpg"
                self.generate_diploma(user_id, student_name, place, category, school_name, output_path)
            else:
                # Сертификат для остальных участников
                output_path = f"{certificate_path}/{user_id}.jpg"
                self.generate_certificate(user_id, student_name, output_path)
        
        print(f"Генерация завершена!")
        print(f"Сертификаты сохранены в: {certificate_path}")
        print(f"Дипломы сохранены в: {diploma_path}")

    def list_available_tournaments(self):
        """Показать статистику участников с рейтингом"""
        conn = self.get_db_connection()
        if not conn:
            return
        
        try:
            cursor = conn.cursor()
            
            # Получаем общую статистику
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_participants,
                    COUNT(CASE WHEN category_rank <= 3 THEN 1 END) as prize_winners,
                    COUNT(CASE WHEN category_rank > 3 THEN 1 END) as certificate_holders
                FROM "user" 
                WHERE category_rank IS NOT NULL
                AND student_name IS NOT NULL
                AND student_name != ''
            """)
            
            stats = cursor.fetchone()
            
            if not stats or stats[0] == 0:
                print("Участники с рейтингом не найдены")
                return
            
            total, prize_winners, certificate_holders = stats
            
            print("\nСтатистика участников с рейтингом:")
            print("-" * 50)
            print(f"Всего участников: {total}")
            print(f"Призеры (1-3 место): {prize_winners}")
            print(f"Участники (сертификаты): {certificate_holders}")
            print("-" * 50)
            
            # Показываем топ-10 участников
            cursor.execute("""
                SELECT 
                    u.id,
                    u.student_name,
                    u.category,
                    u.category_rank,
                    ei.name as school_name
                FROM "user" u
                LEFT JOIN educational_institutions ei ON u.educational_institution_id = ei.id
                WHERE u.category_rank IS NOT NULL
                AND u.student_name IS NOT NULL
                AND u.student_name != ''
                ORDER BY u.category_rank ASC
                LIMIT 10
            """)
            
            top_participants = cursor.fetchall()
            
            print("\nТоп-10 участников:")
            print("-" * 80)
            print(f"{'Место':<5} {'ID':<5} {'ФИО':<30} {'Группа':<10} {'Школа':<25}")
            print("-" * 80)
            
            for participant in top_participants:
                user_id, student_name, category, place, school_name = participant
                school_short = school_name[:22] if school_name else "Не указана"
                print(f"{place:<5} {user_id:<5} {student_name[:28]:<30} {category or 'Не указана':<10} {school_short:<25}")
            
            print("-" * 80)
            
        except Exception as e:
            print(f"Ошибка при получении статистики: {e}")
        finally:
            conn.close()

    def dry_run_generation(self, tournament_name):
        """Показать что будет создано без фактического создания"""
        print(f"РЕЖИМ ПРЕДВАРИТЕЛЬНОГО ПРОСМОТРА")
        print(f"Название папки: {tournament_name}")
        print("=" * 60)
        
        # Получаем участников с рейтингом
        participants, _ = self.get_tournament_participants(tournament_name)
        
        if not participants:
            print("Участники с рейтингом не найдены")
            return
        
        print(f"Всего участников с рейтингом: {len(participants)}")
        print()
        
        diplomas_count = 0
        certificates_count = 0
        
        print("Список документов для создания:")
        print("-" * 80)
        print(f"{'Тип':<12} {'ID':<5} {'ФИО':<30} {'Место':<6} {'Группа':<10}")
        print("-" * 80)
        
        for participant in participants:
            user_id, student_name, category, place, score, school_name = participant
            
            if not student_name:
                continue
            
            if place and place <= 3:
                doc_type = "ДИПЛОМ"
                diplomas_count += 1
                place_str = self.arabic_to_roman(place)  # Римские цифры для диплома
            else:
                doc_type = "СЕРТИФИКАТ"
                certificates_count += 1
                place_str = str(place) if place else "-"
            
            print(f"{doc_type:<12} {user_id:<5} {student_name[:28]:<30} {place_str:<6} {category or 'Не указана':<10}")
        
        print("-" * 80)
        print(f"Дипломов будет создано: {diplomas_count}")
        print(f"Сертификатов будет создано: {certificates_count}")
        print()
        print("Папки для создания:")
        print(f"  - doc/tournament/{tournament_name}/certificate/")
        print(f"  - doc/tournament/{tournament_name}/diploma/")

def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(description='Генератор сертификатов и дипломов для турниров')
    parser.add_argument('--tournament', '-t', type=str, help='Название папки для сохранения документов')
    parser.add_argument('--list-tournaments', '-l', action='store_true', help='Показать статистику участников с рейтингом')
    parser.add_argument('--dry-run', '-d', action='store_true', help='Показать что будет создано без фактического создания')
    parser.add_argument('--overwrite', '-o', action='store_true', help='Перезаписывать существующие файлы без запроса')
    parser.add_argument('--quality', '-q', type=int, default=40, help='Качество сжатия JPEG для дипломов (1-100, по умолчанию 40)')
    parser.add_argument('--cert-quality', '-cq', type=int, default=15, help='Качество сжатия JPEG для сертификатов (1-100, по умолчанию 15)')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("ГЕНЕРАТОР СЕРТИФИКАТОВ И ДИПЛОМОВ")
    print("=" * 60)
    
    # Создаем генератор
    generator = CertificateGenerator(overwrite=args.overwrite, quality=args.quality, certificate_quality=args.cert_quality)
    
    if args.list_tournaments:
        generator.list_available_tournaments()
        return
    
    # Получаем название папки
    tournament_name = args.tournament
    if not tournament_name:
        tournament_name = input("Введите название папки для сохранения документов: ").strip()
    
    if not tournament_name:
        print("Название папки не может быть пустым!")
        return
    
    # Выбор режима сжатия (если не в режиме dry-run и не указаны явные параметры качества)
    compression_mode = None
    if not args.dry_run:
        compression_mode = CertificateGenerator.choose_compression_mode()
        # Пересоздаем генератор с выбранным режимом сжатия
        generator = CertificateGenerator(
            overwrite=args.overwrite, 
            compression_mode=compression_mode
        )
    
    if args.dry_run:
        generator.dry_run_generation(tournament_name)
    else:
        generator.generate_certificates_and_diplomas(tournament_name)

if __name__ == "__main__":
    main()
