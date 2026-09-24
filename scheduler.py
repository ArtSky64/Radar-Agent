import logging
import subprocess
import sys
import time

import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scheduler")

INTERVAL_HOURS = int(os.getenv("PIPELINE_INTERVAL_HOURS", "72"))
INTERVAL_SECONDS = INTERVAL_HOURS * 3600


def run_pipeline_once() -> None:
    """Запускает main.py ОТДЕЛЬНЫМ процессом с мгновенной построчной передачей логов (-u)."""
    logger.info("Запуск полного цикла пайплайна (main.py)...")
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    result = subprocess.run([sys.executable, "-u", "main.py"], env=env)
    if result.returncode != 0:
        logger.error(f"main.py завершился с кодом {result.returncode}")
    else:
        logger.info("Цикл пайплайна завершён успешно.")


def loop() -> None:
    while True:
        try:
            run_pipeline_once()
        except KeyboardInterrupt:
            logger.info("Остановка планировщика по сигналу.")
            break
        except Exception:
            logger.exception("Непредвиденный сбой планировщика — цикл продолжается")

        logger.info(f"Следующий запуск через {INTERVAL_HOURS} ч.")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    loop()