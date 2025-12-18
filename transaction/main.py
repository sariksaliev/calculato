# main.py
import logging
from bot import TransactionBot


def main():
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )

    print( "[SYSTEM] Запуск бота...")

    # Вставьте сюда ваш токен
    TOKEN = "8298002084:AAGv1V8mWeBfuJbTNBILyE5vtUTvg54Luhk"

    try:
        bot = TransactionBot(TOKEN)
        bot.run()
    except Exception as e:
        logging.error(f"Ошибка при запуске бота: {e}")


if __name__ == "__main__":
    main()