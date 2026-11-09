"""
Быстрый скрипт для полной очистки таблиц лидерборда LMSYS Arena (leaderboard, leaderboard_analysis).
Остальные данные (статьи, авторы, github, хаб RAG) не затрагиваются.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import sqlite3
import config


def main():
    db_path = getattr(config, "DB_NAME", os.path.join("data", "app_database.db"))
    if not os.path.exists(db_path):
        print(f"[!] База данных не найдена по пути: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM leaderboard")
    cur.execute("DELETE FROM leaderboard_analysis")
    conn.commit()
    conn.close()
    print(f"[OK] Таблицы лидерборда Arena в {db_path} успешно очищены!")


if __name__ == "__main__":
    main()
