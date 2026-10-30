# AI Радар & Scout ✦ Autonomous AI/ML Recon Core

Современная автономная система мониторинга, векторной дедупликации и интерактивной аналитики ключевых релизов в сфере искусственного интеллекта и машинного обучения.

Собирает данные из первоисточников:
* **Hugging Face** (трендовые модели и датасеты);
* **ArXiv & Papers with Code** (научные публикации и препринты);
* **GitHub Trending** (трендовые AI-репозитории и движки инференса);
* **LMSys Chatbot Arena** (лидерборд и замеры Elo моделей).

Система отсекает шум через векторную модель **FastEmbed** (косинусный порог 0.59), формирует краткие выжимки ключевых тезисов и предоставляет премиальный веб-интерфейс рабочей станции со встроенным RAG-ассистентом.

---

## 🏛 Архитектура проекта

```
agent/
├── app.py                      # FastAPI сервер (REST API + раздача собранного React SPA)
├── database.py                 # SQLite схемы, индексы и миграции
├── dedup.py                    # Векторная дедупликация (FastEmbed cosine similarity 0.59)
├── rag_service.py              # Векторный индекс базы знаний для семантического поиска
├── rag_agent.py                # Интеллектуальный диалоговый движок AI-ассистента
├── scheduler.py                # Планировщик периодического сбора данных
├── main.py                     # CLI-раннер краулеров
├── run_all.py                  # All-in-One раннер бэкенда и веб-интерфейса
├── config.py                   # Загрузчик настроек и .env
├── requirements.txt            # Зависимости Python
├── data/
│   └── app_database.db         # Боевая база данных SQLite
└── web/                        # Современный веб-интерфейс (React 19 + TypeScript + Vite + Tailwind CSS)
    ├── dist/                   # Готовая продакшн-сборка интерфейса (HTML/CSS/JS)
    └── src/
        ├── components/
        │   ├── studio/         # StudioFeed (лента), StudioSidebar (фильтры), StudioRightPane (обзор и ассистент)
        │   ├── background/     # FluidAuroraCanvas (живой космический k-NN фон)
        │   └── ui/             # CommandPalette (Ctrl+K), IntelligenceOrb, Sparkline, TypewriterText
        ├── types/              # TypeScript интерфейсы
        └── utils/              # Грамматика и локализация сущностей
```

---

## 🚀 Быстрый старт (Локальная разработка)

### 1. Установка Python-бэкенда
Требуется Python 3.10+:
```bash
python -m venv venv
# Активация окружения:
# Windows: venv\Scripts\activate
# Linux/macOS: source venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

### 2. Настройка конфигурации (.env)
Скопируйте шаблон и укажите ваши ключи:
```bash
cp .env.example .env
```
* `OPENAI_API_KEY` или `VLLM_BASE_URL` — для работы диалогового AI-ассистента;
* `GITHUB_TOKEN` — для работы парсера GitHub Trending;
* `HUGGINGFACE_API_KEY` — для расширенных лимитов HF API.

### 3. Запуск одной командой
```bash
python run_all.py
```
* **Веб-интерфейс и API:** `http://localhost:8000`
* **Swagger-документация API:** `http://localhost:8000/docs`

Если вы активно разрабатываете фронтенд с горячей перезагрузкой (HMR):
```bash
cd web
npm install
npm run dev
# Vite запустится на http://localhost:5173
```

---

## 📦 Развёртывание на продакшн-сервере

### Вариант 1. Запуск в один процесс через FastAPI (Рекомендуется)
Поскольку в `app.py` настроена автоматическая раздача собранного `web/dist`, на сервере **не требуется ставить Node.js**:
1. Соберите фронтенд локально:
   ```bash
   cd web
   npm run build
   ```
2. Скопируйте проект на сервер (включая папку `web/dist`).
3. Запустите сервер:
   ```bash
   uvicorn app:app --host 0.0.0.0 --port 8000
   ```
Веб-интерфейс и API будут доступны на одном порту `8000`.

### Вариант 2. Запуск через Nginx (Reverse Proxy)
Если перед сервисом стоит Nginx, направьте корневую статику на `web/dist`, а запросы к API проксируйте:
```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Раздача готового React фронтенда
    location / {
        root /path/to/agent/web/dist;
        try_files $uri $uri/ /index.html;
    }

    # Проксирование API запросов к FastAPI
    location ~ ^/(trending|articles|leaderboard|api|rag|scrape)/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 📡 Ключевые REST API эндпоинты

| Метод | Эндпоинт | Описание |
|---|---|---|
| `GET` | `/trending/models` | Получить срез трендовых моделей Hugging Face |
| `GET` | `/trending/github` | Получить трендовые репозитории GitHub |
| `GET` | `/articles` | Получить свежие статьи ArXiv и PapersWithCode |
| `GET` | `/leaderboard` | Получить данные лидерборда LMSys Arena |
| `POST` | `/api/v1/radar/sync` | Запустить фоновый сбор свежих данных по всем источникам |
| `POST` | `/api/v1/rag/query` | Отправить запрос диалоговому AI-ассистенту |

---

## ⌨ Горячие клавиши веб-интерфейса

* **`Ctrl + K`** — Быстрый поиск моделей, статей, репозиториев и команд (работает на RU и EN раскладках)
* **`↑` / `↓`** — Навигация по карточкам ленты
* **`Enter`** — Задать вопрос AI-ассистенту о выбранном материале
* **`Esc`** — Закрыть окно быстрого поиска
