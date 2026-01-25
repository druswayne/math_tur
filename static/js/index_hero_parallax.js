(function () {
  function prefersReducedMotion() {
    try {
      return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (_) {
      return false;
    }
  }

  function clamp(v, min, max) {
    return Math.max(min, Math.min(max, v));
  }

  function detectQuality(requested) {
    const q = (requested || "auto").toLowerCase();
    if (q === "high" || q === "low") return q;

    // auto: очень грубая эвристика
    const cores = Number(navigator.hardwareConcurrency || 0);
    const mem = Number(navigator.deviceMemory || 0); // может быть undefined
    const isSmallScreen = (window.innerWidth || 1024) <= 768;
    let isCoarse = false;
    try {
      isCoarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
    } catch (_) {
      isCoarse = false;
    }

    // На мобильных/тач-устройствах чаще выбираем low (особенно из-за blur/backdrop-filter).
    const lowEnd = isSmallScreen || isCoarse || (cores && cores <= 4) || (mem && mem <= 4);
    return lowEnd ? "low" : "high";
  }

  function mulberry32(seed) {
    let t = seed >>> 0;
    return function () {
      t += 0x6D2B79F5;
      let x = Math.imul(t ^ (t >>> 15), 1 | t);
      x ^= x + Math.imul(x ^ (x >>> 7), 61 | x);
      return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
    };
  }

  function pickTone(depth) {
    if (depth >= 0.5) return "near";
    if (depth >= 0.28) return "mid";
    return "far";
  }

  function generateWords(parallaxEl, wordSetName, quality, opts) {
    const WORD_SETS = {
      school: [
        "орфография", "пунктуация", "ударение", "словарь", "синонимы", "антонимы", "омонимы",
        "морфология", "синтаксис", "части речи", "подлежащее", "сказуемое", "обстоятельство",
        "определение", "дополнение", "прямая речь", "диалог", "обращение", "однородные члены",
        "сложное предложение", "сложноподчинённое", "сложносочинённое", "тире", "запятая", "точка с запятой",
        "приставка", "корень", "суффикс", "окончание", "чередование", "Н/НН", "не/ни", "слитно/раздельно",
        "буква «Ё»", "деепричастие", "причастие", "косвенная речь", "«кавычки»"
      ],
      olympiad: [
        "синтаксический разбор", "морфологический разбор", "фонетический разбор",
        "паронимы", "лексическое значение", "этимология", "фразеологизм", "стилистика",
        "речевая ошибка", "логика текста", "связность", "тропы", "метафора", "метонимия", "эпитет",
        "сравнение", "гипербола", "литота", "ирония", "градация", "анафора", "эпифора",
        "параллелизм", "инверсия", "эллипсис", "односоставное", "безличное", "неполное предложение",
        "обособление", "уточнение", "вводные слова", "причастный оборот", "деепричастный оборот",
        "орфоэпическая норма", "вариант нормы", "акцентология", "пунктуационная норма",
        "словообразование", "морфемика", "слитное/дефисное", "правописание суффиксов"
      ],
    };

    const words = WORD_SETS[wordSetName] || WORD_SETS.school;

    // Кол-во слов: зависит от площади видимой области
    const vw = Math.max(320, window.innerWidth || 1024);
    const vh = Math.max(480, window.innerHeight || 768);
    const isSmall = vw <= 576;
    const approx = Math.round((vw * vh) / 60000); // ~10-25
    // Нужно больше слов (примерно в 2 раза), но без кучности.
    // В low режиме ограничиваем верхнюю границу ради производительности.
    const count = quality === "low"
      ? clamp(Math.round(approx * 2), isSmall ? 12 : 18, isSmall ? 22 : 30)
      : clamp(Math.round(approx * 2), isSmall ? 16 : 26, isSmall ? 30 : 48);

    const seed = Date.now() ^ (vw << 16) ^ vh;
    const rnd = mulberry32(seed);

    parallaxEl.innerHTML = "";

    // Более равномерное распределение: сетка + jitter (вместо полностью случайных координат).
    // Это даёт меньше “кучности” без тяжёлых алгоритмов.
    const padX = 0.06;
    const padY = isSmall ? 0.06 : 0.10;
    const spanX = 0.88;
    const spanY = isSmall ? 0.88 : 0.80;
    const avoidRects = (opts && opts.avoidRects) || [];
    const preferBands = (opts && opts.preferBands) || null;

    const aspect = vw / vh;
    const cols = clamp(Math.round(Math.sqrt(count * aspect)), isSmall ? 4 : 5, isSmall ? 8 : 12);
    const rows = clamp(Math.ceil(count / cols), isSmall ? 4 : 4, isSmall ? 10 : 12);
    const cellW = spanX / cols;
    const cellH = spanY / rows;

    const cells = [];
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        cells.push({ c, r });
      }
    }
    // shuffle cells
    for (let i = cells.length - 1; i > 0; i--) {
      const j = Math.floor(rnd() * (i + 1));
      const tmp = cells[i];
      cells[i] = cells[j];
      cells[j] = tmp;
    }

    function insideAnyAvoidRect(nx, ny) {
      for (let i = 0; i < avoidRects.length; i++) {
        const a = avoidRects[i];
        if (nx >= a.x0 && nx <= a.x1 && ny >= a.y0 && ny <= a.y1) return true;
      }
      return false;
    }

    // В мобилке стараемся размещать слова преимущественно там, где нет таймера/карточки.
    const allowed = [];
    const blocked = [];
    for (let i = 0; i < cells.length; i++) {
      const cell = cells[i];
      const cx = padX + (cell.c + 0.5) * cellW;
      const cy = padY + (cell.r + 0.5) * cellH;
      (insideAnyAvoidRect(cx, cy) ? blocked : allowed).push(cell);
    }

    // Доп. приоритет: “полосы” выше/ниже карточки (особенно важно на мобилке,
    // где карточка часто занимает почти всю ширину и значимую часть высоты).
    const preferred = [];
    if (preferBands) {
      for (let i = 0; i < allowed.length; i++) {
        const cell = allowed[i];
        const cy = padY + (cell.r + 0.5) * cellH;
        if (cy <= preferBands.topMaxY || cy >= preferBands.bottomMinY) {
          preferred.push(cell);
        }
      }
    }

    // Формируем пул ячеек: сначала preferred, потом allowed.
    // Если allowed пуст — в крайнем случае используем все ячейки (иначе слов не будет вообще).
    let pool = preferred.length >= Math.min(8, Math.floor(cells.length / 5)) ? preferred : allowed;
    if (!pool.length) pool = cells;

    function shuffle(arr) {
      for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(rnd() * (i + 1));
        const tmp = arr[i];
        arr[i] = arr[j];
        arr[j] = tmp;
      }
    }

    // Если есть preferBands, делаем смешанный пул: preferred (перемешанный) + allowed (перемешанный)
    if (preferBands && preferred.length) {
      const p = preferred.slice();
      const a = allowed.slice();
      shuffle(p);
      shuffle(a);
      // убираем дубликаты (preferred уже подмножество allowed)
      const set = new Set(p.map((c) => c.r + ":" + c.c));
      const tail = a.filter((c) => !set.has(c.r + ":" + c.c));
      pool = p.concat(tail);
    } else {
      shuffle(pool);
    }

    // Выровняем плотность по горизонтали (чтобы слева/справа не “пустело”):
    // группируем по колонкам и берём ячейки по кругу.
    const groups = Array.from({ length: cols }, function () { return []; });
    for (let i = 0; i < pool.length; i++) {
      const cell = pool[i];
      if (cell && typeof cell.c === "number" && cell.c >= 0 && cell.c < cols) {
        groups[cell.c].push(cell);
      }
    }
    for (let c = 0; c < groups.length; c++) shuffle(groups[c]);

    const selectedCells = [];
    let colIdx = 0;
    while (selectedCells.length < count) {
      let attempts = 0;
      while (attempts < cols && groups[colIdx].length === 0) {
        colIdx = (colIdx + 1) % cols;
        attempts++;
      }
      // если внезапно всё пусто — fallback на исходный pool
      if (attempts >= cols && groups[colIdx].length === 0) break;

      const picked = groups[colIdx].pop();
      if (picked) selectedCells.push(picked);
      colIdx = (colIdx + 1) % cols;
    }
    if (selectedCells.length < count) {
      // fallback — добьём из pool
      for (let i = selectedCells.length; i < count; i++) {
        selectedCells.push(pool[i % pool.length]);
      }
    }

    const nodes = [];
    for (let i = 0; i < count; i++) {
      const word = words[Math.floor(rnd() * words.length)];

      const cell = selectedCells[i] || pool[i % pool.length] || { c: i % cols, r: Math.floor(i / cols) };
      // jitter внутри ячейки (0.18..0.82), чтобы не липло к границам ячейки
      const jx = 0.18 + rnd() * 0.64;
      const jy = 0.18 + rnd() * 0.64;
      const x = padX + (cell.c + jx) * cellW;
      const y = padY + (cell.r + jy) * cellH;

      const depth = 0.12 + rnd() * 0.55; // 0.12..0.67
      const tone = pickTone(depth);
      // Размер шрифта: на мобилках меньше, и длинные слова автоматически уменьшаем
      const fsMin = isSmall ? 11 : 12;
      const fsMax = isSmall ? 20 : 26;
      let fs = Math.round(fsMin + rnd() * (fsMax - fsMin));
      const wlen = word.length;
      if (wlen >= 18) fs = Math.round(fs * 0.72);
      else if (wlen >= 14) fs = Math.round(fs * 0.82);
      fs = clamp(fs, 10, fsMax);
      const rot = Math.round(-14 + rnd() * 28); // -14..14
      const scale = (0.96 + rnd() * 0.12).toFixed(2); // 0.96..1.08

      const outer = document.createElement("span");
      outer.className = "ru-word";
      outer.style.setProperty("--x", Math.round(x * 1000) / 10 + "%");
      outer.style.setProperty("--y", Math.round(y * 1000) / 10 + "%");
      outer.style.setProperty("--fs", fs + "px");
      outer.style.setProperty("--rot", rot + "deg");
      outer.style.setProperty("--scale", scale);

      const inner = document.createElement("span");
      inner.className = "ru-word__inner";
      inner.dataset.depth = String(depth.toFixed(3));
      inner.dataset.tone = tone;
      inner.textContent = word;

      // параметры для “плавания”
      // в low режиме заметно меньше амплитуды
      const ampK = quality === "low" ? 0.55 : 1.0;
      inner.dataset.floatAx = String(((0.8 + rnd() * 1.8) * ampK).toFixed(2)); // px
      inner.dataset.floatAy = String(((0.6 + rnd() * 1.6) * ampK).toFixed(2)); // px
      inner.dataset.floatSp = String((0.55 + rnd() * 1.05).toFixed(2)); // speed
      inner.dataset.phase = String((rnd() * Math.PI * 2).toFixed(3));

      // параметры “живости” от курсора (микро-наклон и микро-масштаб)
      inner.dataset.tilt = String((1.2 + rnd() * 3.8).toFixed(2)); // deg
      inner.dataset.pop = String((0.006 + rnd() * 0.012).toFixed(3)); // scale factor

      outer.appendChild(inner);
      parallaxEl.appendChild(outer);
      nodes.push(inner);
    }

    return nodes;
  }

  document.addEventListener("DOMContentLoaded", function () {
    const hero =
      document.getElementById("indexMainParallax") ||
      document.getElementById("indexHero");
    if (!hero) return;

    const parallaxEl =
      hero.querySelector(".index-main-parallax__parallax") ||
      hero.querySelector(".index-hero__parallax") ||
      hero;

    const wordSetName = (hero.getAttribute("data-word-set") || "school").trim();
    const quality = detectQuality(hero.getAttribute("data-parallax-quality"));
    // выставим фактическое значение, чтобы CSS мог реагировать
    hero.setAttribute("data-parallax-quality", quality);

    function computeAvoidRects() {
      // На мобилках хотим “обходить” области карточки/таймера
      const vw = window.innerWidth || 1024;
      let isCoarse = false;
      try {
        isCoarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
      } catch (_) {
        isCoarse = false;
      }
      const apply = vw <= 768 || isCoarse;
      if (!apply) return { avoidRects: [], preferBands: null };

      const host = hero.getBoundingClientRect();
      const avoid = [];
      let band = null;

      function addAvoidFor(el, padPx) {
        if (!el) return;
        const r = el.getBoundingClientRect();
        const x0 = clamp((r.left - host.left - padPx) / host.width, 0, 1);
        const y0 = clamp((r.top - host.top - padPx) / host.height, 0, 1);
        const x1 = clamp((r.right - host.left + padPx) / host.width, 0, 1);
        const y1 = clamp((r.bottom - host.top + padPx) / host.height, 0, 1);
        // если прямоугольник слишком маленький — игнор
        if (x1 - x0 < 0.02 || y1 - y0 < 0.02) return;
        avoid.push({ x0, y0, x1, y1 });
      }

      // Основная карточка турнира (включая таймер)
      const cardEl = hero.querySelector(".card");
      addAvoidFor(cardEl, 24);
      addAvoidFor(hero.querySelector(".countdown-timer"), 16);

      // Полосы: размещаем слова преимущественно выше/ниже карточки
      if (cardEl) {
        const r = cardEl.getBoundingClientRect();
        const y0 = clamp((r.top - host.top) / host.height, 0, 1);
        const y1 = clamp((r.bottom - host.top) / host.height, 0, 1);
        const m = 0.04; // запас по вертикали
        const topMaxY = clamp(y0 - m, 0.06, 0.90);
        const bottomMinY = clamp(y1 + m, 0.10, 0.94);
        band = { topMaxY, bottomMinY };
      }

      return { avoidRects: avoid, preferBands: band };
    }

    // Генерацию делаем в rAF, чтобы размеры уже были стабильны
    let nodes = [];
    function regenWords() {
      const res = computeAvoidRects();
      nodes = generateWords(parallaxEl, wordSetName, quality, res) || [];
      return nodes;
    }

    window.requestAnimationFrame(function () {
      regenWords();
    });

    // items будут готовы чуть позже; если слов нет — просто выходим
    function getItems() {
      return nodes.length ? nodes : Array.from(hero.querySelectorAll(".ru-word__inner[data-depth]"));
    }

    let targetX = 0;
    let targetY = 0;
    let currX = 0;
    let currY = 0;

    const MAX_SHIFT = quality === "low" ? 22 : 28; // px
    // Чем больше EASE, тем быстрее “догоняет” курсор.
    const EASE = quality === "low" ? 0.11 : 0.14;

    const reduceMotion = prefersReducedMotion();

    // Кэшируем числовые параметры, чтобы не читать dataset каждый кадр
    let anim = [];
    function rebuildAnim() {
      const items = getItems();
      anim = items.map(function (el) {
        return {
          el,
          depth: Number(el.dataset.depth || 0),
          ax: Number(el.dataset.floatAx || 1),
          ay: Number(el.dataset.floatAy || 1),
          sp: Number(el.dataset.floatSp || 1),
          ph: Number(el.dataset.phase || 0),
          tilt: Number(el.dataset.tilt || 2),
          pop: Number(el.dataset.pop || 0.01),
        };
      });
    }
    // первичная сборка (после генерации слов)
    window.requestAnimationFrame(function () {
      rebuildAnim();
    });

    function updateTargetFromEvent(e) {
      // На touch не гоняем параллакс к пальцу: это мешает скроллу и выглядит “дёргано”.
      if (e && e.pointerType && e.pointerType !== "mouse") return;
      const r = hero.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;

      const nx = (e.clientX - cx) / (r.width / 2);
      const ny = (e.clientY - cy) / (r.height / 2);

      targetX = clamp(nx, -1, 1) * MAX_SHIFT;
      targetY = clamp(ny, -1, 1) * MAX_SHIFT;
    }

    hero.addEventListener("pointermove", updateTargetFromEvent, { passive: true });
    hero.addEventListener(
      "pointerleave",
      function () {
        targetX = 0;
        targetY = 0;
      },
      { passive: true }
    );

    // Пауза, когда вкладка скрыта
    let paused = false;
    document.addEventListener("visibilitychange", function () {
      paused = document.hidden;
    });

    // Пауза, когда блок вне экрана
    let inView = true;
    try {
      const io = new IntersectionObserver(
        function (entries) {
          inView = entries.some(function (e) {
            return e.isIntersecting;
          });
        },
        { root: null, threshold: 0.05 }
      );
      io.observe(hero);
    } catch (_) {
      // ignore
    }

    // Ограничение FPS (low: ~30, high: ~45)
    const frameBudgetMs = quality === "low" ? 1000 / 30 : 1000 / 45;
    let lastFrame = 0;

    // “Пружина” для живого следования за курсором (даёт лёгкий овершут)
    let velX = 0;
    let velY = 0;
    const springK = quality === "low" ? 0.14 : 0.20; // жёсткость (живее)
    const springD = quality === "low" ? 0.76 : 0.70; // демпфирование (чуть больше овершут)
    let lastT = 0;
    const FLOAT_SPEED = quality === "low" ? 1.18 : 1.38;

    function tick(nowMs) {
      if (paused || !inView) {
        window.requestAnimationFrame(tick);
        return;
      }
      if (nowMs - lastFrame < frameBudgetMs) {
        window.requestAnimationFrame(tick);
        return;
      }
      lastFrame = nowMs;

      // dt нормализованный к 60fps
      const dt = lastT ? clamp((nowMs - lastT) / 16.67, 0.65, 1.8) : 1;
      lastT = nowMs;

      // Быстрая реакция + овершут: пружина, а не простой lerp
      velX += (targetX - currX) * (springK * dt);
      velY += (targetY - currY) * (springK * dt);
      const damp = Math.pow(springD, dt);
      velX *= damp;
      velY *= damp;
      currX += velX;
      currY += velY;

      // Чуть “поживее” — небольшой дополнительный lerp поверх пружины
      currX += (targetX - currX) * (EASE * 0.35);
      currY += (targetY - currY) * (EASE * 0.35);

      for (let i = 0; i < anim.length; i++) {
        const a = anim[i];
        // ближние слои реагируют сильнее (чуть нелинейно)
        const d = Math.pow(a.depth, 1.12);
        const baseX = currX * d;
        const baseY = currY * d;

        // лёгкое “плавание” всегда (если не prefers-reduced-motion)
        let fx = 0;
        let fy = 0;
        if (!reduceMotion) {
          const t = (nowMs || 0) / 1000;
          // немного завязано на depth: ближние двигаются чуть активнее
          const k = 0.55 + a.depth * 0.95;
          fx = Math.sin(t * a.sp * FLOAT_SPEED + a.ph) * a.ax * k;
          fy = Math.cos(t * (a.sp * 0.9) * FLOAT_SPEED + a.ph) * a.ay * k;
        }

        // “Живость” от курсора: микро-наклон и микро-масштаб
        const nx = MAX_SHIFT ? clamp(currX / MAX_SHIFT, -1, 1) : 0;
        const ny = MAX_SHIFT ? clamp(currY / MAX_SHIFT, -1, 1) : 0;
        const rot = (nx * 0.9 - ny * 0.45) * a.tilt * a.depth;
        const mag = (Math.abs(nx) + Math.abs(ny)) * 0.5;
        const sc = 1 + mag * a.pop * (0.6 + a.depth);

        a.el.style.transform =
          "translate3d(" + (baseX + fx) + "px, " + (baseY + fy) + "px, 0) " +
          "rotate(" + rot.toFixed(3) + "deg) " +
          "scale(" + sc.toFixed(4) + ")";
      }

      window.requestAnimationFrame(tick);
    }

    if (reduceMotion) {
      // без анимации — просто статичные слова
      return;
    }

    // перегенерация при изменении размеров (чтобы смотрелось естественно)
    let resizeTimer = 0;
    window.addEventListener(
      "resize",
      function () {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(function () {
          // при resize перегенерим слова (с учётом новых зон) и пересоберём кэш
          regenWords();
          rebuildAnim();
        }, 180);
      },
      { passive: true }
    );

    window.requestAnimationFrame(tick);
  });
})();

