# main.py
import logging
import os
from dotenv import load_dotenv

from bot import TransactionBot


def main():
    load_dotenv()

    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("Не найден BOT_TOKEN в .env")

    print("[SYSTEM] Запуск бота...")
    TransactionBot(token).run()


if __name__ == "__main__":
    main()
