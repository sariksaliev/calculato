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


def detect_network(address: str) -> str:
    if address.startswith("0x"):
        return "BSC / EVM"
    if address.startswith("T"):
        return "TRC20"
    return "UNKNOWN"


class TransactionCalculator:
    """
    Логика:
    - каждая строка Received = транзакция
    - кошелёк определяется по `from <ADDRESS>`
    - группировка и суммирование ТОЛЬКО по адресу
    """

    def __init__(self):
        # address -> { currency -> amount }
        self.wallets = defaultdict(lambda: defaultdict(float))
        self.tx_count = 0

    def add_transactions(self, text: str) -> int:
        added = 0

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            # Ищем строку Received
            m = re.search(
                r"Received:\s*([\d.]+)\s*#?([A-Za-z]{2,10}).*?from\s+([A-Za-z0-9\.]+)",
                line,
                re.IGNORECASE
            )
            if not m:
                continue

            amount = float(m.group(1))
            currency = m.group(2).upper()
            address = m.group(3)

            self.wallets[address][currency] += amount
            self.tx_count += 1
            added += 1

        return added

    def clear(self):
        self.wallets.clear()
        self.tx_count = 0

    def get_report(self) -> str:
        if not self.wallets:
            return "📭 Нет транзакций для отчёта."

        lines = []
        lines.append("📊 ОТЧЕТ ПО ТРАНЗАКЦИЯМ")
        lines.append(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        lines.append("─" * 40)

        total_sum = defaultdict(float)

        for address, currencies in self.wallets.items():
            network = detect_network(address)
            lines.append(f"\n💼 Wallet: {address}")
            lines.append(f"🌐 Network: {network}")

            for currency, amount in currencies.items():
                lines.append(f"{currency}: {amount:.2f}")
                total_sum[currency] += amount

        lines.append("\n" + "═" * 40)
        lines.append("📈 ОБЩАЯ СТАТИСТИКА:")
        lines.append(f"• Кошельков: {len(self.wallets)}")
        lines.append(f"• Транзакций: {self.tx_count}")

        for currency, amount in total_sum.items():
            lines.append(f"• Всего {currency}: {amount:.2f}")

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
            "Бот сам сгруппирует по кошелькам (адресам).\n\n"
            "Команды:\n"
            "/finish_count — отчет\n"
            "/clear — очистить"
        )

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        added = self.calc.add_transactions(update.message.text)
        if added:
            await update.message.reply_text(f"✅ Добавлено транзакций: {added}")
        else:
            await update.message.reply_text("ℹ️ Транзакции не найдены.")

    async def finish(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        report = self.calc.get_report()
        self.calc.clear()
        await update.message.reply_text(report + "\n\n✅ Отчет готов.")

    async def clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.calc.clear()
        await update.message.reply_text("🗑 Данные очищены.")

    def run(self):
        self.app.run_polling()


if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN") or "ВАШ_ТОКЕН"
    TransactionBot(TOKEN).run()
