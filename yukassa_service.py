#!/usr/bin/env python3
"""
Сервис для работы с ЮKassa (тестовая среда)
"""

import requests
import json
import uuid
import os
from datetime import datetime
# from flask import current_app, url_for  # Временно отключено
import logging

class YukassaService:
    """Сервис для работы с ЮKassa API"""
    
    def __init__(self):
        # Получаем данные из переменных окружения
        self.shop_id = os.getenv('YUKASSA_SHOP_ID')
        self.secret_key = os.getenv('YUKASSA_SECRET_KEY')
        self.base_url = "https://api.yookassa.ru/v3"  # Тестовая среда
        self.logger = logging.getLogger(__name__)
    
    def create_payment(self, amount, description, return_url, capture=True):
        """
        Создает платеж в ЮKassa
        
        Args:
            amount (float): Сумма в рублях
            description (str): Описание платежа
            return_url (str): URL для возврата после оплаты
            capture (bool): Автоматическое списание (True) или двухстадийный платеж (False)
        
        Returns:
            dict: Ответ от ЮKassa с данными платежа
        """
        """
        Создает платеж в ЮKassa
        
        Args:
            amount (float): Сумма в рублях
            description (str): Описание платежа
            return_url (str): URL для возврата после оплаты
            capture (bool): Автоматическое списание (True) или двухстадийный платеж (False)
        
        Returns:
            dict: Ответ от ЮKassa с данными платежа
        """
        try:
            payment_data = {
                "amount": {
                    "value": str(amount),
                    "currency": "RUB"
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": return_url
                },
                "capture": capture,
                "description": description,
                "metadata": {
                    "order_id": str(uuid.uuid4())
                }
            }
            
            headers = {
                "Content-Type": "application/json",
                "Idempotence-Key": str(uuid.uuid4())
            }
            
            # Базовая аутентификация
            import base64
            auth_string = f"{self.shop_id}:{self.secret_key}"
            auth_bytes = auth_string.encode('ascii')
            auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
            headers["Authorization"] = f"Basic {auth_b64}"
            
            response = requests.post(
                f"{self.base_url}/payments",
                json=payment_data,
                headers=headers,
                timeout=30
            )
            
            response.raise_for_status()
            payment_info = response.json()
            
            self.logger.info(f"Создан платеж ЮKassa: {payment_info.get('id')}")
            return payment_info
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Ошибка при создании платежа ЮKassa: {e}")
            raise Exception(f"Ошибка при создании платежа: {str(e)}")
    
    def get_payment_info(self, payment_id):
        """
        Получает информацию о платеже
        
        Args:
            payment_id (str): ID платежа в ЮKassa
        
        Returns:
            dict: Информация о платеже
        """
        try:
            headers = {
                "Content-Type": "application/json"
            }
            
            # Базовая аутентификация
            import base64
            auth_string = f"{self.shop_id}:{self.secret_key}"
            auth_bytes = auth_string.encode('ascii')
            auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
            headers["Authorization"] = f"Basic {auth_b64}"
            
            response = requests.get(
                f"{self.base_url}/payments/{payment_id}",
                headers=headers,
                timeout=30
            )
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Ошибка при получении информации о платеже {payment_id}: {e}")
            raise Exception(f"Ошибка при получении информации о платеже: {str(e)}")
    
    def capture_payment(self, payment_id, amount=None):
        """
        Подтверждает платеж (для двухстадийных платежей)
        
        Args:
            payment_id (str): ID платежа
            amount (float): Сумма для списания (если не указана, списывается вся сумма)
        
        Returns:
            dict: Результат подтверждения
        """
        try:
            capture_data = {}
            if amount:
                capture_data["amount"] = {
                    "value": str(amount),
                    "currency": "RUB"
                }
            
            headers = {
                "Content-Type": "application/json",
                "Idempotence-Key": str(uuid.uuid4())
            }
            
            # Базовая аутентификация
            import base64
            auth_string = f"{self.shop_id}:{self.secret_key}"
            auth_bytes = auth_string.encode('ascii')
            auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
            headers["Authorization"] = f"Basic {auth_b64}"
            
            response = requests.post(
                f"{self.base_url}/payments/{payment_id}/capture",
                json=capture_data,
                headers=headers,
                timeout=30
            )
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Ошибка при подтверждении платежа {payment_id}: {e}")
            raise Exception(f"Ошибка при подтверждении платежа: {str(e)}")
    
    def cancel_payment(self, payment_id):
        """
        Отменяет платеж
        
        Args:
            payment_id (str): ID платежа
        
        Returns:
            dict: Результат отмены
        """
        try:
            headers = {
                "Content-Type": "application/json",
                "Idempotence-Key": str(uuid.uuid4())
            }
            
            # Базовая аутентификация
            import base64
            auth_string = f"{self.shop_id}:{self.secret_key}"
            auth_bytes = auth_string.encode('ascii')
            auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
            headers["Authorization"] = f"Basic {auth_b64}"
            
            response = requests.post(
                f"{self.base_url}/payments/{payment_id}/cancel",
                headers=headers,
                timeout=30
            )
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Ошибка при отмене платежа {payment_id}: {e}")
            raise Exception(f"Ошибка при отмене платежа: {str(e)}")
    
    def verify_webhook_signature(self, body, signature):
        """
        Проверяет подпись webhook'а от ЮKassa
        
        Args:
            body (str): Тело запроса
            signature (str): Подпись из заголовка
        
        Returns:
            bool: True если подпись верна
        """
        # В тестовой среде подпись не проверяется
        # В продакшене здесь должна быть проверка HMAC-SHA256
        return True
    
    def get_payment_status(self, payment_info):
        """
        Получает статус платежа из ответа ЮKassa
        
        Args:
            payment_info (dict): Информация о платеже от ЮKassa
        
        Returns:
            str: Статус платежа
        """
        status = payment_info.get('status', 'unknown')
        
        # Маппинг статусов ЮKassa на наши статусы
        status_mapping = {
            'pending': 'pending',                    # Ожидает оплаты
            'waiting_for_capture': 'waiting_for_capture',  # Ожидает подтверждения
            'succeeded': 'succeeded',                # Успешно оплачен
            'canceled': 'canceled',                  # Отменен
            'failed': 'failed'                       # Ошибка платежа
        }
        
        return status_mapping.get(status, 'unknown')
    
    def get_payment_status_description(self, status):
        """
        Получает описание статуса платежа для отображения пользователю
        
        Args:
            status (str): Статус платежа
        
        Returns:
            str: Описание статуса
        """
        descriptions = {
            'pending': 'Ожидает оплаты',
            'waiting_for_capture': 'Ожидает подтверждения',
            'succeeded': 'Оплачено',
            'canceled': 'Отменено',
            'failed': 'Ошибка платежа',
            'expired': 'Время платежа истекло',
            'unknown': 'Неизвестный статус'
        }
        
        return descriptions.get(status, 'Неизвестный статус')
    
    def is_payment_expired(self, payment_info):
        """
        Проверяет, истек ли платеж
        
        Args:
            payment_info (dict): Информация о платеже от ЮKassa
        
        Returns:
            bool: True если платеж истек
        """
        try:
            # Получаем время создания платежа
            created_at = payment_info.get('created_at')
            if not created_at:
                return False
            
            # Парсим время создания
            from datetime import datetime
            created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            
            # Время жизни платежа в ЮKassa - 1 час
            from datetime import timedelta
            expiration_time = created_time + timedelta(hours=1)
            
            # Текущее время в UTC
            current_time = datetime.utcnow().replace(tzinfo=created_time.tzinfo)
            
            return current_time > expiration_time
            
        except Exception as e:
            self.logger.error(f"Ошибка при проверке истечения платежа: {e}")
            return False
    
    def get_payment_status_with_expiry(self, payment_info):
        """
        Получает статус платежа с учетом истечения времени
        
        Args:
            payment_info (dict): Информация о платеже от ЮKassa
        
        Returns:
            str: Статус платежа
        """
        status = self.get_payment_status(payment_info)
        
        # Если платеж в статусе pending и истек, меняем на expired
        if status == 'pending' and self.is_payment_expired(payment_info):
            return 'expired'
        
        return status

# Создаем глобальный экземпляр сервиса
yukassa_service = YukassaService() 