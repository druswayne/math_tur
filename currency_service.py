#!/usr/bin/env python3
"""
Сервис для работы с курсами валют
"""

import requests
import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import SessionLocal, CurrencyRate

import logging

class CurrencyService:
    """Сервис для получения и кэширования курсов валют"""
    
    def __init__(self):
        self.cache = {}
        self.cache_duration = timedelta(hours=1)  # Обновляем курс каждый час
        self.logger = logging.getLogger(__name__)
    
    def get_byn_to_rub_rate(self):
        """Получает актуальный курс BYN → RUB"""
        try:
            # Проверяем кэш
            if self._is_cache_valid('BYN_RUB'):
                return self.cache['BYN_RUB']['rate']
            
            # Получаем курс через API НБ РБ
            rate = self._fetch_from_nbrb()
            if rate:
                self._update_cache('BYN_RUB', rate)
                self._save_to_db('BYN_RUB', rate, 'nbrb')
                return rate
            
            # Если не удалось получить от НБ РБ, пробуем ЦБ РФ
            rate = self._fetch_from_cbr()
            if rate:
                self._update_cache('BYN_RUB', rate)
                self._save_to_db('BYN_RUB', rate, 'cbr')
                return rate
            
            # Если API недоступны, пробуем получить последний курс из БД
            rate = self.get_latest_rate_from_db('BYN_RUB')
            if rate:
                self.logger.warning(f"API недоступны, используем последний сохраненный курс из БД: {rate}")
                self._update_cache('BYN_RUB', rate)
                return rate
            
            # Если в БД нет курсов, используем резервный курс
            fallback_rate = 30.0  # Резервный курс 1 BYN = 30 RUB
            self.logger.warning(f"API недоступны и нет сохраненных курсов в БД, используем резервный: {fallback_rate}")
            self._update_cache('BYN_RUB', fallback_rate)
            self._save_to_db('BYN_RUB', fallback_rate, 'fallback')
            return fallback_rate
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении курса валют: {e}")
            # Возвращаем резервный курс
            return 30.0
    
    def _fetch_from_cbr(self):
        """Получает курс через API Центрального Банка РФ"""
        try:
            url = "https://www.cbr-xml-daily.ru/daily_json.js"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Получаем курс BYN (код валюты в ЦБ РФ)
            byn_rate = None
            for currency in data.get('Valute', {}).values():
                if currency.get('CharCode') == 'BYN':
                    byn_rate = currency.get('Value', 0)
                    break
            
            if byn_rate:
                # Конвертируем: 1 BYN = X RUB
                return float(byn_rate)*1.07
            
            return None
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении курса от ЦБ РФ: {e}")
            return None
    
    def _fetch_from_nbrb(self):
        """Получает курс через API Национального Банка РБ"""
        try:
            url = "https://api.nbrb.by/ExRates/Rates/456?ParamMode=0"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Получаем курс RUB к BYN
            rub_rate = float(data.get('Cur_OfficialRate')/100)*0.93
            if rub_rate:
                # Конвертируем: 1 BYN = 1/RUB_rate RUB
                return 1.0 / float(rub_rate)
            
            return None
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении курса от НБ РБ: {e}")
            return None
    
    def _save_to_db(self, currency_pair, rate, source):
        """Сохраняет курс валют в базу данных раз в сутки"""
        try:
            db = SessionLocal()
            
            # Проверяем, есть ли уже запись за сегодня
            today = datetime.now().date()
            existing_rate = db.query(CurrencyRate).filter(
                CurrencyRate.currency_pair == currency_pair,
                CurrencyRate.created_at >= today
            ).first()
            
            if not existing_rate:
                # Создаем новую запись
                currency_rate = CurrencyRate(
                    currency_pair=currency_pair,
                    rate=rate,
                    source=source
                )
                db.add(currency_rate)
                db.commit()
                self.logger.info(f"Курс {currency_pair} = {rate} (источник: {source}) сохранен в БД")
            else:
                self.logger.debug(f"Курс {currency_pair} уже сохранен за сегодня")
                
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении курса в БД: {e}")
        finally:
            db.close()
    
    def get_latest_rate_from_db(self, currency_pair='BYN_RUB'):
        """Получает последний сохраненный курс из базы данных"""
        try:
            db = SessionLocal()
            latest_rate = db.query(CurrencyRate).filter(
                CurrencyRate.currency_pair == currency_pair
            ).order_by(CurrencyRate.created_at.desc()).first()
            
            if latest_rate:
                return latest_rate.rate
            return None
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении курса из БД: {e}")
            return None
        finally:
            db.close()
    
    def _is_cache_valid(self, key):
        """Проверяет, действителен ли кэш"""
        if key not in self.cache:
            return False
        
        cache_time = self.cache[key]['timestamp']
        return datetime.now() - cache_time < self.cache_duration
    
    def _update_cache(self, key, rate):
        """Обновляет кэш"""
        self.cache[key] = {
            'rate': rate,
            'timestamp': datetime.now()
        }
    
    def convert_byn_to_rub(self, byn_amount):
        """Конвертирует сумму из BYN в RUB"""
        rate = self.get_byn_to_rub_rate()
        return round(byn_amount * rate, 2)
    
    def convert_rub_to_byn(self, rub_amount):
        """Конвертирует сумму из RUB в BYN"""
        rate = self.get_byn_to_rub_rate()
        return round(rub_amount / rate, 2)
    
    def get_formatted_rate(self):
        """Возвращает отформатированный курс для отображения"""
        rate = self.get_byn_to_rub_rate()
        return f"1 BYN = {rate:.2f} RUB"

# Создаем глобальный экземпляр сервиса
currency_service = CurrencyService() 