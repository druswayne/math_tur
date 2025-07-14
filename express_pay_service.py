#!/usr/bin/env python3
"""
Сервис для работы с Express-Pay API
Документация: https://express-pay.by/docs/api/v1
"""

import requests
import json
import uuid
import os
from datetime import datetime, timedelta
import logging
from dotenv import load_dotenv
load_dotenv()
class ExpressPayService:
    """Сервис для работы с Express-Pay API"""
    
    def __init__(self):
        # Получаем данные из переменных окружения
        self.service_number = os.environ.get('EXPRESS_PAY_SERVICE_NUMBER')
        self.service_provider_code = os.environ.get('EXPRESS_PAY_SERVICE_PROVIDER_CODE')
        self.api_token = os.environ.get('EXPRESS_PAY_API_TOKEN')
        self.service_code = os.environ.get('EXPRESS_PAY_SERVICE_CODE')
        self.base_url = "https://api.express-pay.by/v1"
        self.logger = logging.getLogger(__name__)
        print(self.api_token)
        # Проверяем наличие всех необходимых переменных
        if not all([self.service_number, self.service_provider_code, self.api_token, 
                   self.service_code]):
            self.logger.error("Не все переменные окружения для Express-Pay настроены")
    

    
    def create_payment(self, amount, order_id, description, return_url, payment_method='epos'):
        """
        Создает платеж в Express-Pay
        
        Args:
            amount (float): Сумма в BYN
            order_id (str): Уникальный ID заказа
            description (str): Описание платежа
            return_url (str): URL для возврата после оплаты
            payment_method (str): Способ оплаты ('epos' или 'erip')
        
        Returns:
            dict: Ответ от Express-Pay с данными платежа
            
        Note:
            Время жизни платежа: 10 минут
        """
        try:
            # Формируем дату истечения (10 минут от текущего времени)
            expiration = (datetime.now() + timedelta(minutes=10)).strftime("%Y%m%d%H%M")
            
            # Формируем данные для запроса согласно документации
            payment_data = {
                "AccountNo": str(order_id),
                "Amount": str(amount).replace('.', ','),  # Заменяем точку на запятую
                "Currency": "933",  # Код валюты BYN
                "Expiration": expiration,
                "Info": description,
                "Surname": "",
                "FirstName": "",
                "Patronymic": "",
                "City": "",
                "Street": "",
                "House": "",
                "Building": "",
                "Apartment": "",
                "IsNameEditable": "0",
                "IsAddressEditable": "0",
                "IsAmountEditable": "0",
                "EmailNotification": "",
                "SmsPhone": "",
                "ReturnInvoiceUrl": "1"  # Возвращать публичную ссылку на счет
            }
            

            
            # Отправляем запрос как form-data с токеном в URL
            response = requests.post(
                f"{self.base_url}/invoices?token={self.api_token}",
                data=payment_data,
                timeout=30
            )
            
            response.raise_for_status()
            payment_info = response.json()
            
            # Проверяем наличие ошибки в ответе
            if 'Error' in payment_info:
                error = payment_info['Error']
                raise Exception(f"Express-Pay ошибка: {error.get('Msg', 'Неизвестная ошибка')} (код: {error.get('Code', 'N/A')})")
            
            self.logger.info(f"Создан платеж Express-Pay: {payment_info.get('InvoiceNo')}")
            return payment_info
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Ошибка при создании платежа Express-Pay: {e}")
            raise Exception(f"Ошибка при создании платежа: {str(e)}")
    
    def get_payment_info(self, invoice_no):
        """
        Получает информацию о платеже
        
        Args:
            invoice_no (str): Номер счета в Express-Pay
        
        Returns:
            dict: Информация о платеже
        """
        try:
            # Формируем URL для получения информации о счете
            url = f"{self.base_url}/invoices?token={self.api_token}&InvoiceNo={invoice_no}"
            
            # Отправляем GET запрос
            response = requests.get(url, timeout=30)
            
            response.raise_for_status()
            result = response.json()
            
            # Проверяем наличие ошибки в ответе
            if 'Error' in result:
                error = result['Error']
                raise Exception(f"Express-Pay ошибка: {error.get('Msg', 'Неизвестная ошибка')} (код: {error.get('Code', 'N/A')})")
            
            # Возвращаем первый счет из списка (если есть)
            if 'Items' in result and result['Items']:
                return result['Items'][0]
            else:
                raise Exception("Счет не найден")
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Ошибка при получении информации о платеже {invoice_no}: {e}")
            raise Exception(f"Ошибка при получении информации о платеже: {str(e)}")

    def get_payment_status(self, invoice_no):
        """
        Получает статус платежа через специальный endpoint
        
        Args:
            invoice_no (str): Номер счета в Express-Pay
        
        Returns:
            dict: Статус платежа
        """
        # Проверяем, что invoice_no не None и не пустой
        if not invoice_no or invoice_no == 'None' or invoice_no == 'null':
            raise Exception("Номер счета не может быть пустым или None")
        
        # Если invoice_no является словарем, извлекаем номер счета
        if isinstance(invoice_no, dict):
            invoice_no = invoice_no.get('InvoiceNo')
            if not invoice_no:
                raise Exception("В данных платежа отсутствует номер счета (InvoiceNo)")
            
        try:
            # Формируем URL для получения статуса счета согласно документации
            url = f"{self.base_url}/invoices/{invoice_no}/status?token={self.api_token}"
            
            # Отправляем GET запрос
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            # Проверяем наличие ошибки в ответе
            if 'Error' in result:
                error = result['Error']
                raise Exception(f"Express-Pay ошибка: {error.get('Msg', 'Неизвестная ошибка')} (код: {error.get('Code', 'N/A')})")
            
            self.logger.info(f"Получен статус платежа {invoice_no}: {result.get('Status')}")
            return result
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Ошибка при получении статуса платежа {invoice_no}: {e}")
            raise Exception(f"Ошибка при получении статуса платежа: {str(e)}")
    
    def parse_payment_status(self, status_code):
        """
        Парсит статус платежа из числового кода Express-Pay
        
        Args:
            status_code (int): Код статуса от Express-Pay
        
        Returns:
            str: Статус платежа
        """
        # Маппинг статусов Express-Pay на наши статусы согласно документации
        status_mapping = {
            1: 'pending',      # Ожидает оплату
            2: 'expired',      # Просрочен
            3: 'succeeded',    # Оплачен
            4: 'partial',      # Оплачен частично
            5: 'canceled',     # Отменен
            6: 'succeeded',    # Оплачен с помощью банковской карты
            7: 'refunded'      # Платеж возвращен
        }
        
        return status_mapping.get(status_code, 'unknown')
    
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
            payment_info (dict): Информация о платеже от Express-Pay
        
        Returns:
            bool: True если платеж истек
        """
        try:
            # Получаем время истечения
            expiration_str = payment_info.get('Expiration')
            if not expiration_str:
                return False
            
            # Парсим время истечения согласно формату документации
            # Форматы: yyyyMMdd, yyyyMMddHHmm
            if len(expiration_str) == 8:  # yyyyMMdd
                expiration_time = datetime.strptime(expiration_str, "%Y%m%d")
            elif len(expiration_str) == 12:  # yyyyMMddHHmm
                expiration_time = datetime.strptime(expiration_str, "%Y%m%d%H%M")
            else:
                # Попробуем другие форматы
                try:
                    expiration_time = datetime.strptime(expiration_str, "%Y-%m-%d %H:%M:%S")
                except:
                    return False
            
            current_time = datetime.now()
            
            return current_time > expiration_time
            
        except Exception as e:
            self.logger.error(f"Ошибка при проверке истечения платежа: {e}")
            return False
    
    def get_payment_status_with_expiry(self, payment_info):
        """
        Получает статус платежа с учетом истечения времени
        
        Args:
            payment_info (dict): Информация о платеже от Express-Pay
        
        Returns:
            str: Статус платежа
        """
        status_code = payment_info.get('Status')
        status = self.parse_payment_status(status_code)
        
        # Если платеж в статусе pending и истек, меняем на expired
        if status == 'pending' and self.is_payment_expired(payment_info):
            return 'expired'
        
        return status

# Создаем экземпляр сервиса
express_pay_service = ExpressPayService() 