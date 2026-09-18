"""
Запускает все 3 процесса проекта одной командой, без Docker:
  - api      -> uvicorn app:app --host 0.0.0.0 --port 8000
  - frontend -> streamlit run frontend.py --server.address 0.0.0.0 --server.port 8501
  - worker   -> python scheduler.py

Логи всех трёх идут в один терминал, каждая строка с префиксом [api]/[frontend]/[worker].
Ctrl+C гасит все три процесса разом (а не по одному в трёх терминалах).

Запуск:  python run_all.py
Запуск в фоне (не глохнет при закрытии SSH):  nohup python run_all.py > run_all.log 2>&1 &
Остановка фонового запуска: kill $(cat run_all.pid)  (PID пишется при старте)
"""

import os
import signal
import subprocess
import sys
import threading

PROCESSES = {
    "api": [sys.executable, "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"],
    "frontend": [sys.executable, "-m", "streamlit", "run", "frontend.py",
                 "--server.address", "0.0.0.0", "--server.port", "8501"],
    "worker": [sys.executable, "scheduler.py"],
}

# Цвета для префиксов, чтобы разные процессы визуально не сливались в одной консоли.
COLORS = {"api": "\033[36m", "frontend": "\033[35m", "worker": "\033[33m"}
RESET = "\033[0m"

procs: dict[str, subprocess.Popen] = {}
stop_event = threading.Event()


def stream_output(name: str, proc: subprocess.Popen) -> None:
    color = COLORS.get(name, "")
    prefix = f"{color}[{name}]{RESET} "
    for line in iter(proc.stdout.readline, ""):
        if not line:
            break
        print(prefix + line.rstrip())
    if not stop_event.is_set():
        print(f"{prefix}!!! процесс завершился сам (код {proc.returncode}) — остальные продолжают работать")


def start_all() -> None:
    for name, cmd in PROCESSES.items():
        print(f"Запускаю {name}: {' '.join(cmd)}")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
        )
        procs[name] = proc
        threading.Thread(target=stream_output, args=(name, proc), daemon=True).start()


def stop_all(*_args) -> None:
    if stop_event.is_set():
        return
    stop_event.set()
    print("\nОстанавливаю все процессы...")
    for name, proc in procs.items():
        if proc.poll() is None:
            proc.terminate()
    for name, proc in procs.items():
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print(f"{name} не завершился за 10с — убиваю принудительно")
            proc.kill()
    sys.exit(0)


if __name__ == "__main__":
    with open("run_all.pid", "w") as f:
        f.write(str(os.getpid()))

    signal.signal(signal.SIGINT, stop_all)
    signal.signal(signal.SIGTERM, stop_all)

    start_all()

    # Держим главный поток живым, пока не прилетит Ctrl+C/SIGTERM или пока
    # все процессы не умрут сами (проверяем раз в секунду, а не блокируемся
    # в signal.pause(), иначе не заметим самостоятельную смерть процессов).
    import time
    while not stop_event.is_set():
        if all(p.poll() is not None for p in procs.values()):
            print("Все процессы завершились сами — выхожу.")
            break
        time.sleep(1)
