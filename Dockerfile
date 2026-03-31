# Исполняемая среда - Python 3.11
FROM python:3.11-slim

# Указываем рабочую папку в контейнере
WORKDIR /app

# Копируем список зависимостей
COPY requirements.txt .

# Устанавливаем библиотеки
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект в контейнер
COPY . .

# Команда запуска обоих ботов через main.py
CMD ["python", "main.py"]
