class TeacherTutorial {
    constructor() {
        this.currentStep = 0;
        this.steps = [
            {
                title: "Добро пожаловать в Лигу Знатоков!",
                description: "Давайте познакомимся с вашим личным кабинетом учителя. Это поможет вам быстрее освоить все возможности платформы для работы с учащимися.",
                target: null,
                position: 'center'
            },
                         {
                 title: "Всего учащихся",
                 description: "Количество учащихся которые зарегистрировались по вашей ссылке.",
                 target: '.row.mb-4.g-3 .col-md-3:nth-child(1) .stats-card',
                 position: 'bottom'
             },
             {
                 title: "Активных учащихся",
                 description: "Количество учащихся, которые поучаствовали хотя бы в одном турнире.",
                 target: '.row.mb-4.g-3 .col-md-3:nth-child(2) .stats-card',
                 position: 'bottom'
             },
             {
                 title: "Баланс",
                 description: "Баллы, которые начисляются за каждое участие учащегося в турнире. В конце сезона баллы можно обменять на подарки!",
                 target: '.row.mb-4.g-3 .col-md-3:nth-child(3) .stats-card',
                 position: 'bottom'
             },
             {
                 title: "Жетоны",
                 description: "Жетоны, которые вы можете распределять между своими учениками.",
                 target: '.row.mb-4.g-3 .col-md-3:nth-child(4) .stats-card',
                 position: 'bottom'
             },
            {
                title: "Купить жетоны",
                description: "Страница для покупки жетонов.",
                target: '.buy-tickets-btn',
                position: 'bottom'
            },
            {
                title: "Обменять баллы",
                description: "Страница на которой в конце сезона вы можете обменять баллы на призы.",
                target: '.shop-btn',
                position: 'bottom'
            },
            {
                title: "История активности",
                description: "Страница на которой вы можете видеть историю покупки жетонов и получения призов.",
                target: '.purchase-history-btn',
                position: 'bottom'
            },
            {
                title: "История передач",
                description: "Страница на которой вы видите историю выдачи жетонов своим учащимся. На этой странице можно отменить передачу.",
                target: '.transfer-history-btn',
                position: 'bottom'
            },
            {
                title: "Пригласительная ссылка для учащихся",
                description: "Используйте ссылку для регистрации своих учащихся.",
                target: '.invite-link-card',
                position: 'bottom'
            },
            {
                title: "Мои учащиеся",
                description: "Таблица с вашими учащимися. Для каждого учащегося в таблице доступно много полезной и интересной информации!",
                target: '.students-card',
                position: 'bottom'
            }
        ];
        
        this.resizeTimeout = null;
        this.init();
    }
    
    init() {
        // Очищаем старые куки при входе пользователя
        this.cleanupOldCookies();
        
        // Проверяем, нужно ли показывать обучение
        if (!this.shouldShowTutorial()) {
            return;
        }
        
                 // Проверяем наличие необходимых элементов
         const requiredElements = [
             '.row.mb-4.g-3 .col-md-3:nth-child(1) .stats-card',
             '.row.mb-4.g-3 .col-md-3:nth-child(2) .stats-card',
             '.row.mb-4.g-3 .col-md-3:nth-child(3) .stats-card',
             '.row.mb-4.g-3 .col-md-3:nth-child(4) .stats-card',
             '.buy-tickets-btn',
             '.shop-btn',
             '.purchase-history-btn',
             '.transfer-history-btn',
             '.invite-link-card',
             '.students-card'
         ];
        
        this.createOverlay();
        this.createTutorialContainer();
        this.showStep(0);
    }
    
    shouldShowTutorial() {
        // Проверяем, что мы на странице профиля учителя
        if (!window.location.pathname.includes('/teacher-profile')) {
            return false;
        }
        
        // Проверяем, что пользователь авторизован
        const isAuthenticated = document.body.classList.contains('logged-in') || 
                               document.body.getAttribute('data-user-authenticated') === 'true';
        if (!isAuthenticated) {
            return false;
        }
        
        // Получаем ID пользователя из данных на странице
        const userId = this.getUserId();
        if (!userId) {
            return false;
        }
        
        // Проверяем, проходил ли конкретный пользователь обучение
        const cookieName = `teacher_tutorial_completed_${userId}`;
        const hasCompleted = this.getCookie(cookieName);
        return !hasCompleted;
    }
    
         createOverlay() {
         this.overlay = document.createElement('div');
         this.overlay.className = 'tutorial-overlay';
         this.overlay.style.cssText = `
             position: fixed;
             top: 0;
             left: 0;
             width: 100%;
             height: 100%;
             background: rgba(0, 0, 0, 0.7);
             z-index: 9998;
             display: none;
         `;
         document.body.appendChild(this.overlay);
     }
    
    createTutorialContainer() {
        this.container = document.createElement('div');
        this.container.className = 'tutorial-container';
        this.container.style.cssText = `
            position: fixed;
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
            z-index: 9999;
            max-width: 90vw;
            width: 500px;
            display: none;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        `;
        
        this.container.innerHTML = `
            <div class="tutorial-header" style="padding: 20px 20px 0 20px;">
                <h3 class="tutorial-title" style="margin: 0 0 10px 0; color: #333; font-size: 1.4rem;"></h3>
                <p class="tutorial-description" style="margin: 0; color: #666; line-height: 1.5; font-size: 1rem;"></p>
            </div>
            <div class="tutorial-footer" style="padding: 20px; border-top: 1px solid #eee; display: flex; justify-content: space-between; align-items: center;">
                <div class="tutorial-progress" style="font-size: 0.9rem; color: #666;">
                    <span class="current-step">1</span> из <span class="total-steps">${this.steps.length}</span>
                </div>
                <div class="tutorial-buttons" style="display: flex; gap: 10px;">
                    <button class="tutorial-skip" style="
                        background: none;
                        border: 1px solid #ddd;
                        padding: 8px 16px;
                        border-radius: 6px;
                        cursor: pointer;
                        color: #666;
                        font-size: 0.9rem;
                        white-space: nowrap;
                    ">Пропустить</button>
                    <button class="tutorial-next" style="
                        background: #007bff;
                        border: none;
                        padding: 8px 16px;
                        border-radius: 6px;
                        cursor: pointer;
                        color: white;
                        font-size: 0.9rem;
                    ">Далее</button>
                </div>
            </div>
        `;
        
        document.body.appendChild(this.container);
        
        // Добавляем обработчики событий
        this.container.querySelector('.tutorial-skip').addEventListener('click', () => this.skipTutorial());
        this.container.querySelector('.tutorial-next').addEventListener('click', () => this.nextStep());
        
        // Обработчик изменения размера окна
        window.addEventListener('resize', () => {
            // Добавляем debounce для предотвращения частых вызовов
            clearTimeout(this.resizeTimeout);
            this.resizeTimeout = setTimeout(() => {
                this.handleWindowResize();
            }, 250);
        });
    }
    
    showStep(stepIndex) {
        const step = this.steps[stepIndex];
        
        // Обновляем содержимое
        this.container.querySelector('.tutorial-title').textContent = step.title;
        this.container.querySelector('.tutorial-description').textContent = step.description;
        this.container.querySelector('.current-step').textContent = stepIndex + 1;
        
        // Показываем контейнер
        this.container.style.display = 'block';
        
                 // Показываем overlay для первого шага (приветствие) и для кнопок в блоке "Действия"
         if (stepIndex === 0 || (stepIndex >= 5 && stepIndex <= 8)) {
             this.overlay.style.display = 'block';
         } else {
             this.overlay.style.display = 'none';
         }
        
        // Позиционируем контейнер
        this.positionContainer(step);
        
        // Подсвечиваем целевой элемент
        this.highlightTarget(step.target);
    }
    
    positionContainer(step) {
        if (!step.target) {
            // Центрируем для приветственного сообщения
            this.container.style.left = '50%';
            this.container.style.top = '50%';
            this.container.style.transform = 'translate(-50%, -50%)';
            return;
        }
        
        const targetElement = document.querySelector(step.target);
        if (!targetElement) {
            // Если элемент не найден, центрируем
            this.container.style.left = '50%';
            this.container.style.top = '50%';
            this.container.style.transform = 'translate(-50%, -50%)';
            return;
        }
        
        const targetRect = targetElement.getBoundingClientRect();
        const containerRect = this.container.getBoundingClientRect();
        
        let left, top;
        
        // Позиционируем относительно целевого элемента
        switch (step.position) {
            case 'top':
                left = targetRect.left + (targetRect.width / 2) - (containerRect.width / 2);
                top = targetRect.top - containerRect.height - 20;
                break;
            case 'bottom':
                left = targetRect.left + (targetRect.width / 2) - (containerRect.width / 2);
                top = targetRect.bottom + 20;
                break;
            case 'left':
                left = targetRect.left - containerRect.width - 20;
                top = targetRect.top + (targetRect.height / 2) - (containerRect.height / 2);
                break;
            case 'right':
                left = targetRect.right + 20;
                top = targetRect.top + (targetRect.height / 2) - (containerRect.height / 2);
                break;
            default:
                left = targetRect.left + (targetRect.width / 2) - (containerRect.width / 2);
                top = targetRect.bottom + 20;
        }
        
        // Проверяем границы экрана
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        
        // Корректируем по горизонтали
        if (left < 20) left = 20;
        if (left + containerRect.width > viewportWidth - 20) {
            left = viewportWidth - containerRect.width - 20;
        }
        
        // Корректируем по вертикали
        if (top < 20) top = 20;
        if (top + containerRect.height > viewportHeight - 20) {
            top = viewportHeight - containerRect.height - 20;
        }
        
        this.container.style.left = left + 'px';
        this.container.style.top = top + 'px';
        this.container.style.transform = 'none';
    }
    
    highlightTarget(targetSelector) {
        // Убираем предыдущую подсветку
        const previousHighlight = document.querySelector('.tutorial-highlight');
        if (previousHighlight) {
            previousHighlight.classList.remove('tutorial-highlight');
        }
        
        if (!targetSelector) return;
        
        const targetElement = document.querySelector(targetSelector);
        if (targetElement) {
            targetElement.classList.add('tutorial-highlight');
            
            // Прокручиваем к элементу
            targetElement.scrollIntoView({
                behavior: 'smooth',
                block: 'center'
            });
        }
    }
    
    nextStep() {
        this.currentStep++;
        
        if (this.currentStep >= this.steps.length) {
            this.completeTutorial();
        } else {
            this.showStep(this.currentStep);
        }
    }
    
    skipTutorial() {
        this.completeTutorial();
    }
    
    completeTutorial() {
        // Скрываем overlay и контейнер
        this.overlay.style.display = 'none';
        this.container.style.display = 'none';
        
        // Убираем подсветку
        const highlightedElement = document.querySelector('.tutorial-highlight');
        if (highlightedElement) {
            highlightedElement.classList.remove('tutorial-highlight');
        }
        
        // Устанавливаем куки о завершении обучения
        const userId = this.getUserId();
        if (userId) {
            const cookieName = `teacher_tutorial_completed_${userId}`;
            this.setCookie(cookieName, 'true', 365);
        }
        
                 // Показываем уведомление
         if (typeof showNotification === 'function') {
             showNotification('Обучение завершено!', 'Теперь вы знаете все возможности личного кабинета учителя. Вы всегда можете повторить обучение, нажав кнопку "Обучение" в правом верхнем углу.', 'success');
         }
    }
    
    handleWindowResize() {
        if (this.currentStep < this.steps.length) {
            this.showStep(this.currentStep);
        }
    }
    
    getUserId() {
        // Пытаемся получить ID пользователя из различных источников
        const userIdElement = document.querySelector('[data-user-id]');
        if (userIdElement) {
            return userIdElement.getAttribute('data-user-id');
        }
        
        // Ищем в URL или других местах
        const urlMatch = window.location.pathname.match(/\/teacher-profile\/(\d+)/);
        if (urlMatch) {
            return urlMatch[1];
        }
        
        return null;
    }
    
    cleanupOldCookies() {
        // Удаляем старые куки для обратной совместимости
        const oldCookie = this.getCookie('teacher_tutorial_completed');
        if (oldCookie) {
            this.setCookie('teacher_tutorial_completed', '', -1);
        }
    }
    
    // Утилиты для работы с куки
    setCookie(name, value, days) {
        const expires = new Date();
        expires.setTime(expires.getTime() + (days * 24 * 60 * 60 * 1000));
        document.cookie = name + '=' + value + ';expires=' + expires.toUTCString() + ';path=/';
    }
    
    getCookie(name) {
        const nameEQ = name + "=";
        const ca = document.cookie.split(';');
        for (let i = 0; i < ca.length; i++) {
            let c = ca[i];
            while (c.charAt(0) === ' ') c = c.substring(1, c.length);
            if (c.indexOf(nameEQ) === 0) return c.substring(nameEQ.length, c.length);
        }
        return null;
    }
}

// Добавляем CSS анимацию
const style = document.createElement('style');
style.textContent = `
         @keyframes tutorial-pulse {
         0% { 
             box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.7), 0 0 0 0 rgba(255, 193, 7, 0.7);
             transform: scale(1);
         }
         50% {
             box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.7), 0 0 0 5px rgba(255, 193, 7, 0.5);
             transform: scale(1.02);
         }
         100% { 
             box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.7), 0 0 0 0 rgba(255, 193, 7, 0);
             transform: scale(1);
         }
     }
    
         .tutorial-highlight {
         transition: all 0.3s ease;
         animation: tutorial-pulse 2s infinite;
         position: relative;
         z-index: 9999;
     }
     
     .tutorial-highlight:hover {
         border-color: #e0a800;
         box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.7), 0 0 0 3px rgba(224, 168, 0, 0.8);
     }
     
     /* Специальная обработка для кнопок в блоке "Действия" */
     .actions-card .tutorial-highlight {
         background: white !important;
         border-radius: 8px;
         box-shadow: 0 0 0 3px rgba(255, 193, 7, 0.8) !important;
     }
     
     .actions-card .tutorial-highlight:hover {
         box-shadow: 0 0 0 3px rgba(224, 168, 0, 0.8) !important;
     }
    
    @media (max-width: 768px) {
        .tutorial-container {
            width: 90vw !important;
            max-width: 90vw !important;
            margin: 10px;
            font-size: 13px;
            left: 48% !important;
            transform: translateX(-50%) !important;
        }
        
        .tutorial-header {
            padding: 12px 12px 0 12px !important;
        }
        
        .tutorial-footer {
            padding: 12px !important;
            flex-direction: column;
            gap: 8px;
        }
        
        .tutorial-buttons {
            width: 100%;
            justify-content: space-between;
        }
        
        .tutorial-skip, .tutorial-next {
            flex: 1;
            margin: 0 3px;
            font-size: 12px;
            padding: 5px 10px;
        }
        
        .tutorial-title {
            font-size: 1.1rem !important;
            margin-bottom: 8px !important;
        }
        
        .tutorial-description {
            font-size: 0.85rem !important;
            line-height: 1.4 !important;
        }
        
        .tutorial-progress {
            font-size: 0.8rem !important;
        }
    }
`;
document.head.appendChild(style);

// Запускаем обучение при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    new TeacherTutorial();
});
