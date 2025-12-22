import re
from collections import defaultdict
from datetime import datetime
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram import Update


class TransactionCalculator:
    def __init__(self):
        # wallet_address -> currency -> amount
        self.transactions = defaultdict(lambda: defaultdict(float))

        self.rates = {
            'USDT': 1.0,
            'USDC': 1.0,
            'BNB': 886.0,
            'TRX': 0.12,
            'ETH': 3500.0,
            'BTC': 68000.0,
            'SOL': 150.0,
        }

    def add_transactions(self, text: str) -> int:
        lines = text.strip().split('\n')
        transactions_added = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if 'received:' not in line.lower():
                continue

            amount, currency, wallet_address = self._extract_transaction(line)

            if amount and currency and wallet_address:
                self.transactions[wallet_address][currency] += amount
                transactions_added += 1

        return transactions_added

    def _extract_transaction(self, line: str):
        """
        Возвращает:
        amount (float), currency (str), wallet_address (str)
        """

        amount_currency_pattern = r'Received:\s*([\d.]+)\s*#([A-Za-z]{2,})'
        wallet_pattern = r'from\s+([A-Za-z0-9\.]{6,})'

        amount_currency_match = re.search(amount_currency_pattern, line, re.IGNORECASE)
        wallet_match = re.search(wallet_pattern, line, re.IGNORECASE)

        if not amount_currency_match or not wallet_match:
            return None, None, None

        try:
            amount = float(amount_currency_match.group(1))
            currency = amount_currency_match.group(2).upper()
            wallet_address = wallet_match.group(1)

            return amount, currency, wallet_address
        except ValueError:
            return None, None, None

    def get_total_report(self) -> str:
        if not self.transactions:
            return "📭 Нет транзакций для отчёта."

        report = []
        report.append("📊 ОТЧЁТ ПО ТРАНЗАКЦИЯМ")
        report.append(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        report.append("─" * 40)

        total_all_usd = 0.0
        total_tx_count = 0

        for wallet_address, currencies in self.transactions.items():
            report.append(f"\n🔹 Wallet: {wallet_address}")

            wallet_usd_total = 0.0

            for currency, amount in currencies.items():
                report.append(f"• {amount:.2f} {currency}")

                if currency in self.rates:
                    wallet_usd_total += amount * self.rates[currency]

                total_tx_count += 1

            report.append(f"Итого по кошельку: ${wallet_usd_total:.2f}")
            total_all_usd += wallet_usd_total

        report.append("\n" + "═" * 40)
        report.append("📈 ОБЩАЯ СТАТИСТИКА:")
        report.append(f"• Кошельков: {len(self.transactions)}")
        report.append(f"• Транзакций: {total_tx_count}")
        report.append(f"• Общая сумма: ${total_all_usd:.2f} USD")

        return "\n".join(report)

    def clear_all(self):
        self.transactions.clear()

    def get_status(self):
        if not self.transactions:
            return None

        tx_count = sum(len(v) for v in self.transactions.values())

        return {
            "wallet_count": len(self.transactions),
            "transaction_count": tx_count
        }


class TransactionBot:
    def __init__(self, token: str):
        self.calculator = TransactionCalculator()
        self.application = Application.builder().token(token).build()
        self._setup_handlers()

    def _setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("finish_count", self.finish))
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(CommandHandler("clear", self.clear))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 Бот для подсчёта транзакций\n\n"
            "Отправьте текст с транзакциями.\n"
            "После завершения нажмите /finish_count"
        )

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        added = self.calculator.add_transactions(update.message.text)

        if added > 0:
            status = self.calculator.get_status()
            await update.message.reply_text(
                f"✅ Добавлено транзакций: {added}\n"
                f"• Кошельков: {status['wallet_count']}\n"
                f"• Всего транзакций: {status['transaction_count']}"
            )
        else:
            await update.message.reply_text(
                "❌ Не удалось распознать транзакции.\n"
                "Проверьте формат строки Received."
            )

    async def finish(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        report = self.calculator.get_total_report()
        self.calculator.clear_all()
        await update.message.reply_text(report)

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        status = self.calculator.get_status()
        if not status:
            await update.message.reply_text("📭 Нет активных транзакций.")
        else:
            await update.message.reply_text(
                f"📊 Статус:\n"
                f"• Кошельков: {status['wallet_count']}\n"
                f"• Транзакций: {status['transaction_count']}"
            )

    async def clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.calculator.clear_all()
        await update.message.reply_text("✅ Данные очищены.")

    def run(self):
        self.application.run_polling()
