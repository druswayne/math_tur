#!/usr/bin/env python3
"""
Мониторинг использования памяти Flask-Limiter в реальном времени
"""

import os
import sys
import time
import psutil
import gc
import threading
from datetime import datetime, timedelta
from flask import Flask, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import json

class RateLimiterMonitor:
    """Мониторинг использования памяти Flask-Limiter"""
    
    def __init__(self, app, limiter):
        self.app = app
        self.limiter = limiter
        self.monitoring = False
        self.metrics = {
            'memory_usage': [],
            'unique_ips': [],
            'requests_per_second': [],
            'rate_limit_exceeded': 0,
            'start_time': datetime.now()
        }
        
    def start_monitoring(self, interval=5):
        """Запускает мониторинг"""
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, args=(interval,), daemon=True)
        self.monitor_thread.start()
        print(f"🔍 Мониторинг запущен (интервал: {interval} сек)")
        
    def stop_monitoring(self):
        """Останавливает мониторинг"""
        self.monitoring = False
        print("⏹️ Мониторинг остановлен")
        
    def _monitor_loop(self, interval):
        """Основной цикл мониторинга"""
        while self.monitoring:
            try:
                self._collect_metrics()
                time.sleep(interval)
            except Exception as e:
                print(f"❌ Ошибка мониторинга: {e}")
                
    def _collect_metrics(self):
        """Собирает метрики"""
        # Использование памяти
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024
        
        # Количество уникальных IP (если доступно)
        unique_ips = self._get_unique_ips_count()
        
        # Запросы в секунду (примерно)
        requests_per_second = self._get_requests_per_second()
        
        # Сохраняем метрики
        timestamp = datetime.now()
        self.metrics['memory_usage'].append({
            'timestamp': timestamp.isoformat(),
            'memory_mb': memory_mb
        })
        
        if unique_ips is not None:
            self.metrics['unique_ips'].append({
                'timestamp': timestamp.isoformat(),
                'count': unique_ips
            })
            
        self.metrics['requests_per_second'].append({
            'timestamp': timestamp.isoformat(),
            'rps': requests_per_second
        })
        
        # Проверяем пороги
        self._check_thresholds(memory_mb, unique_ips)
        
        # Ограничиваем размер истории (храним последние 1000 записей)
        for key in ['memory_usage', 'unique_ips', 'requests_per_second']:
            if len(self.metrics[key]) > 1000:
                self.metrics[key] = self.metrics[key][-1000:]
                
    def _get_unique_ips_count(self):
        """Получает количество уникальных IP (если возможно)"""
        try:
            # Попытка получить доступ к storage
            if hasattr(self.limiter, 'storage') and hasattr(self.limiter.storage, 'storage'):
                return len(self.limiter.storage.storage)
        except:
            pass
        return None
        
    def _get_requests_per_second(self):
        """Получает примерное количество запросов в секунду"""
        # Простая реализация - можно улучшить
        return len(self.metrics['requests_per_second']) / max(1, (datetime.now() - self.metrics['start_time']).total_seconds())
        
    def _check_thresholds(self, memory_mb, unique_ips):
        """Проверяет пороги и выдает предупреждения"""
        warnings = []
        
        if memory_mb > 500:
            warnings.append(f"💥 КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ: Память {memory_mb:.2f} МБ > 500 МБ")
        elif memory_mb > 100:
            warnings.append(f"⚠️ ПРЕДУПРЕЖДЕНИЕ: Память {memory_mb:.2f} МБ > 100 МБ")
            
        if unique_ips and unique_ips > 50000:
            warnings.append(f"💥 КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ: Уникальных IP {unique_ips:,} > 50,000")
        elif unique_ips and unique_ips > 10000:
            warnings.append(f"⚠️ ПРЕДУПРЕЖДЕНИЕ: Уникальных IP {unique_ips:,} > 10,000")
            
        for warning in warnings:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {warning}")
            
    def get_current_stats(self):
        """Получает текущую статистику"""
        if not self.metrics['memory_usage']:
            return None
            
        latest_memory = self.metrics['memory_usage'][-1]
        latest_ips = self.metrics['unique_ips'][-1] if self.metrics['unique_ips'] else None
        latest_rps = self.metrics['requests_per_second'][-1] if self.metrics['requests_per_second'] else None
        
        # Вычисляем тренды
        memory_trend = self._calculate_trend('memory_usage', 'memory_mb')
        ips_trend = self._calculate_trend('unique_ips', 'count') if self.metrics['unique_ips'] else None
        
        return {
            'current_memory_mb': latest_memory['memory_mb'],
            'memory_trend': memory_trend,
            'unique_ips': latest_ips['count'] if latest_ips else None,
            'ips_trend': ips_trend,
            'requests_per_second': latest_rps['rps'] if latest_rps else None,
            'rate_limit_exceeded': self.metrics['rate_limit_exceeded'],
            'uptime_seconds': (datetime.now() - self.metrics['start_time']).total_seconds()
        }
        
    def _calculate_trend(self, metric_key, value_key):
        """Вычисляет тренд метрики"""
        if len(self.metrics[metric_key]) < 2:
            return 0
            
        recent = self.metrics[metric_key][-10:]  # Последние 10 значений
        if len(recent) < 2:
            return 0
            
        first_value = recent[0][value_key]
        last_value = recent[-1][value_key]
        
        if first_value == 0:
            return 0
            
        return ((last_value - first_value) / first_value) * 100
        
    def print_current_stats(self):
        """Выводит текущую статистику"""
        stats = self.get_current_stats()
        if not stats:
            print("📊 Статистика недоступна")
            return
            
        print("\n" + "="*60)
        print("📊 ТЕКУЩАЯ СТАТИСТИКА RATE LIMITER")
        print("="*60)
        print(f"💾 Использование памяти: {stats['current_memory_mb']:.2f} МБ")
        
        if stats['memory_trend'] is not None:
            trend_icon = "📈" if stats['memory_trend'] > 0 else "📉" if stats['memory_trend'] < 0 else "➡️"
            print(f"   {trend_icon} Тренд памяти: {stats['memory_trend']:+.2f}%")
            
        if stats['unique_ips'] is not None:
            print(f"🌐 Уникальных IP: {stats['unique_ips']:,}")
            
        if stats['ips_trend'] is not None:
            trend_icon = "📈" if stats['ips_trend'] > 0 else "📉" if stats['ips_trend'] < 0 else "➡️"
            print(f"   {trend_icon} Тренд IP: {stats['ips_trend']:+.2f}%")
            
        if stats['requests_per_second'] is not None:
            print(f"🚀 Запросов/сек: {stats['requests_per_second']:.2f}")
            
        print(f"🚫 Rate limit exceeded: {stats['rate_limit_exceeded']}")
        print(f"⏱️ Время работы: {stats['uptime_seconds']:.0f} сек")
        print("="*60)
        
    def save_metrics_to_file(self, filename=None):
        """Сохраняет метрики в файл"""
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"rate_limiter_metrics_{timestamp}.json"
            
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.metrics, f, indent=2, ensure_ascii=False)
            print(f"💾 Метрики сохранены в {filename}")
        except Exception as e:
            print(f"❌ Ошибка сохранения метрик: {e}")

def create_test_app():
    """Создает тестовое приложение для демонстрации"""
    app = Flask(__name__)
    
    # Настраиваем rate limiter
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["100 per minute"],
        strategy="fixed-window",
        key_prefix="test_rate_limit"
    )
    
    @app.route('/test')
    @limiter.limit("10 per minute")
    def test_endpoint():
        return {"message": "test", "timestamp": datetime.now().isoformat()}
        
    @app.route('/stats')
    def stats_endpoint():
        return {"message": "stats endpoint"}
        
    return app, limiter

def main():
    """Основная функция"""
    print("🔍 Мониторинг использования памяти Flask-Limiter")
    print("=" * 60)
    
    # Создаем тестовое приложение
    app, limiter = create_test_app()
    
    # Создаем мониторинг
    monitor = RateLimiterMonitor(app, limiter)
    
    # Запускаем мониторинг
    monitor.start_monitoring(interval=5)
    
    try:
        print("\n📋 Команды:")
        print("   'stats' - показать текущую статистику")
        print("   'save' - сохранить метрики в файл")
        print("   'quit' - выйти")
        print("\n⏳ Ожидание команд...")
        
        while True:
            command = input("> ").strip().lower()
            
            if command == 'stats':
                monitor.print_current_stats()
            elif command == 'save':
                monitor.save_metrics_to_file()
            elif command == 'quit':
                break
            else:
                print("❓ Неизвестная команда. Используйте: stats, save, quit")
                
    except KeyboardInterrupt:
        print("\n⏹️ Остановка по Ctrl+C...")
    finally:
        monitor.stop_monitoring()
        monitor.save_metrics_to_file()
        print("✅ Мониторинг завершен")

if __name__ == "__main__":
    main()
