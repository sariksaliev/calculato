# bot.py
import os
import re
import logging
from collections import defaultdict
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

logging.basicConfig(level=logging.INFO)


class TransactionCalculator:
    """
    ЛОГИКА:
    - Любая строка, начинающаяся с '#', считается названием кошелька (как есть).
    - Каждая строка 'Received: ...' = одна транзакция.
    - Транзакция относится к последнему увиденному кошельку.
    - Кошельки считаются по уникальным хэштегам.
    """

    def __init__(self):
        # wallet_name -> list of transactions
        self.transactions = defaultdict(list)

    def add_transactions(self, text: str) -> int:
        current_wallet = None
        added = 0

        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue

            # 1️⃣ Любой хэштег = имя кошелька (БЕЗ анализа)
            if line.startswith("#"):
                # убираем #, сохраняем текст как есть
                current_wallet = line[1:].strip()
                continue

            if not current_wallet:
                continue

            # 2️⃣ Каждая строка Received = транзакция
            match = re.search(
                r"Received:\s*([\d.]+)\s*#?([A-Za-z]{2,10})",
                line,
                re.IGNORECASE
            )
            if not match:
                continue

            amount = float(match.group(1))
            currency = match.group(2).upper()

            self.transactions[current_wallet].append({
                "amount": amount,
                "currency": currency
            })
            added += 1

        return added

    def clear(self):
        self.transactions.clear()

    def get_report(self) -> str:
        if not self.transactions:
            return "📭 Нет транзакций для отчёта."

        lines = []
        lines.append("📊 ОТЧЕТ ПО ТРАНЗАКЦИЯМ")
        lines.append(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        lines.append("─" * 40)

        total_transactions = 0
        total_sum = 0.0

        for wallet, txs in self.transactions.items():
            wallet_sum = 0.0

            for tx in txs:
                wallet_sum += tx["amount"]
                total_transactions += 1

            lines.append(f"\n{wallet}: {wallet_sum:.2f} USDT")
            total_sum += wallet_sum

        lines.append("\n" + "═" * 40)
        lines.append("📈 ОБЩАЯ СТАТИСТИКА:")
        lines.append(f"• Кошельков: {len(self.transactions)}")
        lines.append(f"• Транзакций: {total_transactions}")
        lines.append(f"• Общая сумма: {total_sum:.2f} USDT")

        return "\n".join(lines)


class TransactionBot:
    def __init__(self, token: str):
        self.calc = TransactionCalculator()
        self.app = Application.builder().token(token).build()

        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("finish_count", self.finish))
        self.app.add_handler(CommandHandler("clear", self.clear))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 Калькулятор транзакций\n\n"
            "Просто пересылайте сообщения с транзакциями.\n"
            "Бот сам определит кошельки по хэштегам.\n\n"
            "Команды:\n"
            "/finish_count — сформировать отчет\n"
            "/clear — очистить данные"
        )

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        added = self.calc.add_transactions(update.message.text)

        if added > 0:
            await update.message.reply_text(
                f"✅ Добавлено транзакций: {added}"
            )
        else:
            await update.message.reply_text(
                "ℹ️ Сообщение не содержит транзакций."
            )

    async def finish(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        report = self.calc.get_report()
        self.calc.clear()
        await update.message.reply_text(report + "\n\n✅ Отчет готов.")

    async def clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.calc.clear()
        await update.message.reply_text("🗑 Все данные очищены.")

    def run(self):
        self.app.run_polling()


if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN") or "ВАШ_ТОКЕН"
    TransactionBot(TOKEN).run()
