import requests
import hashlib
import hmac
import json
import urllib.parse
from datetime import datetime
from typing import Dict, Any, Optional

class ExpressPayService:
    """
    Сервис для интеграции с ExpressPay.by API
    Документация: https://express-pay.by/docs/api/v1
    """
    
    def __init__(self, api_token: str, secret_word: str, test_mode: bool = True):
        """
        Инициализация сервиса ExpressPay.by
        
        Args:
            api_token: API-ключ (токен) доступа к серверу
            secret_word: Секретное слово для формирования цифровой подписи
            test_mode: Режим тестирования (True для тестов, False для продакшена)
        """
        self.api_token = api_token
        self.secret_word = secret_word
        self.test_mode = test_mode
        
        # URL для API
        if test_mode:
            self.base_url = "https://sandbox-api.express-pay.by"
        else:
            self.base_url = "https://api.express-pay.by"
    
    def _generate_signature(self, params: Dict[str, Any]) -> str:
        """
        Генерация цифровой подписи алгоритмом HMAC-SHA1
        
        Args:
            params: Параметры запроса
            
        Returns:
            Подпись в формате HMAC-SHA1
        """
        # Сортируем параметры по ключам
        sorted_params = dict(sorted(params.items()))
        
        # Формируем строку для подписи
        sign_string = ""
        for key, value in sorted_params.items():
            if key != "signature" and value is not None:
                sign_string += f"{key}={value}&"
        
        # Убираем последний символ "&"
        if sign_string.endswith("&"):
            sign_string = sign_string[:-1]
        
        # Создаем HMAC-SHA1 подпись
        signature = hmac.new(
            self.secret_word.encode('utf-8'),
            sign_string.encode('utf-8'),
            hashlib.sha1
        ).hexdigest()
        
        return signature
    
    def _make_request(self, endpoint: str, params: Dict[str, Any], method: str = "GET") -> Dict[str, Any]:
        """
        Выполнение HTTP-запроса к API
        
        Args:
            endpoint: Конечная точка API
            params: Параметры запроса
            method: HTTP метод (GET или POST)
            
        Returns:
            Ответ от API
        """
        # Добавляем обязательные параметры
        params.update({
            "version": "1.0",
            "token": self.api_token
        })
        
        # Генерируем подпись
        params["signature"] = self._generate_signature(params)
        
        try:
            # Логируем запрос в тестовом режиме
            if self.test_mode:
                print(f"🧪 Тестовый режим ExpressPay.by")
                print(f"Метод: {method}")
                print(f"URL: {self.base_url}/{endpoint}")
                print(f"Параметры: {params}")
            
            if method.upper() == "POST":
                # Для POST-запросов отправляем данные в теле запроса
                response = requests.post(
                    f"{self.base_url}/{endpoint}",
                    json=params,
                    headers={"Content-Type": "application/json"}
                )
            else:
                # Для GET-запросов отправляем параметры в URL
                encoded_params = urllib.parse.urlencode(params)
                url = f"{self.base_url}/{endpoint}?{encoded_params}"
                response = requests.get(url)
            
            if response.status_code == 200:
                result = response.json()
                
                # Логируем ответ в тестовом режиме
                if self.test_mode:
                    print(f"Ответ: {result}")
                
                # Проверяем наличие ошибки
                if "Error" in result:
                    return {
                        "success": False,
                        "error": result["Error"]["Msg"],
                        "error_code": result["Error"]["Code"]
                    }
                
                return {
                    "success": True,
                    "data": result
                }
            else:
                error_text = f"HTTP ошибка: {response.status_code}"
                try:
                    error_data = response.json()
                    if "Error" in error_data:
                        error_text += f" - {error_data['Error']['Msg']}"
                except:
                    error_text += f" - {response.text}"
                
                return {
                    "success": False,
                    "error": error_text
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"Ошибка запроса: {str(e)}"
            }
    
    def create_card_invoice(self, 
                           account_no: str,
                           amount: float, 
                           currency: str = "933",  # 933 = BYN
                           expiration: str = None,
                           info: str = "",
                           return_url: str = "",
                           fail_url: str = "",
                           return_type: str = "json") -> Dict[str, Any]:
        """
        Выставление счета по карте (интернет-эквайринг)
        
        Args:
            account_no: Номер лицевого счета
            amount: Сумма платежа (в копейках для BYN)
            currency: Код валюты (933=BYN, 978=EUR, 840=USD, 643=RUB)
            expiration: Дата истечения счета (YYYYMMDDHHMMSS)
            info: Информация о платеже
            return_url: URL для возврата после успешной оплаты
            fail_url: URL для возврата при ошибке
            return_type: Тип возврата (json, xml, redirect)
            
        Returns:
            Словарь с данными платежа
        """
        if expiration is None:
            # По умолчанию 1 час
            expiration = (datetime.now().timestamp() + 3600)
            expiration = datetime.fromtimestamp(expiration).strftime('%Y%m%d%H%M%S')
        
        # Конвертируем сумму в копейки для BYN
        if currency == "933":  # BYN
            amount_cents = int(amount * 100)
        else:
            amount_cents = int(amount)
        
        params = {
            "accountNo": account_no,
            "amount": str(amount_cents),
            "currency": currency,
            "expiration": expiration,
            "info": info,
            "returnUrl": return_url,
            "failUrl": fail_url,
            "returnType": return_type
        }
        
        # Убираем пустые параметры
        params = {k: v for k, v in params.items() if v}
        
        result = self._make_request("v1/web_cardinvoices", params, method="POST")
        
        print(f"🔧 ExpressPay.by create_card_invoice результат:")
        print(f"   Успех: {result.get('success')}")
        print(f"   Данные: {result}")
        
        if result["success"]:
            data = result["data"]
            payment_id = data.get("InvoiceNo")
            payment_url = data.get("FormUrl")
            
            print(f"🔧 Извлеченные данные:")
            print(f"   InvoiceNo: {payment_id}")
            print(f"   FormUrl: {payment_url}")
            
            return {
                "success": True,
                "payment_id": payment_id,
                "payment_url": payment_url,
                "account_no": account_no,
                "amount": amount,
                "currency": currency
            }
        else:
            print(f"❌ Ошибка ExpressPay.by: {result.get('error')}")
            return result
    
    def get_card_invoice_status(self, invoice_no: str) -> Dict[str, Any]:
        """
        Получение статуса счета по карте
        
        Args:
            invoice_no: Номер счета
            
        Returns:
            Словарь со статусом платежа
        """
        params = {
            "invoiceNo": invoice_no
        }
        
        result = self._make_request("v1/web_cardinvoices/status", params, method="GET")
        
        if result["success"]:
            data = result["data"]
            status = data.get("Status")
            return {
                "success": True,
                "status": status,
                "status_description": self._get_status_description(status),
                "amount": data.get("Amount"),
                "currency": data.get("Currency"),
                "account_no": data.get("AccountNo")
            }
        else:
            return result
    
    def cancel_card_invoice(self, invoice_no: str) -> Dict[str, Any]:
        """
        Отмена счета по карте
        
        Args:
            invoice_no: Номер счета
            
        Returns:
            Результат отмены
        """
        params = {
            "invoiceNo": invoice_no
        }
        
        result = self._make_request("v1/web_cardinvoices/cancel", params, method="POST")
        return result
    
    def _get_status_description(self, status: str) -> str:
        """
        Получение описания статуса платежа
        
        Args:
            status: Код статуса
            
        Returns:
            Описание статуса
        """
        status_descriptions = {
            "100": "Счет зарегистрирован, но не оплачен",
            "101": "Предавторизованная сумма захолдирована",
            "102": "Проведена полная авторизация суммы счета",
            "103": "Авторизация отменена",
            "104": "По транзакции была проведена операция возврата",
            "105": "Инициирована авторизация через ACS банка-эмитента",
            "106": "Авторизация отклонена"
        }
        
        return status_descriptions.get(status, "Неизвестный статус")
    
    def verify_webhook_signature(self, data: Dict[str, Any], signature: str) -> bool:
        """
        Проверка подписи webhook'а от ExpressPay.by
        
        Args:
            data: Данные webhook'а
            signature: Подпись из заголовка
            
        Returns:
            True если подпись верна, False иначе
        """
        expected_signature = self._generate_signature(data)
        return signature.lower() == expected_signature.lower()

# Создаем экземпляр сервиса для тестового режима
# Тестовые данные из документации ExpressPay.by
expresspay_service = ExpressPayService(
    api_token="a75b74cbcfe446509e8ee874f421bd66",  # Тестовый API ключ
    secret_word="test_secret_word",                 # Тестовое секретное слово
    test_mode=True                                  # Тестовый режим
) 