# bot.py
import os
import re
import logging
from collections import defaultdict
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)


class TransactionCalculator:
    """
    ЖЁСТКАЯ ЛОГИКА:
    - #wallet_name (одно слово с _) — идентификатор кошелька
    - каждая строка с суммой = отдельная транзакция
    - никаких условий по словам, сетям, именам
    """

    def __init__(self):
        self.transactions = defaultdict(list)
        self.rates = {
            "USDT": 1.0, "USDC": 1.0,
            "BNB": 886.0, "TRX": 0.12,
            "ETH": 3500.0, "BTC": 68000.0, "SOL": 150.0,
        }

    def add_transactions(self, text: str) -> int:
        lines = text.splitlines()
        current_wallet = None
        added = 0

        for raw in lines:
            line = raw.strip()
            if not line:
                continue

            # 1️⃣ Жёстко: кошелёк только через #wallet_name
            if line.startswith("#"):
                wallet = line[1:].strip()
                if " " in wallet:
                    continue  # защита: пробелы запрещены
                current_wallet = wallet.lower()
                continue

            if not current_wallet:
                continue

            # 2️⃣ Ищем сумму ТОЛЬКО в строках с Received
            m = re.search(
                r"Received:\s*([\d.]+)\s*#?([A-Za-z]{2,10})",
                line,
                re.IGNORECASE
            )
            if not m:
                continue

            amount = float(m.group(1))
            currency = m.group(2).upper()

            addr_match = re.search(r"from\s+([A-Za-z0-9\.]+)", line, re.IGNORECASE)
            address = addr_match.group(1) if addr_match else None

            self.transactions[current_wallet].append({
                "amount": amount,
                "currency": currency,
                "address": address
            })
            added += 1

        return added

    def clear(self):
        self.transactions.clear()

    def get_status(self):
        if not self.transactions:
            return None

        tx_count = sum(len(v) for v in self.transactions.values())
        return {
            "wallets": len(self.transactions),
            "transactions": tx_count
        }

    def get_report(self) -> str:
        if not self.transactions:
            return "📭 Нет транзакций для отчёта."

        lines = []
        lines.append("📊 ОТЧЕТ ПО ТРАНЗАКЦИЯМ")
        lines.append(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        lines.append("─" * 40)

        total_usd = 0.0
        total_tx = 0

        for wallet in sorted(self.transactions.keys()):
            txs = self.transactions[wallet]
            lines.append(f"\n#{wallet}")
            lines.append(f"Транзакций: {len(txs)}")

            sums = defaultdict(float)
            for tx in txs:
                sums[tx["currency"]] += tx["amount"]
                total_tx += 1

            for cur, amt in sums.items():
                lines.append(f"{amt:.2f} {cur}")
                if cur in self.rates:
                    total_usd += amt * self.rates[cur]

        lines.append("\n" + "═" * 40)
        lines.append("📈 ОБЩАЯ СТАТИСТИКА:")
        lines.append(f"• Кошельков: {len(self.transactions)}")
        lines.append(f"• Транзакций: {total_tx}")
        lines.append(f"• Общая сумма: ${total_usd:.2f} USD")

        return "\n".join(lines)


class TransactionBot:
    def __init__(self, token: str):
        self.calc = TransactionCalculator()
        self.app = Application.builder().token(token).build()

        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("finish_count", self.finish))
        self.app.add_handler(CommandHandler("status", self.status))
        self.app.add_handler(CommandHandler("clear", self.clear))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 Калькулятор транзакций\n\n"
            "Формат ОБЯЗАТЕЛЕН:\n"
            "#wallet_name\n"
            "Received: 29 #USDT ($29) from 0x...\n\n"
            "Имя кошелька — одним словом через _"
        )

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        added = self.calc.add_transactions(update.message.text)
        if added:
            status = self.calc.get_status()
            await update.message.reply_text(
                f"✅ Добавлено: {added}\n"
                f"Кошельков: {status['wallets']}\n"
                f"Транзакций: {status['transactions']}"
            )
        else:
            await update.message.reply_text("❌ Не удалось распознать данные.")

    async def finish(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        report = self.calc.get_report()
        self.calc.clear()
        await update.message.reply_text(report + "\n\n✅ Готово.")

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        status = self.calc.get_status()
        if not status:
            await update.message.reply_text("📭 Пока нет данных.")
        else:
            await update.message.reply_text(
                f"Кошельков: {status['wallets']}\n"
                f"Транзакций: {status['transactions']}"
            )

    async def clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.calc.clear()
        await update.message.reply_text("🗑 Очищено.")

    def run(self):
        self.app.run_polling()


if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN") or "ВАШ_ТОКЕН"
    TransactionBot(TOKEN).run()
