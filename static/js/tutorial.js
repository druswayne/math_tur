class UserTutorial {
    constructor() {
        this.currentStep = 0;
        this.steps = [
            {
                title: "Добро пожаловать в Лигу Знатоков!",
                description: "Давайте познакомимся с вашим личным кабинетом. Это поможет вам быстрее освоить все возможности платформы.",
                target: null,
                position: 'center'
            },
            {
                title: "Профиль пользователя",
                description: "Здесь вы можете проверить и отредактировать свою личную информацию: имя, категорию, контактные данные.",
                target: '.profile-section',
                position: 'bottom'
            },
            {
                title: "Общий счёт",
                description: "Эти баллы вы зарабатываете за решение турнирных задач. В конце сезона их можно обменять на призы. На вкладке с общим рейтингом можно узнать своё место среди участников своей группы.",
                target: '.balance-section',
                position: 'bottom'
            },
            {
                title: "Жетоны",
                description: "Жетоны нужны для участия в турнирах. 1 жетон = 1 турнир. Жетоны покупаются за реальные деньги.",
                target: '.tickets-section',
                position: 'bottom'
            },
            {
                title: "Купить жетоны",
                description: "На этой странице вы можете покупать жетоны в любом количестве для участия в турнирах.",
                target: '.buy-tickets-btn',
                position: 'bottom'
            },
            {
                title: "Лавка призов",
                description: "Здесь вы можете обменивать заработанные на турнирах баллы на призы. Обмен доступен только в конце сезона.",
                target: '.shop-btn',
                position: 'bottom'
            },
            {
                title: "История покупок",
                description: "Просматривайте историю покупок жетонов и призов.",
                target: '.purchase-history-btn',
                position: 'bottom'
            },
            {
                title: "История турниров",
                description: "Здесь вы найдете информацию о турнирах, в которых участвовали: статистику по решенным и нерешенным задачам, время решения и рекомендации по итогам турнира.",
                target: '.tournament-history-btn',
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
            '.profile-section',
            '.balance-section', 
            '.tickets-section',
            '.buy-tickets-btn',
            '.shop-btn',
            '.purchase-history-btn',
            '.tournament-history-btn'
        ];
        
        this.createOverlay();
        this.createTutorialContainer();
        this.showStep(0);
    }
    
    shouldShowTutorial() {
        // Проверяем, что мы на странице профиля
        if (!window.location.pathname.includes('/profile')) {
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
        const cookieName = `tutorial_completed_${userId}`;
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
        
        // Показываем overlay только для первого шага (приветствие)
        if (stepIndex === 0) {
            this.overlay.style.display = 'block';
            this.positionContainerCenter();
        } else {
            this.overlay.style.display = 'none';
            // Позиционируем контейнер рядом с элементом
            if (step.target) {
                const element = document.querySelector(step.target);
                if (element) {
                    this.positionContainerNearElement(element);
                } else {
                    this.positionContainerTop();
                }
            } else {
                this.positionContainerTop();
            }
        }
        
        // Если есть целевой элемент, подсвечиваем его
        if (step.target) {
            this.highlightElement(step.target, step.position);
        } else {
            this.removeHighlight();
        }
        
        // Обновляем кнопку
        const nextBtn = this.container.querySelector('.tutorial-next');
        if (stepIndex === this.steps.length - 1) {
            nextBtn.textContent = 'Завершить';
        } else {
            nextBtn.textContent = 'Далее';
        }
    }
    
    highlightElement(selector, position) {
        this.removeHighlight();
        
        const element = document.querySelector(selector);
        if (!element) return;
        
        // Создаем подсветку
        this.highlight = document.createElement('div');
        this.highlight.className = 'tutorial-highlight';
        this.highlight.style.cssText = `
            position: absolute;
            border: 3px solid #ffc107;
            border-radius: 8px;
            box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.7);
            z-index: 9997;
            pointer-events: none;
            transition: all 0.3s ease;
        `;
        
        document.body.appendChild(this.highlight);
        
        // Позиционируем подсветку
        this.positionHighlight(element, position);
        
        // Добавляем пульсацию
        this.highlight.style.animation = 'tutorial-pulse 2s infinite';
        
        // Прокручиваем к элементу, если он не виден
        this.scrollToElement(element);
        
        // Обновляем позицию контейнера после прокрутки
        setTimeout(() => {
            this.positionContainerNearElement(element);
        }, 600);
    }
    
    positionHighlight(element, position) {
        const rect = element.getBoundingClientRect();
        const padding = 10;
        
        // Учитываем прокрутку страницы
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;
        
        // Вычисляем абсолютные координаты
        const absoluteTop = rect.top + scrollTop;
        const absoluteLeft = rect.left + scrollLeft;
        
        this.highlight.style.top = (absoluteTop - padding) + 'px';
        this.highlight.style.left = (absoluteLeft - padding) + 'px';
        this.highlight.style.width = (rect.width + padding * 2) + 'px';
        this.highlight.style.height = (rect.height + padding * 2) + 'px';
    }
    
    // Прокрутка к элементу с учетом модального окна
    scrollToElement(element) {
        const rect = element.getBoundingClientRect();
        const windowHeight = window.innerHeight;
        const windowWidth = window.innerWidth;
        const isMobile = windowWidth <= 768;
        
        // Примерные размеры модального окна
        const modalWidth = Math.min(500, windowWidth - 40);
        const modalHeight = 200; // Примерная высота
        const margin = 20;
        
        // Проверяем, виден ли элемент
        const isElementVisible = rect.top >= 0 && 
                                rect.bottom <= windowHeight && 
                                rect.left >= 0 && 
                                rect.right <= windowWidth;
        
        // Вычисляем оптимальную позицию прокрутки
        let targetScrollTop = window.pageYOffset;
        let needsScroll = false;
        
        if (!isElementVisible) {
            needsScroll = true;
            
            if (isMobile) {
                // На мобильных устройствах размещаем элемент в верхней части экрана
                // с учетом места для модального окна
                const elementTop = rect.top + window.pageYOffset;
                const modalSpace = modalHeight + margin * 2;
                targetScrollTop = elementTop - modalSpace;
            } else {
                // На десктопе размещаем элемент по центру, учитывая модальное окно
                const elementCenter = rect.top + window.pageYOffset + rect.height / 2;
                const viewportCenter = windowHeight / 2;
                const modalOffset = modalHeight / 2 + margin;
                
                // Если модальное окно будет справа/слева от элемента
                if (rect.right + modalWidth + margin <= windowWidth || rect.left - modalWidth - margin >= 0) {
                    // Размещаем элемент по центру экрана
                    targetScrollTop = elementCenter - viewportCenter;
                } else {
                    // Если модальное окно будет сверху/снизу, учитываем его размер
                    if (rect.top + window.pageYOffset < modalHeight + margin) {
                        // Элемент слишком высоко, прокручиваем вниз
                        targetScrollTop = rect.top + window.pageYOffset - margin;
                    } else if (rect.bottom + window.pageYOffset > windowHeight - modalHeight - margin) {
                        // Элемент слишком низко, прокручиваем вверх
                        targetScrollTop = rect.bottom + window.pageYOffset - windowHeight + modalHeight + margin;
                    } else {
                        // Размещаем элемент по центру
                        targetScrollTop = elementCenter - viewportCenter;
                    }
                }
            }
        } else {
            // Элемент виден, но проверяем, есть ли место для модального окна
            if (isMobile) {
                // На мобильных устройствах проверяем, есть ли место сверху для модального окна
                if (rect.top < modalHeight + margin) {
                    needsScroll = true;
                    targetScrollTop = window.pageYOffset + rect.top - modalHeight - margin;
                }
            } else {
                // На десктопе проверяем, есть ли место для модального окна рядом
                const hasSpaceRight = rect.right + modalWidth + margin <= windowWidth;
                const hasSpaceLeft = rect.left - modalWidth - margin >= 0;
                const hasSpaceTop = rect.top - modalHeight - margin >= 0;
                const hasSpaceBottom = rect.bottom + modalHeight + margin <= windowHeight;
                
                if (!hasSpaceRight && !hasSpaceLeft && !hasSpaceTop && !hasSpaceBottom) {
                    // Нет места для модального окна, прокручиваем к элементу
                    needsScroll = true;
                    targetScrollTop = rect.top + window.pageYOffset - margin;
                }
            }
        }
        
        if (needsScroll) {
            // Плавно прокручиваем к вычисленной позиции
            window.scrollTo({
                top: Math.max(0, targetScrollTop),
                behavior: 'smooth'
            });
            
            // Ждем завершения прокрутки перед позиционированием контейнера
            setTimeout(() => {
                if (this.currentStep > 0 && this.steps[this.currentStep] && this.steps[this.currentStep].target) {
                    const element = document.querySelector(this.steps[this.currentStep].target);
                    if (element) {
                        this.positionContainerNearElement(element);
                    }
                }
            }, 500);
        }
    }
    
    // Позиционирование контейнера по центру экрана
    positionContainerCenter() {
        this.container.style.top = '50%';
        this.container.style.left = '50%';
        this.container.style.transform = 'translate(-50%, -50%)';
    }
    
    // Позиционирование контейнера в верхней части экрана
    positionContainerTop() {
        const margin = 20;
        const isMobile = window.innerWidth <= 768;
        
        this.container.style.top = margin + 'px';
        this.container.style.left = isMobile ? '48%' : '50%';
        this.container.style.transform = 'translateX(-50%)';
        this.container.style.width = isMobile ? Math.min(400, window.innerWidth - 20) + 'px' : Math.min(500, window.innerWidth - 40) + 'px';
    }
    
    // Обработка изменения размера окна
    handleWindowResize() {
        if (this.currentStep === 0) {
            // Для приветственного сообщения просто центрируем
            this.positionContainerCenter();
            return;
        }
        
        const step = this.steps[this.currentStep];
        if (!step || !step.target) {
            this.positionContainerTop();
            return;
        }
        
        const element = document.querySelector(step.target);
        if (!element) {
            this.positionContainerTop();
            return;
        }
        
        // Проверяем, виден ли элемент после изменения размера
        const rect = element.getBoundingClientRect();
        const windowHeight = window.innerHeight;
        const windowWidth = window.innerWidth;
        
        const isElementVisible = rect.top >= 0 && 
                                rect.bottom <= windowHeight && 
                                rect.left >= 0 && 
                                rect.right <= windowWidth;
        
        if (!isElementVisible) {
            // Если элемент не виден, прокручиваем к нему
            this.scrollToElement(element);
        } else {
            // Если элемент виден, просто перепозиционируем контейнер и подсветку
            this.positionContainerNearElement(element);
            this.updateHighlightPosition(element);
        }
    }
    
    // Обновление позиции подсветки
    updateHighlightPosition(element) {
        if (this.highlight && element) {
            this.positionHighlight(element);
        }
    }
    
    // Позиционирование контейнера рядом с элементом
    positionContainerNearElement(element) {
        const rect = element.getBoundingClientRect();
        const containerRect = this.container.getBoundingClientRect();
        const windowWidth = window.innerWidth;
        const windowHeight = window.innerHeight;
        const margin = 20;
        const isMobile = windowWidth <= 768;
        
        // Вычисляем размеры контейнера
        const containerWidth = isMobile ? Math.min(400, windowWidth - 20) : Math.min(500, windowWidth - 40);
        const containerHeight = containerRect.height || (isMobile ? 150 : 200); // Более компактная высота на мобильных
        
        // Определяем позицию контейнера
        let top, left;
        let position = 'center'; // Для логирования
        
        // На мобильных устройствах сдвигаем чуть правее
        if (isMobile) {
            left = (windowWidth - containerWidth) / 2 + (windowWidth * 0.01); // Сдвигаем на 1% вправо
            
            if (rect.top - containerHeight - margin >= 0) {
                // Сверху от элемента
                top = rect.top - containerHeight - margin;
                position = 'mobile-top';
            } else if (rect.bottom + containerHeight + margin <= windowHeight) {
                // Снизу от элемента
                top = rect.bottom + margin;
                position = 'mobile-bottom';
            } else {
                // В верхней части экрана
                top = margin;
                position = 'mobile-top-fallback';
            }
        } else {
            // Десктопная логика
            // Проверяем, есть ли место справа от элемента
            if (rect.right + containerWidth + margin <= windowWidth) {
                left = rect.right + margin;
                // Выравниваем по вертикали с элементом, но не перекрываем его
                if (rect.top + rect.height + margin + containerHeight <= windowHeight) {
                    // Размещаем под элементом
                    top = rect.bottom + margin;
                    position = 'right-bottom';
                } else if (rect.top - containerHeight - margin >= 0) {
                    // Размещаем над элементом
                    top = rect.top - containerHeight - margin;
                    position = 'right-top';
                } else {
                    // Размещаем справа, выравнивая по центру элемента
                    top = Math.max(margin, rect.top + (rect.height - containerHeight) / 2);
                    position = 'right-center';
                }
            }
            // Проверяем, есть ли место слева от элемента
            else if (rect.left - containerWidth - margin >= 0) {
                left = rect.left - containerWidth - margin;
                // Выравниваем по вертикали с элементом, но не перекрываем его
                if (rect.top + rect.height + margin + containerHeight <= windowHeight) {
                    // Размещаем под элементом
                    top = rect.bottom + margin;
                    position = 'left-bottom';
                } else if (rect.top - containerHeight - margin >= 0) {
                    // Размещаем над элементом
                    top = rect.top - containerHeight - margin;
                    position = 'left-top';
                } else {
                    // Размещаем слева, выравнивая по центру элемента
                    top = Math.max(margin, rect.top + (rect.height - containerHeight) / 2);
                    position = 'left-center';
                }
            }
            // Если не помещается по горизонтали, размещаем сверху или снизу
            else {
                // Выравниваем по горизонтали с элементом
                left = Math.max(margin, Math.min(windowWidth - containerWidth - margin, rect.left + (rect.width - containerWidth) / 2));
                
                if (rect.top - containerHeight - margin >= 0) {
                    // Сверху
                    top = rect.top - containerHeight - margin;
                    position = 'top';
                } else if (rect.bottom + containerHeight + margin <= windowHeight) {
                    // Снизу
                    top = rect.bottom + margin;
                    position = 'bottom';
                } else {
                    // По центру экрана, но не перекрывая элемент
                    const centerY = (windowHeight - containerHeight) / 2;
                    if (centerY < rect.top - containerHeight - margin || centerY > rect.bottom + margin) {
                        top = centerY;
                        position = 'center';
                    } else {
                        // Если центр перекрывает элемент, размещаем в верхней части экрана
                        top = margin;
                        position = 'top-fallback';
                    }
                }
            }
        }
        
        // Применяем позицию
        this.container.style.top = top + 'px';
        this.container.style.left = left + 'px';
        this.container.style.transform = 'none';
        this.container.style.width = containerWidth + 'px';
        
        // Дополнительная проверка на перекрытие
        setTimeout(() => {
            const containerRect = this.container.getBoundingClientRect();
            const elementRect = element.getBoundingClientRect();
            
            // Проверяем, перекрывает ли контейнер элемент
            const isOverlapping = !(containerRect.right < elementRect.left || 
                                   containerRect.left > elementRect.right || 
                                   containerRect.bottom < elementRect.top || 
                                   containerRect.top > elementRect.bottom);
            
            if (isOverlapping) {
                // Если перекрывает, размещаем в верхней части экрана
                this.positionContainerTop();
            }
        }, 50);
    }
    
    removeHighlight() {
        if (this.highlight) {
            this.highlight.remove();
            this.highlight = null;
        }
    }
    
    nextStep() {
        if (this.currentStep < this.steps.length - 1) {
            this.currentStep++;
            this.showStep(this.currentStep);
        } else {
            this.completeTutorial();
        }
    }
    
    skipTutorial() {
        if (confirm('Вы уверены, что хотите пропустить обучение? Вы всегда можете пройти его позже в личном кабинете.')) {
            this.completeTutorial();
        }
    }
    
    completeTutorial() {
        // Получаем ID пользователя
        const userId = this.getUserId();
        if (userId) {
            // Устанавливаем куки для конкретного пользователя
            const cookieName = `tutorial_completed_${userId}`;
            this.setCookie(cookieName, 'true', 365);
        } else {
            // Fallback для старых куки
            this.setCookie('tutorial_completed', 'true', 365);
        }
        
        // Очищаем таймер изменения размера окна
        if (this.resizeTimeout) {
            clearTimeout(this.resizeTimeout);
            this.resizeTimeout = null;
        }
        
        // Убираем подсветку и контейнеры
        this.removeHighlight();
        this.overlay.remove();
        this.container.remove();
        
        // Показываем напутствие
        this.showCompletionMessage();
    }
    
    showCompletionMessage() {
        const message = document.createElement('div');
        message.className = 'tutorial-completion';
        message.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: #28a745;
            color: white;
            padding: 15px 20px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            z-index: 10000;
            max-width: 300px;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        `;
        
        message.innerHTML = `
            <div style="font-weight: bold; margin-bottom: 5px;">🎉 Обучение завершено!</div>
            <div style="font-size: 0.9rem;">Теперь вы знаете все основные возможности личного кабинета. Удачи в турнирах!</div>
        `;
        
        document.body.appendChild(message);
        
        // Убираем сообщение через 5 секунд
        setTimeout(() => {
            message.style.opacity = '0';
            message.style.transform = 'translateX(100%)';
            message.style.transition = 'all 0.5s ease';
            setTimeout(() => message.remove(), 500);
        }, 5000);
    }
    
    // Получение ID пользователя
    getUserId() {
        // Пытаемся получить ID из различных источников
        const userId = document.body.getAttribute('data-user-id') ||
                      document.querySelector('[data-user-id]')?.getAttribute('data-user-id') ||
                      this.extractUserIdFromPage();
        
        return userId;
    }
    
    // Извлечение ID пользователя со страницы
    extractUserIdFromPage() {
        // Пытаемся найти ID в URL или других элементах
        const profileLink = document.querySelector('a[href*="/profile"]');
        if (profileLink) {
            const href = profileLink.getAttribute('href');
            const match = href.match(/\/profile\?user=(\d+)/);
            if (match) return match[1];
        }
        
        // Если не нашли, возвращаем null
        return null;
    }
    
    // Очистка старых куки при смене пользователя
    cleanupOldCookies() {
        const userId = this.getUserId();
        if (userId) {
            // Удаляем старый общий куки, если он есть
            this.setCookie('tutorial_completed', '', -1); // Устанавливаем срок в прошлое
            
            // Проверяем все куки и удаляем старые tutorial_completed_*
            const cookies = document.cookie.split(';');
            cookies.forEach(cookie => {
                const [name, value] = cookie.trim().split('=');
                if (name.startsWith('tutorial_completed_') && name !== `tutorial_completed_${userId}`) {
                    this.setCookie(name, '', -1);
                }
            });
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
    }
    
    .tutorial-highlight:hover {
        border-color: #e0a800;
        box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.7), 0 0 0 3px rgba(224, 168, 0, 0.8);
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
    new UserTutorial();
}); 