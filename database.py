import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "businesses.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Таблица бизнесов (создание, если нет)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS businesses (
            id TEXT PRIMARY KEY,
            name TEXT,
            prompt TEXT,
            fields TEXT,
            spreadsheet_id TEXT,
            spreadsheet_url TEXT,
            owner_email TEXT
        )
    ''')
    
    # УНИВЕРСАЛЬНАЯ МИГРАЦИЯ: Проверка всех колонок
    cursor.execute("PRAGMA table_info(businesses)")
    existing_columns = [column[1] for column in cursor.fetchall()]
    
    required_columns = {
        'fields': 'TEXT',
        'spreadsheet_id': 'TEXT',
        'spreadsheet_url': 'TEXT',
        'owner_email': 'TEXT'
    }
    
    for column_name, column_type in required_columns.items():
        if column_name not in existing_columns:
            try:
                print(f"Migrating database: adding missing column '{column_name}' to 'businesses' table...")
                cursor.execute(f"ALTER TABLE businesses ADD COLUMN {column_name} {column_type}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    pass # Значит, другой процесс уже добавил колонку
                else:
                    raise e

    # НОВАЯ КОЛОНКА KNOWLEDGE
    cursor.execute("PRAGMA table_info(businesses)")
    existing_columns = [column[1] for column in cursor.fetchall()]
    if 'knowledge' not in existing_columns:
        print("Migrating database: adding missing column 'knowledge' to 'businesses' table...")
        cursor.execute("ALTER TABLE businesses ADD COLUMN knowledge TEXT DEFAULT ''")
    
    # ТАБЛИЦА ЛИДОВ: Проверка колонки 'data'
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id TEXT,
            data TEXT, -- JSON со всеми собранными полями
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (business_id) REFERENCES businesses (id)
        )
    ''')
    cursor.execute("PRAGMA table_info(leads)")
    existing_leads_columns = [column[1] for column in cursor.fetchall()]
    if 'data' not in existing_leads_columns:
        print("Migrating database: adding missing column 'data' to 'leads' table...")
        cursor.execute("ALTER TABLE leads ADD COLUMN data TEXT")
    
    # Таблица сессий (диалогов) - теперь с композитным ключом (user_id, business_id)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            user_id INTEGER,
            business_id TEXT,
            history TEXT, -- JSON список сообщений
            completed BOOLEAN DEFAULT 0,
            PRIMARY KEY (user_id, business_id),
            FOREIGN KEY (business_id) REFERENCES businesses (id)
        )
    ''')

    # Таблица лидов (для истории, помимо Google Таблиц)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id TEXT,
            data TEXT, -- JSON со всеми собранными полями
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (business_id) REFERENCES businesses (id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Database initialized successfully!")

# --- Методы для бизнеса ---

def get_business(business_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM businesses WHERE id = ?", (business_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        res = dict(row)
        res['fields'] = json.loads(res['fields']) if res['fields'] else []
        return res
    return None

def get_all_businesses():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM businesses")
    rows = cursor.fetchall()
    conn.close()
    
    businesses = []
    for row in rows:
        b = dict(row)
        b['fields'] = json.loads(b['fields']) if b['fields'] else []
        businesses.append(b)
    return businesses

def save_business(id, name, prompt, fields, spreadsheet_id, spreadsheet_url, owner_email):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO businesses (id, name, prompt, fields, spreadsheet_id, spreadsheet_url, owner_email)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (id, name, prompt, json.dumps(fields, ensure_ascii=False), spreadsheet_id, spreadsheet_url, owner_email))
    conn.commit()
    conn.close()

# --- Методы для сессий ---

def get_session(user_id: int, business_id: str = None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if business_id:
        cursor.execute("SELECT * FROM sessions WHERE user_id = ? AND business_id = ?", (user_id, business_id))
    else:
        # Если business_id не передан, берем последнюю активную сессию (для обратной совместимости или дефолта)
        cursor.execute("SELECT * FROM sessions WHERE user_id = ? ORDER BY rowid DESC LIMIT 1", (user_id,))
        
    row = cursor.fetchone()
    conn.close()
    if row:
        res = dict(row)
        res['history'] = json.loads(res['history']) if res['history'] else []
        res['completed'] = bool(res['completed'])
        return res
    return {
        "user_id": user_id,
        "business_id": business_id,
        "history": [],
        "completed": False
    }

def update_session(user_id: int, business_id: str, history: list, completed: bool):
    if not business_id:
        return # Не сохраняем сессии без business_id
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO sessions (user_id, business_id, history, completed)
        VALUES (?, ?, ?, ?)
    ''', (user_id, business_id, json.dumps(history, ensure_ascii=False), int(completed)))
    conn.commit()
    conn.close()

# --- Методы для лидов ---

def save_lead(business_id: str, lead_data: dict):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO leads (business_id, data) 
        VALUES (?, ?)
    ''', (business_id, json.dumps(lead_data, ensure_ascii=True)))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()