# main.py
#!/usr/bin/env python3
import logging
import os
from bot import TransactionBot
from config import Config


def setup_logging():
    if not os.path.exists('logs'):
        os.makedirs('logs')

    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/bot.log'),
            logging.StreamHandler()
        ]
    )


def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    if not Config.BOT_TOKEN:
        logger.error("BOT_TOKEN не найден в .env файле!")
        return

    try:
        logger.info("Запуск бота...")
        bot = TransactionBot(token=Config.BOT_TOKEN)
        bot.run()

    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}", exc_info=True)


if __name__ == '__main__':
    main()