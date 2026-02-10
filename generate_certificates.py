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
        
        # Координаты для сертификата
        self.cert_name_coords = {
            'start': (168, 568),
            'end': (729, 568),
            'max_height': 50
        }
        self.cert_score_coords = {
            'start': (315, 815),
            'end': (381, 815)
        }
        self.cert_place_coords = {
            'start': (701, 815),
            'end': (742, 815)
        }
        
        # Координаты для диплома
        self.diploma_coords = {
            'place': {'start': (340, 408), 'end': (458, 408)},       # место (1–3) вверху
            'name': {'start': (177, 552), 'end': (738, 552)},
            'group': {'start': (486, 578), 'end': (528, 578)},       # класс
            'school_line1': {'start': (175, 641), 'end': (735, 641)}, # первая строка школы
            'school_line2': {'start': (175, 690), 'end': (735, 690)},# вторая строка школы
            'score': {'start': (502, 846), 'end': (543, 846)}
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
        """Получение участников с установленным category_rank, которые участвовали в турнирах"""
        conn = self.get_db_connection()
        if not conn:
            return [], None
        
        try:
            cursor = conn.cursor()
            
            # Получаем всех участников с установленным category_rank, которые участвовали в турнирах
            # (как в лавке призов - только те, у кого есть TournamentParticipation)
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
                AND u.is_admin = FALSE
                AND EXISTS (
                    SELECT 1 FROM tournament_participation tp 
                    WHERE tp.user_id = u.id
                )
                ORDER BY u.category, u.category_rank ASC
            """)
            
            participants = cursor.fetchall()
            print(f"Найдено участников с рейтингом (участвовали в турнирах): {len(participants)}")
            
            return participants, tournament_name
            
        except Exception as e:
            print(f"Ошибка при получении участников: {e}")
            return [], None
        finally:
            conn.close()
    
    def get_shop_settings(self):
        """Получение настроек лавки призов для определения процентов по категориям"""
        conn = self.get_db_connection()
        if not conn:
            return {}
        
        try:
            cursor = conn.cursor()
            
            # Получаем настройки лавки
            cursor.execute("""
                SELECT 
                    top_users_percentage_1_2,
                    top_users_percentage_3,
                    top_users_percentage_4,
                    top_users_percentage_5,
                    top_users_percentage_6,
                    top_users_percentage_7,
                    top_users_percentage_8,
                    top_users_percentage_9,
                    top_users_percentage_10,
                    top_users_percentage_11
                FROM shop_settings
                LIMIT 1
            """)
            
            row = cursor.fetchone()
            if not row:
                # Если настроек нет, используем 10% по умолчанию для всех категорий
                return {cat: 10 for cat in ['1-2', '3', '4', '5', '6', '7', '8', '9', '10', '11']}
            
            # Маппинг полей на категории
            settings = {
                '1-2': row[0] or 10,
                '3': row[1] or 10,
                '4': row[2] or 10,
                '5': row[3] or 10,
                '6': row[4] or 10,
                '7': row[5] or 10,
                '8': row[6] or 10,
                '9': row[7] or 10,
                '10': row[8] or 10,
                '11': row[9] or 10
            }
            
            return settings
            
        except Exception as e:
            print(f"Ошибка при получении настроек лавки: {e}")
            # В случае ошибки используем 10% по умолчанию
            return {cat: 10 for cat in ['1-2', '3', '4', '5', '6', '7', '8', '9', '10', '11']}
        finally:
            conn.close()
    
    def get_category_participants_count(self, category):
        """Получение количества участников турниров в категории"""
        conn = self.get_db_connection()
        if not conn:
            return 0
        
        try:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT COUNT(*)
                FROM "user" u
                WHERE u.category = %s
                AND u.category_rank IS NOT NULL
                AND u.is_admin = FALSE
                AND EXISTS (
                    SELECT 1 FROM tournament_participation tp 
                    WHERE tp.user_id = u.id
                )
            """, (category,))
            
            result = cursor.fetchone()
            return result[0] if result else 0
            
        except Exception as e:
            print(f"Ошибка при подсчете участников категории {category}: {e}")
            return 0
        finally:
            conn.close()
    
    def calculate_diploma_recipients(self, participants):
        """Вычисление списка участников, которые получат дипломы: только 1–3 место в каждой группе (категории)"""
        if not participants:
            return set()
        
        # Группируем участников по категориям (уже отсортированы по category_rank ASC)
        participants_by_category = {}
        for participant in participants:
            user_id, student_name, category, place, score, school_name = participant
            if category not in participants_by_category:
                participants_by_category[category] = []
            participants_by_category[category].append(participant)
        
        diploma_recipients = set()
        
        # Дипломы только для 1, 2 и 3 места в каждой категории
        for category, category_participants in participants_by_category.items():
            category_users_count = len(category_participants)
            # Берём только первых троих (места 1, 2, 3)
            allowed_count = min(3, category_users_count)
            print(f"Категория {category}: {category_users_count} участников, дипломов (1–3 место): {allowed_count}")
            for participant in category_participants[:allowed_count]:
                diploma_recipients.add(participant[0])
        
        return diploma_recipients

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

    def generate_certificate(self, user_id, student_name, score, place, output_path):
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
            
            # Получаем шрифт размером 20 для баллов и места
            small_font = None
            for font_name in ['arial.ttf', 'calibri.ttf', 'times.ttf', 'DejaVuSans.ttf']:
                try:
                    small_font = ImageFont.truetype(font_name, 20)
                    break
                except:
                    continue
            
            if not small_font:
                small_font = ImageFont.load_default()
            
            # Получаем координаты для ФИО
            start_x, start_y = self.cert_name_coords['start']
            end_x, end_y = self.cert_name_coords['end']
            max_height = self.cert_name_coords['max_height']
            
            # Вычисляем доступную ширину
            available_width = end_x - start_x
            
            # Получаем подходящий шрифт (уменьшаем размер на 50%)
            font, text_width, text_height = self.get_font_for_text(
                student_name, available_width, max_height, font_size=37  # было 75, стало 37 (0.5x)
            )
            
            # Вычисляем позицию для центрирования
            # start_y - это нижняя линия, поднимаем текст выше
            text_x = start_x + (available_width - text_width) // 2
            text_y = start_y - text_height - 10  # поднимаем на высоту текста + отступ
            
            # Рисуем ФИО
            draw.text((text_x, text_y), student_name, fill='black', font=font)
            
            # Рисуем баллы
            score_text = str(score) if score else "0"
            score_start = self.cert_score_coords['start']
            score_end = self.cert_score_coords['end']
            score_width = score_end[0] - score_start[0]
            
            bbox = small_font.getbbox(score_text)
            score_text_width = bbox[2] - bbox[0]
            score_text_height = bbox[3] - bbox[1]
            
            score_x = score_start[0] + (score_width - score_text_width) // 2
            score_y = score_start[1] - score_text_height - 5  # поднимаем над линией
            draw.text((score_x, score_y), score_text, fill='black', font=small_font)
            
            # Рисуем место
            place_text = str(place) if place else "-"
            place_start = self.cert_place_coords['start']
            place_end = self.cert_place_coords['end']
            place_width = place_end[0] - place_start[0]
            
            bbox = small_font.getbbox(place_text)
            place_text_width = bbox[2] - bbox[0]
            place_text_height = bbox[3] - bbox[1]
            
            place_x = place_start[0] + (place_width - place_text_width) // 2
            place_y = place_start[1] - place_text_height - 5  # поднимаем над линией
            draw.text((place_x, place_y), place_text, fill='black', font=small_font)
            
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

    def generate_diploma(self, user_id, student_name, place, category, school_name, score, output_path):
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
            
            # Получаем шрифт для остальных полей (обычный)
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
            
            # Получаем жирный шрифт для имени (на 50% больше размера)
            name_font_size = int(self.diploma_font_size * 1.5)  # 20 * 1.5 = 30
            bold_font_paths = [
                'C:/Windows/Fonts/arialbd.ttf',  # Arial Bold
                'C:/Windows/Fonts/calibrib.ttf',  # Calibri Bold
                'C:/Windows/Fonts/arial.ttf',  # Fallback на обычный Arial
                '/System/Library/Fonts/Arial-Bold.ttf',  # macOS
                '/System/Library/Fonts/Arial.ttf',  # macOS fallback
                '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',  # Linux
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',  # Linux fallback
            ]
            
            name_font = None
            for font_path in bold_font_paths:
                if os.path.exists(font_path):
                    try:
                        name_font = ImageFont.truetype(font_path, name_font_size)
                        break
                    except:
                        continue
            
            # Если не нашли жирный шрифт, используем обычный увеличенного размера
            if not name_font:
                for font_path in font_paths:
                    if os.path.exists(font_path):
                        try:
                            name_font = ImageFont.truetype(font_path, name_font_size)
                            break
                        except:
                            continue
            
            if not name_font:
                name_font = ImageFont.load_default()
            
            # 0. Место (1–3) вверху диплома
            place_text = str(place) if place else "-"
            place_start = self.diploma_coords['place']['start']
            place_end = self.diploma_coords['place']['end']
            place_width = place_end[0] - place_start[0]
            
            # Получаем шрифт размером 20 для баллов и места
            small_font = None
            for font_name in ['arial.ttf', 'calibri.ttf', 'times.ttf', 'DejaVuSans.ttf']:
                try:
                    small_font = ImageFont.truetype(font_name, 20)
                    break
                except:
                    continue
            
            if not small_font:
                small_font = ImageFont.load_default()
            
            # Рисуем место вверху (крупнее)
            place_font_size = 36
            place_font = None
            for fp in font_paths:
                if os.path.exists(fp):
                    try:
                        place_font = ImageFont.truetype(fp, place_font_size)
                        break
                    except Exception:
                        continue
            if not place_font:
                place_font = small_font
            bbox = place_font.getbbox(place_text)
            place_text_width = bbox[2] - bbox[0]
            place_text_height = bbox[3] - bbox[1]
            place_x = place_start[0] + (place_width - place_text_width) // 2
            place_y = place_start[1] - place_text_height - 5
            draw.text((place_x, place_y), place_text, fill='black', font=place_font)
            
            # 1. ФИО (жирным и на 50% больше)
            name_start = self.diploma_coords['name']['start']
            name_end = self.diploma_coords['name']['end']
            name_width = name_end[0] - name_start[0]
            
            # Разбиваем ФИО на строки если нужно (используем жирный шрифт)
            name_lines = self.split_text_to_lines(student_name, name_width, name_font)
            name_y = name_start[1] - name_font_size  # поднимаем над нижней линией
            
            for line in name_lines:
                bbox = name_font.getbbox(line)
                line_width = bbox[2] - bbox[0]
                line_x = name_start[0] + (name_width - line_width) // 2
                draw.text((line_x, name_y), line, fill='black', font=name_font)
                name_y += name_font_size + 5
            
            # 2. Группа (категория/класс)
            group_text = category or "Не указана"
            group_start = self.diploma_coords['group']['start']
            group_end = self.diploma_coords['group']['end']
            group_x = group_start[0] + (group_end[0] - group_start[0]) // 2
            group_y = group_start[1] - self.diploma_font_size // 2 + 2  # поднимаем над нижней линией + опускаем на 2px
            draw.text((group_x, group_y), group_text, fill='black', font=font, anchor='mm')
            
            # 3. Название школы (две строки)
            if school_name:
                line1_coords = self.diploma_coords['school_line1']
                line2_coords = self.diploma_coords['school_line2']
                school_width = line1_coords['end'][0] - line1_coords['start'][0]
                school_lines = self.split_text_to_lines(school_name, school_width, font)
                if len(school_lines) > 0:
                    line1 = school_lines[0]
                    bbox = font.getbbox(line1)
                    line1_width = bbox[2] - bbox[0]
                    line1_x = line1_coords['start'][0] + (school_width - line1_width) // 2
                    line1_y = line1_coords['start'][1] - self.diploma_font_size
                    draw.text((line1_x, line1_y), line1, fill='black', font=font)
                if len(school_lines) > 1:
                    line2 = school_lines[1]
                    bbox = font.getbbox(line2)
                    line2_width = bbox[2] - bbox[0]
                    line2_x = line2_coords['start'][0] + (school_width - line2_width) // 2
                    line2_y = line2_coords['start'][1] - self.diploma_font_size
                    draw.text((line2_x, line2_y), line2, fill='black', font=font)
            
            # 4. Баллы
            score_text = str(score) if score else "0"
            score_start = self.diploma_coords['score']['start']
            score_end = self.diploma_coords['score']['end']
            score_width = score_end[0] - score_start[0]
            
            bbox = small_font.getbbox(score_text)
            score_text_width = bbox[2] - bbox[0]
            score_text_height = bbox[3] - bbox[1]
            
            score_x = score_start[0] + (score_width - score_text_width) // 2
            score_y = score_start[1] - score_text_height - 5  # поднимаем над линией
            draw.text((score_x, score_y), score_text, fill='black', font=small_font)
            
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
        
        # Получаем участников с рейтингом (только те, кто участвовал в турнирах)
        participants, _ = self.get_tournament_participants(tournament_name)
        
        if not participants:
            print("Участники с рейтингом не найдены")
            return
        
        # Создаем папки
        certificate_path, diploma_path = self.create_directories(tournament_name)
        
        # Вычисляем список участников, которые получат дипломы (по категориям, как в лавке призов)
        diploma_recipients = self.calculate_diploma_recipients(participants)
        
        total_participants = len(participants)
        diplomas_count = len(diploma_recipients)
        certificates_count = total_participants - diplomas_count
        
        print(f"\nВсего участников: {total_participants}")
        print(f"Дипломов будет создано: {diplomas_count}")
        print(f"Сертификатов будет создано: {certificates_count}\n")
        
        # Обрабатываем каждого участника
        for participant in participants:
            user_id, student_name, category, place, score, school_name = participant
            
            if not student_name:
                print(f"Пропускаем пользователя {user_id}: нет ФИО")
                continue
            
            # Определяем тип документа (используем логику лавки призов)
            if user_id in diploma_recipients:
                # Диплом для топ участников категории
                output_path = f"{diploma_path}/{user_id}.jpg"
                self.generate_diploma(user_id, student_name, place, category, school_name, score, output_path)
            else:
                # Сертификат для остальных участников
                output_path = f"{certificate_path}/{user_id}.jpg"
                self.generate_certificate(user_id, student_name, score, place, output_path)
        
        print(f"\nГенерация завершена!")
        print(f"Сертификаты сохранены в: {certificate_path}")
        print(f"Дипломы сохранены в: {diploma_path}")

    def list_available_tournaments(self):
        """Показать статистику участников с рейтингом по категориям (дипломы только 1–3 место в группе)"""
        conn = self.get_db_connection()
        if not conn:
            return
        
        try:
            cursor = conn.cursor()
            
            # Получаем общую статистику (только участники турниров)
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_participants
                FROM "user" u
                WHERE u.category_rank IS NOT NULL
                AND u.student_name IS NOT NULL
                AND u.student_name != ''
                AND u.is_admin = FALSE
                AND EXISTS (
                    SELECT 1 FROM tournament_participation tp 
                    WHERE tp.user_id = u.id
                )
            """)
            
            total_result = cursor.fetchone()
            total = total_result[0] if total_result and total_result[0] else 0
            
            if total == 0:
                print("Участники с рейтингом не найдены")
                return
            
            print("\nСтатистика участников с рейтингом (участвовали в турнирах). Дипломы: только 1–3 место в каждой группе.")
            print("=" * 100)
            print(f"{'Категория':<12} {'Участников':<12} {'Дипломов (1-3)':<15} {'Сертификатов':<15}")
            print("-" * 100)
            
            total_diplomas = 0
            total_certificates = 0
            
            categories = ['1-2', '3', '4', '5', '6', '7', '8', '9', '10', '11']
            
            for category in categories:
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM "user" u
                    WHERE u.category = %s
                    AND u.category_rank IS NOT NULL
                    AND u.student_name IS NOT NULL
                    AND u.student_name != ''
                    AND u.is_admin = FALSE
                    AND EXISTS (
                        SELECT 1 FROM tournament_participation tp 
                        WHERE tp.user_id = u.id
                    )
                """, (category,))
                
                category_count_result = cursor.fetchone()
                category_count = category_count_result[0] if category_count_result and category_count_result[0] else 0
                
                if category_count == 0:
                    continue
                
                # Дипломы только для 1–3 места в каждой группе
                diplomas_count = min(3, category_count)
                certificates_count = category_count - diplomas_count
                
                total_diplomas += diplomas_count
                total_certificates += certificates_count
                
                print(f"{category:<12} {category_count:<12} {diplomas_count:<15} {certificates_count:<15}")
            
            print("-" * 100)
            print(f"{'ИТОГО':<12} {total:<12} {total_diplomas:<15} {total_certificates:<15}")
            print("=" * 100)
            
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
                AND u.is_admin = FALSE
                AND EXISTS (
                    SELECT 1 FROM tournament_participation tp 
                    WHERE tp.user_id = u.id
                )
                ORDER BY u.category, u.category_rank ASC
                LIMIT 10
            """)
            
            top_participants = cursor.fetchall()
            
            if top_participants:
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
        
        # Получаем участников с рейтингом (только те, кто участвовал в турнирах)
        participants, _ = self.get_tournament_participants(tournament_name)
        
        if not participants:
            print("Участники с рейтингом не найдены")
            return
        
        print(f"Всего участников с рейтингом (участвовали в турнирах): {len(participants)}")
        print()
        
        # Вычисляем список участников, которые получат дипломы (по категориям, как в лавке призов)
        diploma_recipients = self.calculate_diploma_recipients(participants)
        
        total_participants = len(participants)
        diplomas_count = len(diploma_recipients)
        certificates_count = total_participants - diplomas_count
        
        print(f"\nДипломов будет создано: {diplomas_count}")
        print(f"Сертификатов будет создано: {certificates_count}")
        print()
        
        print("Список документов для создания:")
        print("-" * 80)
        print(f"{'Тип':<12} {'ID':<5} {'ФИО':<30} {'Место':<6} {'Группа':<10}")
        print("-" * 80)
        
        for participant in participants:
            user_id, student_name, category, place, score, school_name = participant
            
            if not student_name:
                continue
            
            if user_id in diploma_recipients:
                doc_type = "ДИПЛОМ"
                place_str = str(place) if place else "-"
            else:
                doc_type = "СЕРТИФИКАТ"
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
