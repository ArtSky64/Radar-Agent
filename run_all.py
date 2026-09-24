"""
Единый All-in-One раннер для AI/ML Radar Agent.
Запускает все компоненты проекта одной командой (без Docker):
  - api      -> FastAPI бэкенд (uvicorn app:app)
  - frontend -> Streamlit веб-интерфейс (frontend.py)
  - pipeline -> Основной пайплайн сбора и планировщик (scheduler.py / main.py)

Особенности:
  - Автоматическая инициализация БД (init_db) и применение миграций перед стартом.
  - Мгновенный вывод логов построчно (PYTHONUNBUFFERED=1, sys.executable -u).
  - Красивые цветовые префиксы [api], [frontend], [pipeline], [system].
  - Надежное завершение всего дерева процессов при нажатии Ctrl+C (Windows & Linux).
  - Поддержка гибких аргументов командной строки.

Запуск:
  python run_all.py

Дополнительные флаги:
  python run_all.py --run-once        # Запустить main.py один раз вместо цикличного планировщика
  python run_all.py --no-pipeline    # Запустить только Web UI и API (без сбора)
  python run_all.py --no-frontend    # Запустить только API и пайплайн
  python run_all.py --host 127.0.0.1 # Привязать к localhost
"""

import argparse
import os
import signal
import subprocess
import sys
import threading
import time

# Инициализируем поддержку ANSI-цветов в консоли Windows
if sys.platform == "win32":
    os.system("")

# Цвета для вывода логов
COLORS = {
    "api": "\033[36m",       # Cyan
    "frontend": "\033[35m",  # Magenta
    "pipeline": "\033[33m",  # Yellow
    "system": "\033[32m",    # Green
    "error": "\033[31m",     # Red
}
RESET = "\033[0m"
BOLD = "\033[1m"

procs: dict[str, subprocess.Popen] = {}
stop_event = threading.Event()
PID_FILE = "run_all.pid"


def log_system(message: str) -> None:
    print(f"{COLORS['system']}[system]{RESET} {message}")


def log_error(message: str) -> None:
    print(f"{COLORS['error']}[system error]{RESET} {message}")


def stream_output(name: str, proc: subprocess.Popen) -> None:
    """Потоковое чтение stdout/stderr процесса и вывод с цветным префиксом."""
    color = COLORS.get(name, "")
    prefix = f"{color}[{name}]{RESET} "
    try:
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            print(prefix + line.rstrip())
    except Exception:
        pass
    finally:
        if not stop_event.is_set():
            code = proc.poll()
            log_system(f"Процесс [{name}] завершился (код: {code})")


def kill_proc_tree(proc: subprocess.Popen) -> None:
    """Надежное завершение процесса и всех его дочерних процессов (кроссплатформенно)."""
    if proc.poll() is not None:
        return

    pid = proc.pid
    if sys.platform == "win32":
        try:
            # На Windows принудительно гасим все дерево процессов через taskkill
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    else:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def stop_all(*_args) -> None:
    """Обработчик остановки по Ctrl+C или SIGTERM."""
    if stop_event.is_set():
        return
    stop_event.set()
    print()
    log_system("Останавливаю все запущенные процессы...")

    for name, proc in list(procs.items()):
        kill_proc_tree(proc)

    # Удаляем PID-файл
    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
        except Exception:
            pass

    log_system("Все процессы успешно остановлены.")
    sys.exit(0)


def init_database_safe() -> None:
    """Проверка и инициализация базы данных перед запуском сервисов."""
    try:
        from database import init_db
        init_db()
        log_system("База данных SQLite инициализирована (схемы и миграции актуальны).")
    except Exception as e:
        log_error(f"Не удалось инициализировать БД: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI/ML Radar Agent All-in-One Runner")
    parser.add_argument("--host", default="0.0.0.0", help="Хост для API и Streamlit (default: 0.0.0.0)")
    parser.add_argument("--api-port", type=int, default=8000, help="Порт для FastAPI (default: 8000)")
    parser.add_argument("--frontend-port", type=int, default=8501, help="Порт для Streamlit (default: 8501)")
    parser.add_argument("--no-pipeline", action="store_true", help="Не запускать пайплайн сбора данных")
    parser.add_argument("--no-frontend", action="store_true", help="Не запускать веб-интерфейс Streamlit")
    parser.add_argument("--no-api", action="store_true", help="Не запускать FastAPI бэкенд")
    parser.add_argument("--run-once", action="store_true", help="Запустить main.py один раз вместо цикличного scheduler.py")

    args = parser.parse_args()

    # Сохраняем PID текущего раннера
    try:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except Exception as e:
        log_error(f"Не удалось записать {PID_FILE}: {e}")

    # Регистрируем сигналы завершения
    signal.signal(signal.SIGINT, stop_all)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop_all)

    # 1. Инициализируем БД
    init_database_safe()

    # Формируем конфигурацию запускаемых процессов
    root_dir = os.path.dirname(os.path.abspath(__file__)) or "."
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    commands: dict[str, list[str]] = {}

    if not args.no_api:
        commands["api"] = [
            sys.executable, "-u", "-m", "uvicorn", "app:app",
            "--host", args.host,
            "--port", str(args.api_port),
        ]

    if not args.no_frontend:
        commands["frontend"] = [
            sys.executable, "-u", "-m", "streamlit", "run", "frontend.py",
            "--server.address", args.host,
            "--server.port", str(args.frontend_port),
            "--server.headless", "true",
        ]

    if not args.no_pipeline:
        if args.run_once:
            commands["pipeline"] = [sys.executable, "-u", "main.py"]
        else:
            commands["pipeline"] = [sys.executable, "-u", "scheduler.py"]

    # Выводим красивый информационный баннер
    print("\n" + "=" * 70)
    print(f"{BOLD}AI/ML Radar Agent — All-in-One Environment{RESET}")
    print("=" * 70)
    if not args.no_frontend:
        print(f"  {BOLD}Веб-интерфейс (Streamlit):{RESET}  http://localhost:{args.frontend_port}")
    if not args.no_api:
        print(f"  {BOLD}REST API (FastAPI):{RESET}        http://localhost:{args.api_port}")
        print(f"  {BOLD}Документация API:{RESET}          http://localhost:{args.api_port}/docs")
    if not args.no_pipeline:
        mode_text = "main.py (разовый запуск)" if args.run_once else "scheduler.py (цикличный сбор)"
        print(f"  {BOLD}Пайплайн сбора данных:{RESET}    {mode_text}")
    print("=" * 70)
    print(f"Для остановки всех сервисов нажмите {BOLD}Ctrl + C{RESET}\n")

    # Запускаем все процессы
    for name, cmd in commands.items():
        log_system(f"Запуск {name} ({' '.join(cmd[1:])})...")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=root_dir,
                env=env,
            )
            procs[name] = proc
            threading.Thread(target=stream_output, args=(name, proc), daemon=True).start()
        except Exception as e:
            log_error(f"Не удалось запустить процесс [{name}]: {e}")

    # Главный цикл поддержания жизни раннера
    try:
        while not stop_event.is_set():
            # Если все процессы завершились сами
            if procs and all(p.poll() is not None for p in procs.values()):
                log_system("Все дочерние процессы завершили работу.")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        stop_all()


if __name__ == "__main__":
    main()
