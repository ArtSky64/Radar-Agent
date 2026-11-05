# AI Радар & Scout — Web Client

Фронтенд-приложение на React 19, Vite, Tailwind CSS и Framer Motion.

## 🚀 Команды разработки

```bash
# Установка зависимостей
npm install

# Запуск dev-сервера с горячей перезагрузкой (порт 5173)
npm run dev

# Продакшн-сборка в папку dist/
npm run build

# Предпросмотр продакшн-сборки
npm run preview
```

## 🏗 Структура компонентов

* `src/components/studio/StudioFeed.tsx` — Центральная монолитная лента материалов.
* `src/components/studio/StudioSidebar.tsx` — Боковая панель источников и тематических фильтров.
* `src/components/studio/StudioRightPane.tsx` — Панель «AI Ассистент» и карточка «Обзор».
* `src/components/background/FluidAuroraCanvas.tsx` — Нейросетевой космический фон (k-NN граф).
* `src/components/ui/CommandPalette.tsx` — Быстрый поиск по Ctrl + K.
