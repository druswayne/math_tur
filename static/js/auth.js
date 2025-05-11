// Функция для получения токена из cookie
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
}

// Функция для добавления токена к запросам
function addTokenToRequests() {
    const token = getCookie('access_token');
    if (token) {
        // Добавляем токен ко всем fetch запросам
        const originalFetch = window.fetch;
        window.fetch = function() {
            let [resource, config] = arguments;
            if (config === undefined) {
                config = {};
            }
            if (config.headers === undefined) {
                config.headers = {};
            }
            config.headers['Authorization'] = token;
            return originalFetch(resource, config);
        };

        // Добавляем токен ко всем XMLHttpRequest
        const originalXHROpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function() {
            const result = originalXHROpen.apply(this, arguments);
            this.setRequestHeader('Authorization', token);
            return result;
        };
    }
}

// Запускаем функцию при загрузке страницы
document.addEventListener('DOMContentLoaded', addTokenToRequests); 