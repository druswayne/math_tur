#!/usr/bin/env python3
"""
Сервис для работы с курсами валют
"""

import requests
import json
from datetime import datetime, timedelta

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
            
            # Получаем курс через API ЦБ РФ
            rate = self._fetch_from_cbr()
            if rate:
                self._update_cache('BYN_RUB', rate)
                return rate
            
            # Если не удалось получить от ЦБ РФ, пробуем НБ РБ
            rate = self._fetch_from_nbrb()
            if rate:
                self._update_cache('BYN_RUB', rate)
                return rate
            
            # Если все API недоступны, используем резервный курс
            fallback_rate = 30.0  # Резервный курс 1 BYN = 30 RUB
            self.logger.warning(f"Не удалось получить курс валют, используем резервный: {fallback_rate}")
            self._update_cache('BYN_RUB', fallback_rate)
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
                return float(byn_rate)
            
            return None
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении курса от ЦБ РФ: {e}")
            return None
    
    def _fetch_from_nbrb(self):
        """Получает курс через API Национального Банка РБ"""
        try:
            url = "https://www.nbrb.by/api/exrates/rates/RUB"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Получаем курс RUB к BYN
            rub_rate = data.get('Cur_OfficialRate', 0)
            if rub_rate:
                # Конвертируем: 1 BYN = 1/RUB_rate RUB
                return 1.0 / float(rub_rate)
            
            return None
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении курса от НБ РБ: {e}")
            return None
    
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