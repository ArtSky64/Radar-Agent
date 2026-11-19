"""
Быстрый скрипт для полной очистки таблиц лидерборда LMSYS Arena (leaderboard, leaderboard_analysis).
Остальные данные (статьи, авторы, github, хаб RAG) не затрагиваются.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from database import clear_leaderboard, DB_NAME


def main():
    if not os.path.exists(DB_NAME):
        print(f"[!] База данных не найдена по пути: {DB_NAME}")
        return

    clear_leaderboard()
    print(f"[OK] Таблицы лидерборда Arena в {DB_NAME} успешно очищены!")


if __name__ == "__main__":
    main()
