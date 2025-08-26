#!/usr/bin/env python3
"""
Улучшенная обработка webhook'ов ЮKassa согласно официальной документации
https://yookassa.ru/developers/using-api/webhooks
"""

import os
import hmac
import hashlib
import json
from datetime import datetime
from flask import request, jsonify
from yukassa_service import yukassa_service

def verify_yukassa_webhook_signature(body, signature, webhook_secret):
    """
    Проверяет подпись webhook'а от ЮKassa согласно документации
    
    Args:
        body (str): Тело запроса в виде строки
        signature (str): Подпись из заголовка X-YooKassa-Signature
        webhook_secret (str): Секретный ключ для проверки подписи
    
    Returns:
        bool: True если подпись верна
    """
    try:
        if not webhook_secret:
            print("⚠️  Webhook secret не настроен, пропускаем проверку подписи")
            return True
        
        # Вычисляем HMAC-SHA256 подпись
        expected_signature = hmac.new(
            webhook_secret.encode('utf-8'),
            body.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Безопасное сравнение подписей
        return hmac.compare_digest(signature, expected_signature)
        
    except Exception as e:
        print(f"❌ Ошибка при проверке подписи: {e}")
        return False

def process_yukassa_webhook(webhook_token):
    """
    Обработка webhook'ов от ЮKassa согласно официальной документации
    
    Args:
        webhook_token (str): Токен из URL для проверки безопасности
    
    Returns:
        tuple: (response_data, status_code)
    """
    # 1. Проверка токена безопасности
    expected_token = os.environ.get('YUKASSA_WEBHOOK_TOKEN')
    if webhook_token != expected_token:
        print(f"❌ Неверный webhook токен. Ожидалось: {expected_token}, получено: {webhook_token}")
        return jsonify({'error': 'Invalid webhook token'}), 403
    
    try:
        # 2. Получение тела запроса
        body = request.get_data(as_text=True)
        if not body:
            print("❌ Пустое тело webhook'а")
            return jsonify({'error': 'Empty request body'}), 400
        
        # 3. Проверка подписи отключена (по требованию)
        print("ℹ️  Проверка подписи отключена")
        
        # 4. Парсинг JSON данных
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            print(f"❌ Ошибка парсинга JSON: {e}")
            return jsonify({'error': 'Invalid JSON'}), 400
        
        # 5. Валидация структуры данных согласно документации
        if not isinstance(data, dict):
            print("❌ Данные webhook'а должны быть объектом")
            return jsonify({'error': 'Invalid data structure'}), 400
        
        # Проверяем обязательные поля
        event_type = data.get('event')
        object_data = data.get('object')
        
        if not event_type:
            print("❌ Отсутствует поле 'event' в webhook'е")
            return jsonify({'error': 'Missing event field'}), 400
        
        if not object_data or not isinstance(object_data, dict):
            print("❌ Отсутствует или неверный формат поля 'object'")
            return jsonify({'error': 'Missing or invalid object field'}), 400
        
        # 6. Логирование входящего webhook'а
        print(f"📨 Получен webhook от ЮKassa:")
        print(f"   - Событие: {event_type}")
        print(f"   - ID объекта: {object_data.get('id')}")
        print(f"   - Статус: {object_data.get('status')}")
        print(f"   - Сумма: {object_data.get('amount', {}).get('value')} {object_data.get('amount', {}).get('currency')}")
        
        # Логируем метаданные, если они есть
        metadata = object_data.get('metadata', {})
        if metadata:
            print(f"   - Метаданные: {metadata}")
            user_id = metadata.get('user_id')
            purchase_id = metadata.get('purchase_id')
            if user_id:
                print(f"   - ID пользователя: {user_id}")
            if purchase_id:
                print(f"   - ID покупки: {purchase_id}")
        
        # 7. Обработка различных типов событий
        if event_type == 'payment.succeeded':
            return handle_payment_succeeded(object_data)
        elif event_type == 'payment.canceled':
            return handle_payment_canceled(object_data)
        elif event_type == 'payment.waiting_for_capture':
            return handle_payment_waiting_for_capture(object_data)
        elif event_type == 'payment.failed':
            return handle_payment_failed(object_data)
        elif event_type == 'payment.pending':
            return handle_payment_pending(object_data)
        else:
            print(f"⚠️  Неизвестный тип события: {event_type}")
            return jsonify({'success': True, 'message': 'Event ignored'}), 200
        
    except Exception as e:
        print(f"❌ Ошибка обработки webhook'а: {e}")
        return jsonify({'error': 'Internal server error'}), 500

def handle_payment_succeeded(payment_data):
    """
    Обработка события payment.succeeded
    
    Args:
        payment_data (dict): Данные платежа
    
    Returns:
        tuple: (response_data, status_code)
    """
    payment_id = payment_data.get('id')
    status = payment_data.get('status')
    
    print(f"✅ Платеж {payment_id} успешно завершен")
    
    # Проверяем, что статус действительно succeeded
    if status != 'succeeded':
        print(f"⚠️  Неожиданный статус для события payment.succeeded: {status}")
        return jsonify({'error': 'Unexpected status'}), 400
    
    # Получаем актуальную информацию о платеже
    try:
        payment_info = yukassa_service.get_payment_info(payment_id)
    except Exception as e:
        print(f"❌ Ошибка получения информации о платеже: {e}")
        return jsonify({'error': 'Failed to get payment info'}), 500
    
    # Находим покупку в базе данных (проверяем как обычные покупки, так и покупки учителей)
    from app import TicketPurchase, TeacherTicketPurchase, User, Teacher, db
    
    # Сначала ищем в обычных покупках
    purchase = TicketPurchase.query.filter_by(payment_id=payment_id).first()
    purchase_type = 'user'
    
    # Если не найдено, ищем в покупках учителей
    if not purchase:
        purchase = TeacherTicketPurchase.query.filter_by(payment_id=payment_id).first()
        purchase_type = 'teacher'
    
    if not purchase:
        print(f"❌ Покупка с payment_id {payment_id} не найдена")
        return jsonify({'error': 'Purchase not found'}), 404
    
    # Дополнительная проверка через метаданные
    metadata = payment_data.get('metadata', {})
    if metadata:
        expected_user_id = metadata.get('user_id')
        expected_teacher_id = metadata.get('teacher_id')
        expected_purchase_id = metadata.get('purchase_id')
        
        if purchase_type == 'user' and expected_user_id and str(purchase.user_id) != expected_user_id:
            print(f"⚠️  Несоответствие ID пользователя: ожидалось {expected_user_id}, найдено {purchase.user_id}")
        elif purchase_type == 'teacher' and expected_teacher_id and str(purchase.teacher_id) != expected_teacher_id:
            print(f"⚠️  Несоответствие ID учителя: ожидалось {expected_teacher_id}, найдено {purchase.teacher_id}")
        
        if expected_purchase_id and str(purchase.id) != expected_purchase_id:
            print(f"⚠️  Несоответствие ID покупки: ожидалось {expected_purchase_id}, найдено {purchase.id}")
    
    # Проверяем, не был ли уже обработан этот платеж
    if purchase.payment_status == 'succeeded':
        print(f"⚠️  Платеж {payment_id} уже был обработан")
        return jsonify({'success': True, 'message': 'Payment already processed'}), 200
    
    # Начисляем жетоны пользователю или учителю
    if purchase_type == 'user':
        user = User.query.get(purchase.user_id)
        if user:
            old_tickets = user.tickets
            user.tickets += purchase.quantity
            purchase.payment_status = 'succeeded'
            purchase.payment_confirmed_at = datetime.now()
            
            db.session.commit()
            
            print(f"💰 Начислено {purchase.quantity} жетонов пользователю {user.id}")
            print(f"   - Было: {old_tickets}, стало: {user.tickets}")
            
            return jsonify({
                'success': True,
                'message': 'Payment processed successfully',
                'tickets_added': purchase.quantity,
                'user_id': user.id,
                'purchase_type': 'user'
            }), 200
        else:
            print(f"❌ Пользователь {purchase.user_id} не найден")
            return jsonify({'error': 'User not found'}), 404
    else:  # purchase_type == 'teacher'
        teacher = Teacher.query.get(purchase.teacher_id)
        if teacher:
            old_tickets = teacher.tickets
            teacher.tickets += purchase.quantity
            purchase.payment_status = 'succeeded'
            purchase.payment_confirmed_at = datetime.now()
            
            db.session.commit()
            
            print(f"💰 Начислено {purchase.quantity} жетонов учителю {teacher.id}")
            print(f"   - Было: {old_tickets}, стало: {teacher.tickets}")
            
            return jsonify({
                'success': True,
                'message': 'Payment processed successfully',
                'tickets_added': purchase.quantity,
                'teacher_id': teacher.id,
                'purchase_type': 'teacher'
            }), 200
        else:
            print(f"❌ Учитель {purchase.teacher_id} не найден")
            return jsonify({'error': 'Teacher not found'}), 404

def handle_payment_canceled(payment_data):
    """
    Обработка события payment.canceled
    
    Args:
        payment_data (dict): Данные платежа
    
    Returns:
        tuple: (response_data, status_code)
    """
    payment_id = payment_data.get('id')
    print(f"❌ Платеж {payment_id} отменен")
    
    # Обновляем статус в базе данных (проверяем как обычные покупки, так и покупки учителей)
    from app import TicketPurchase, TeacherTicketPurchase, db
    
    # Сначала ищем в обычных покупках
    purchase = TicketPurchase.query.filter_by(payment_id=payment_id).first()
    
    # Если не найдено, ищем в покупках учителей
    if not purchase:
        purchase = TeacherTicketPurchase.query.filter_by(payment_id=payment_id).first()
    
    if purchase:
        purchase.payment_status = 'canceled'
        db.session.commit()
        print(f"📝 Статус платежа {payment_id} обновлен на 'canceled'")
    
    return jsonify({'success': True, 'message': 'Payment canceled'}), 200

def handle_payment_waiting_for_capture(payment_data):
    """
    Обработка события payment.waiting_for_capture
    
    Args:
        payment_data (dict): Данные платежа
    
    Returns:
        tuple: (response_data, status_code)
    """
    payment_id = payment_data.get('id')
    print(f"⏳ Платеж {payment_id} ожидает подтверждения")
    
    # Обновляем статус в базе данных (проверяем как обычные покупки, так и покупки учителей)
    from app import TicketPurchase, TeacherTicketPurchase, db
    
    # Сначала ищем в обычных покупках
    purchase = TicketPurchase.query.filter_by(payment_id=payment_id).first()
    
    # Если не найдено, ищем в покупках учителей
    if not purchase:
        purchase = TeacherTicketPurchase.query.filter_by(payment_id=payment_id).first()
    
    if purchase:
        purchase.payment_status = 'waiting_for_capture'
        db.session.commit()
        print(f"📝 Статус платежа {payment_id} обновлен на 'waiting_for_capture'")
    
    return jsonify({'success': True, 'message': 'Payment waiting for capture'}), 200

def handle_payment_failed(payment_data):
    """
    Обработка события payment.failed
    
    Args:
        payment_data (dict): Данные платежа
    
    Returns:
        tuple: (response_data, status_code)
    """
    payment_id = payment_data.get('id')
    print(f"💥 Платеж {payment_id} завершился с ошибкой")
    
    # Обновляем статус в базе данных (проверяем как обычные покупки, так и покупки учителей)
    from app import TicketPurchase, TeacherTicketPurchase, db
    
    # Сначала ищем в обычных покупках
    purchase = TicketPurchase.query.filter_by(payment_id=payment_id).first()
    
    # Если не найдено, ищем в покупках учителей
    if not purchase:
        purchase = TeacherTicketPurchase.query.filter_by(payment_id=payment_id).first()
    
    if purchase:
        purchase.payment_status = 'failed'
        db.session.commit()
        print(f"📝 Статус платежа {payment_id} обновлен на 'failed'")
    
    return jsonify({'success': True, 'message': 'Payment failed'}), 200

def handle_payment_pending(payment_data):
    """
    Обработка события payment.pending
    
    Args:
        payment_data (dict): Данные платежа
    
    Returns:
        tuple: (response_data, status_code)
    """
    payment_id = payment_data.get('id')
    print(f"⏰ Платеж {payment_id} ожидает оплаты")
    
    # Обновляем статус в базе данных (проверяем как обычные покупки, так и покупки учителей)
    from app import TicketPurchase, TeacherTicketPurchase, db
    
    # Сначала ищем в обычных покупках
    purchase = TicketPurchase.query.filter_by(payment_id=payment_id).first()
    
    # Если не найдено, ищем в покупках учителей
    if not purchase:
        purchase = TeacherTicketPurchase.query.filter_by(payment_id=payment_id).first()
    
    if purchase:
        purchase.payment_status = 'pending'
        db.session.commit()
        print(f"📝 Статус платежа {payment_id} обновлен на 'pending'")
    
    return jsonify({'success': True, 'message': 'Payment pending'}), 200

# Пример использования в Flask приложении:
"""
@app.route('/webhook/yukassa/<webhook_token>', methods=['POST'])
def yukassa_webhook(webhook_token):
    return process_yukassa_webhook(webhook_token)
"""
