#!/usr/bin/env python3
"""
Исправление функций обработки webhook'ов Express-Pay для поддержки покупок учителей
"""

def handle_new_payment_notification_fixed(data):
    """Обработка уведомления о поступлении нового платежа (исправленная версия)"""
    try:
        account_no = data.get('AccountNo')
        invoice_no = data.get('InvoiceNo')
        amount = data.get('Amount')
        created = data.get('Created')
        service = data.get('Service')
        
        print(f"Webhook: новый платеж - AccountNo: {account_no}, InvoiceNo: {invoice_no}, Amount: {amount}")
        
        # Ищем покупку в обеих таблицах
        purchase = None
        purchase_type = None
        
        # Сначала пытаемся найти по номеру счёта (InvoiceNo), который мы сохраняем в payment_id
        if invoice_no:
            # Ищем в обычных покупках
            purchase = TicketPurchase.query.filter_by(payment_id=str(invoice_no)).first()
            if purchase:
                purchase_type = 'user'
            else:
                # Ищем в покупках учителей
                purchase = TeacherTicketPurchase.query.filter_by(payment_id=str(invoice_no)).first()
                if purchase:
                    purchase_type = 'teacher'
        
        # Если не нашли по InvoiceNo, пробуем по AccountNo (равен purchase.id при создании)
        if not purchase and account_no:
            try:
                # Ищем в обычных покупках
                purchase = TicketPurchase.query.get(int(account_no))
                if purchase:
                    purchase_type = 'user'
                else:
                    # Ищем в покупках учителей
                    purchase = TeacherTicketPurchase.query.get(int(account_no))
                    if purchase:
                        purchase_type = 'teacher'
            except Exception:
                purchase = None
        
        if not purchase:
            print(f"Webhook: покупка не найдена (InvoiceNo={invoice_no}, AccountNo={account_no})")
            return jsonify({'error': 'Purchase not found'}), 404
        
        print(f"Webhook: найдена покупка типа {purchase_type} (ID: {purchase.id})")
        
        # Не начисляем по CmdType=1, т.к. далее придёт CmdType=3 со статусом
        # Обновим статус только если он не установлен
        if not purchase.payment_status:
            purchase.payment_status = 'pending'
        
        db.session.commit()
        print(f"Webhook: платеж успешно обработан (InvoiceNo={invoice_no}, AccountNo={account_no}, тип: {purchase_type})")
        
        return jsonify({'success': True, 'purchase_type': purchase_type}), 200
        
    except Exception as e:
        print(f"Webhook: ошибка обработки нового платежа: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

def handle_payment_cancellation_fixed(data):
    """Обработка уведомления об отмене платежа (исправленная версия)"""
    try:
        account_no = data.get('AccountNo')
        payment_no = data.get('PaymentNo')
        
        print(f"Webhook: отмена платежа - AccountNo: {account_no}, PaymentNo: {payment_no}")
        
        # Ищем покупку в обеих таблицах
        purchase = None
        purchase_type = None
        
        # Ищем в обычных покупках
        purchase = TicketPurchase.query.filter_by(payment_id=str(account_no)).first()
        if purchase:
            purchase_type = 'user'
        else:
            # Ищем в покупках учителей
            purchase = TeacherTicketPurchase.query.filter_by(payment_id=str(account_no)).first()
            if purchase:
                purchase_type = 'teacher'
        
        if not purchase:
            print(f"Webhook: покупка с payment_id {account_no} не найдена")
            return jsonify({'error': 'Purchase not found'}), 404
        
        print(f"Webhook: найдена покупка типа {purchase_type} для отмены (ID: {purchase.id})")
        
        # Обновляем статус платежа
        purchase.payment_status = 'canceled'
        
        db.session.commit()
        print(f"Webhook: платеж {account_no} отменен (тип: {purchase_type})")
        
        return jsonify({'success': True, 'purchase_type': purchase_type}), 200
        
    except Exception as e:
        print(f"Webhook: ошибка обработки отмены платежа: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

def handle_status_change_notification_fixed(data):
    """Обработка уведомления об изменении статуса счета (исправленная версия)"""
    try:
        status = data.get('Status')
        account_no = data.get('AccountNo')
        invoice_no = data.get('InvoiceNo')
        amount = data.get('Amount')
        created = data.get('Created')
        
        print(f"Webhook: изменение статуса - AccountNo: {account_no}, InvoiceNo: {invoice_no}, Status: {status}")
        
        # Ищем покупку в обеих таблицах
        purchase = None
        purchase_type = None
        
        # Находим покупку по номеру счета (InvoiceNo)
        if invoice_no:
            # Ищем в обычных покупках
            purchase = TicketPurchase.query.filter_by(payment_id=str(invoice_no)).first()
            if purchase:
                purchase_type = 'user'
            else:
                # Ищем в покупках учителей
                purchase = TeacherTicketPurchase.query.filter_by(payment_id=str(invoice_no)).first()
                if purchase:
                    purchase_type = 'teacher'
        
        if not purchase:
            print(f"Webhook: покупка с payment_id {invoice_no} не найдена")
            return jsonify({'error': 'Purchase not found'}), 404
        
        print(f"Webhook: найдена покупка типа {purchase_type} для изменения статуса (ID: {purchase.id})")
        
        # Определяем новый статус на основе кода статуса
        old_status = purchase.payment_status
        new_status = None
        
        if status == 1:
            new_status = 'pending'  # Ожидает оплату
        elif status == 2:
            new_status = 'expired'  # Просрочен
        elif status == 3 or status == 6:
            new_status = 'succeeded'  # Оплачен или Оплачен с помощью банковской карты
        elif status == 4:
            new_status = 'partial'  # Оплачен частично
        elif status == 5:
            new_status = 'canceled'  # Отменен
        elif status == 7:
            new_status = 'refunded'  # Платеж возвращен
        else:
            print(f"Webhook: неизвестный статус: {status}")
            new_status = 'unknown'
        
        # Обновляем статус платежа
        purchase.payment_status = new_status
        
        # Если статус изменился на "оплачен" и ранее не был оплачен, начисляем жетоны
        if new_status == 'succeeded' and old_status != 'succeeded' and not purchase.payment_confirmed_at:
            if purchase_type == 'user':
                user = User.query.get(purchase.user_id)
                if user:
                    user.tickets += purchase.quantity
                    purchase.payment_confirmed_at = datetime.now()
                    print(f"Webhook: начислено {purchase.quantity} жетонов пользователю {user.id}")
            elif purchase_type == 'teacher':
                teacher = Teacher.query.get(purchase.teacher_id)
                if teacher:
                    teacher.tickets += purchase.quantity
                    purchase.payment_confirmed_at = datetime.now()
                    print(f"Webhook: начислено {purchase.quantity} жетонов учителю {teacher.id}")
        
        db.session.commit()
        print(f"Webhook: статус платежа {invoice_no} обновлен с {old_status} на {new_status} (тип: {purchase_type})")
        
        return jsonify({'success': True, 'purchase_type': purchase_type}), 200
        
    except Exception as e:
        print(f"Webhook: ошибка обработки изменения статуса: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

# Импорты для использования в app.py
"""
from app import TicketPurchase, TeacherTicketPurchase, User, Teacher, db
from datetime import datetime
from flask import jsonify
"""

if __name__ == "__main__":
    print("🔧 Исправленные функции обработки webhook'ов Express-Pay")
    print("=" * 60)
    print()
    print("📝 Что исправлено:")
    print("1. Добавлена поддержка поиска покупок в таблице TeacherTicketPurchase")
    print("2. Добавлено логирование типа найденной покупки (user/teacher)")
    print("3. Исправлена логика начисления жетонов для учителей")
    print("4. Улучшена обработка ошибок и логирование")
    print()
    print("🔧 Как применить исправления:")
    print("1. Замените функции в app.py на исправленные версии")
    print("2. Добавьте необходимые импорты")
    print("3. Перезапустите приложение")
    print("4. Протестируйте webhook'и с покупками учителей")
