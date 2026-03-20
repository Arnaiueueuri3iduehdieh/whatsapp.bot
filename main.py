import subprocess
import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

def main():
    logging.info("🚀 Запуск системы WhatsApp.bot...")
    
    # Запускаем оба скрипта параллельно как отдельные процессы
    admin_process = subprocess.Popen([sys.executable, "admin_bot.py"])
    client_process = subprocess.Popen([sys.executable, "bot.py"])
    
    logging.info("✅ Admin Bot и Client Bot успешно запущены в фоновом режиме.")
    logging.info("Для остановки нажми Ctrl + C")
    
    try:
        # Следим за тем, чтобы оба процесса работали
        while True:
            time.sleep(1)
            if admin_process.poll() is not None:
                logging.error("❌ Admin Bot внезапно остановился.")
                break
            if client_process.poll() is not None:
                logging.error("❌ Client Bot внезапно остановился.")
                break
    except KeyboardInterrupt:
        logging.info("🛑 Получен сигнал остановки (Ctrl+C). Выключаем ботов...")
        
    # Аккуратно завершаем процессы при выходе
    admin_process.terminate()
    client_process.terminate()
    admin_process.wait()
    client_process.wait()
    logging.info("💤 Все боты успешно остановлены.")

if __name__ == "__main__":
    main()
