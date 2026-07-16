(function () {
  'use strict';

  var SLIDES = [
    {
      bg: '#E67E00',
      panel: '#FF8C00',
      ghost: 'РЕГИСТРАЦИЯ',
      kicker: '1. Регистрация',
      desc: 'Заполните анкету, подтвердите согласия — и активируйте аккаунт по ссылке из письма на email.',
      cta: 'Участвовать'
    },
    {
      bg: '#D4A017',
      panel: '#FFD700',
      ghost: 'ЖЕТОНЫ',
      kicker: '2. Покупка жетонов',
      desc: 'В личном кабинете нажмите «Купить жетоны», укажите количество, оплатите через Express Pay — жетоны появятся в кошельке.',
      cta: 'Купить'
    },
    {
      bg: '#1f1f24',
      panel: '#343a40',
      ghost: 'ОЖИДАНИЕ',
      kicker: '3. Ожидание турнира',
      desc: 'На главной странице таймер показывает, сколько осталось до старта ближайшего турнира.',
      cta: 'На главную'
    },
    {
      bg: '#FF6B00',
      panel: '#FF8C00',
      ghost: 'ТУРНИР',
      kicker: '4. Участие в турнире',
      desc: 'После старта можно войти в турнир в любое время, пока он активен. Один участник — одно участие.',
      cta: 'Демо'
    },
    {
      bg: '#228B3B',
      panel: '#2fa84a',
      ghost: 'РЕЗУЛЬТАТЫ',
      kicker: '5. Результаты турнира',
      desc: 'Сначала смотрите личные результаты, затем турнирную таблицу рейтинга по параллелям.',
      cta: 'Смотреть'
    },
    {
      bg: '#C47800',
      panel: '#FFC000',
      ghost: 'ПРИЗЫ',
      kicker: '6. Лавка призов',
      desc: 'Из личного кабинета откройте лавку, выберите приз и оформите получение с адресом доставки. Баллы на призы смогут обменять только участники, занявшие 1–3 место в своей категории.',
      cta: 'В лавку'
    }
  ];

  var TOTAL = SLIDES.length;
  var activeIndex = 0;
  var isAnimating = false;
  var isMobile = window.innerWidth < 640;
  var waitTimer = null;
  var playTimer = null;
  var qtyTimer = null;
  var qtyDelayTimer = null;

  var hero = document.getElementById('tourHero');
  var slides = Array.prototype.slice.call(document.querySelectorAll('.tour-slide'));
  var ghostEl = document.getElementById('tourGhostText');
  var kickerEl = document.getElementById('tourKicker');
  var descEl = document.getElementById('tourDesc');
  var dotsEl = document.getElementById('tourDots');
  var prevBtn = document.getElementById('tourPrev');
  var nextBtn = document.getElementById('tourNext');

  if (!hero || !slides.length) return;

  document.body.classList.add('tour-page');

  function buildDots() {
    dotsEl.innerHTML = '';
    for (var i = 0; i < TOTAL; i++) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.setAttribute('aria-label', 'Шаг ' + (i + 1));
      btn.addEventListener('click', (function (idx) {
        return function () { goTo(idx); };
      })(i));
      dotsEl.appendChild(btn);
    }
  }

  function roleFor(i) {
    var diff = (i - activeIndex + TOTAL) % TOTAL;
    if (diff === 0) return 'center';
    if (diff === TOTAL - 1) return 'left';
    if (diff === 1) return 'right';
    if (diff === 2) return 'back';
    return 'far';
  }

  function applyRoles() {
    slides.forEach(function (el, i) {
      el.classList.remove('is-center', 'is-left', 'is-right', 'is-back', 'is-far', 'is-playing');
      el.classList.add('is-' + roleFor(i));
    });
  }

  function updateCopy() {
    var s = SLIDES[activeIndex];
    hero.style.backgroundColor = s.bg;
    hero.setAttribute('data-theme', activeIndex === 2 ? 'dark' : 'light');

    ghostEl.style.opacity = '0';
    setTimeout(function () {
      ghostEl.textContent = s.ghost;
      ghostEl.style.opacity = '1';
    }, 180);

    kickerEl.textContent = s.kicker;
    descEl.textContent = s.desc;

    Array.prototype.forEach.call(dotsEl.children, function (dot, i) {
      dot.classList.toggle('is-active', i === activeIndex);
    });
  }

  function resetTicketQty(center) {
    var qtyEl = center.querySelector('.anim-qty');
    var countEl = center.querySelector('.anim-ticket-count');
    var priceEl = center.querySelector('.anim-price');
    if (qtyEl) qtyEl.textContent = '1';
    if (countEl) countEl.textContent = '1';
    if (priceEl) priceEl.innerHTML = '5.00 BYN<br><small>≈ 150 RUB</small>';
  }

  function resetPlayHome(center) {
    var labelEl = center.querySelector('#playHomeLabel');
    if (labelEl) labelEl.textContent = 'До начала турнира осталось:';
    var map = { days: 0, hours: 0, mins: 0, secs: 3 };
    center.querySelectorAll('[data-play-home]').forEach(function (el) {
      el.textContent = pad(map[el.getAttribute('data-play-home')]);
    });
  }

  function restartCenterAnimations() {
    clearTimers();
    slides.forEach(function (el) {
      el.classList.remove('is-playing');
    });
    var center = slides[activeIndex];
    if (!center) return;
    if (activeIndex === 1) resetTicketQty(center);
    if (activeIndex === 3) resetPlayHome(center);
    void center.offsetWidth;
    center.classList.add('is-playing');
    startSlideTimers(activeIndex);
  }

  function clearTimers() {
    if (waitTimer) {
      clearInterval(waitTimer);
      waitTimer = null;
    }
    if (playTimer) {
      clearInterval(playTimer);
      playTimer = null;
    }
    if (qtyTimer) {
      clearInterval(qtyTimer);
      qtyTimer = null;
    }
    if (qtyDelayTimer) {
      clearTimeout(qtyDelayTimer);
      qtyDelayTimer = null;
    }
  }

  function pad(n) {
    return n < 10 ? '0' + n : String(n);
  }

  function startSlideTimers(index) {
    clearTimers();
    var center = slides[index];
    if (!center) return;

    if (index === 2) {
      var totalSecs = 2 * 86400 + 14 * 3600 + 37 * 60 + 45;
      waitTimer = setInterval(function () {
        totalSecs = Math.max(0, totalSecs - 1);
        var d = Math.floor(totalSecs / 86400);
        var h = Math.floor((totalSecs % 86400) / 3600);
        var m = Math.floor((totalSecs % 3600) / 60);
        var s = totalSecs % 60;
        var map = { days: d, hours: h, mins: m, secs: s };
        center.querySelectorAll('[data-cd]').forEach(function (el) {
          var key = el.getAttribute('data-cd');
          el.textContent = pad(map[key]);
        });
      }, 1000);
    }

    if (index === 3) {
      var startSecs = 3;
      var endSecs = 1 * 3600 + 59 * 60 + 48;
      var switched = false;
      var labelEl = center.querySelector('#playHomeLabel');
      playTimer = setInterval(function () {
        if (activeIndex !== 3) return;

        if (!switched) {
          startSecs = Math.max(0, startSecs - 1);
          var mapStart = { days: 0, hours: 0, mins: 0, secs: startSecs };
          center.querySelectorAll('[data-play-home]').forEach(function (el) {
            el.textContent = pad(mapStart[el.getAttribute('data-play-home')]);
          });
          if (startSecs === 0) {
            switched = true;
            if (labelEl) labelEl.textContent = 'До окончания турнира осталось:';
            var mapEnd0 = {
              days: Math.floor(endSecs / 86400),
              hours: Math.floor((endSecs % 86400) / 3600),
              mins: Math.floor((endSecs % 3600) / 60),
              secs: endSecs % 60
            };
            center.querySelectorAll('[data-play-home]').forEach(function (el) {
              el.textContent = pad(mapEnd0[el.getAttribute('data-play-home')]);
            });
          }
          return;
        }

        endSecs = Math.max(0, endSecs - 1);
        var mapEnd = {
          days: Math.floor(endSecs / 86400),
          hours: Math.floor((endSecs % 86400) / 3600),
          mins: Math.floor((endSecs % 3600) / 60),
          secs: endSecs % 60
        };
        center.querySelectorAll('[data-play-home]').forEach(function (el) {
          el.textContent = pad(mapEnd[el.getAttribute('data-play-home')]);
        });
        var compact = {
          h: Math.floor(endSecs / 3600),
          m: Math.floor((endSecs % 3600) / 60),
          s: endSecs % 60
        };
        center.querySelectorAll('[data-end]').forEach(function (el) {
          el.textContent = pad(compact[el.getAttribute('data-end')]);
        });
        center.querySelectorAll('[data-end2]').forEach(function (el) {
          el.textContent = pad(compact[el.getAttribute('data-end2')]);
        });
      }, 1000);
    }

    if (index === 1) {
      var qtyEl = center.querySelector('.anim-qty');
      var countEl = center.querySelector('.anim-ticket-count');
      var priceEl = center.querySelector('.anim-price');
      var basePerTicket = 5;
      var rubPerTicket = 150;
      var n = 1;
      // Quantity starts when buy scene is visible (~4.2s into 22s cycle)
      qtyDelayTimer = setTimeout(function () {
        qtyDelayTimer = null;
        if (activeIndex !== 1) return;
        qtyTimer = setInterval(function () {
          n = Math.min(5, n + 1);
          if (qtyEl) qtyEl.textContent = String(n);
          if (countEl) countEl.textContent = String(n);
          if (priceEl) {
            var byn = (n * basePerTicket).toFixed(2);
            var rub = n * rubPerTicket;
            priceEl.innerHTML = byn + ' BYN<br><small>≈ ' + rub + ' RUB</small>';
          }
          if (n >= 5) {
            clearInterval(qtyTimer);
            qtyTimer = null;
          }
        }, 650);
      }, 4200);
    }
  }

  function goTo(nextIndex) {
    if (isAnimating) return;
    nextIndex = ((nextIndex % TOTAL) + TOTAL) % TOTAL;
    if (nextIndex === activeIndex) return;

    isAnimating = true;
    activeIndex = nextIndex;
    applyRoles();
    updateCopy();
    setTimeout(function () {
      isAnimating = false;
      restartCenterAnimations();
    }, 650);
  }

  function navigate(dir) {
    if (isAnimating) return;
    goTo(dir === 'next' ? activeIndex + 1 : activeIndex - 1);
  }

  function onResize() {
    isMobile = window.innerWidth < 640;
  }

  buildDots();
  applyRoles();
  updateCopy();
  requestAnimationFrame(function () {
    restartCenterAnimations();
  });

  prevBtn.addEventListener('click', function () { navigate('prev'); });
  nextBtn.addEventListener('click', function () { navigate('next'); });
  window.addEventListener('resize', onResize);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowLeft') navigate('prev');
    if (e.key === 'ArrowRight') navigate('next');
  });

  var touchStartX = null;
  hero.addEventListener('touchstart', function (e) {
    touchStartX = e.changedTouches[0].screenX;
  }, { passive: true });

  hero.addEventListener('touchend', function (e) {
    if (touchStartX === null) return;
    var dx = e.changedTouches[0].screenX - touchStartX;
    touchStartX = null;
    if (Math.abs(dx) < 40) return;
    navigate(dx < 0 ? 'next' : 'prev');
  }, { passive: true });
})();
