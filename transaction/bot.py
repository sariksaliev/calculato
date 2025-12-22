# bot.py
import re
from collections import defaultdict
from datetime import datetime
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram import Update


class TransactionCalculator:
    def __init__(self):
        # wallet_id -> currency -> amount_sum
        self.transactions = defaultdict(lambda: defaultdict(float))
        self.total_transactions = 0  # кол-во распознанных строк Received

        self.rates = {
            'USDT': 1.0,
            'USDC': 1.0,
            'BNB': 886.0,
            'TRX': 0.12,
            'ETH': 3500.0,
            'BTC': 68000.0,
            'SOL': 150.0,
        }

        # Received: 70 #USDT ...
        self._re_amount_currency = re.compile(
            r'Received:\s*([\d.]+)\s*#([A-Za-z0-9]{2,})',
            re.IGNORECASE
        )

        # Cielo: ... (https://tronscan.org/#/address/TUpHuDkiCCmwaTZBHZvQdwWzGNm5t8J2b9)
        self._re_tronscan_addr = re.compile(
            r'tronscan\.org/#/address/([A-Za-z0-9]{20,})',
            re.IGNORECASE
        )
        # Если добавите другие сети — можно расширить аналогично:
        self._re_etherscan_addr = re.compile(
            r'etherscan\.io/address/(0x[a-fA-F0-9]{40})',
            re.IGNORECASE
        )
        self._re_bscscan_addr = re.compile(
            r'bscscan\.com/address/(0x[a-fA-F0-9]{40})',
            re.IGNORECASE
        )

        # fallback: from TUpHuD...J2b9 (до пробела/скобки/|)
        self._re_from_token = re.compile(
            r'\bfrom\s+([^\s\(\|]+)',
            re.IGNORECASE
        )

    def add_transactions(self, text: str) -> int:
        lines = text.strip().split('\n')
        added = 0

        for raw in lines:
            line = raw.strip()
            if not line:
                continue

            if 'received:' not in line.lower():
                continue

            amount, currency = self._extract_amount_currency(line)
            wallet_id = self._extract_wallet_id(line)

            if amount is None or currency is None or wallet_id is None:
                continue

            self.transactions[wallet_id][currency] += amount
            self.total_transactions += 1
            added += 1

        return added

    def _extract_amount_currency(self, line: str):
        m = self._re_amount_currency.search(line)
        if not m:
            return None, None
        try:
            return float(m.group(1)), m.group(2).upper()
        except ValueError:
            return None, None

    def _extract_wallet_id(self, line: str):
        # 1) сначала вытащим полный адрес из ссылок (самый надёжный способ)
        for rx in (self._re_tronscan_addr, self._re_etherscan_addr, self._re_bscscan_addr):
            m = rx.search(line)
            if m:
                return m.group(1)

        # 2) если ссылок нет — берём токен после from (может быть сокращённый)
        m = self._re_from_token.search(line)
        if m:
            return m.group(1).strip()

        return None

    def get_total_report(self) -> str:
        if not self.transactions:
            return "📭 Нет транзакций для отчёта."

        report_lines = []
        report_lines.append("📊 ОТЧЕТ ПО ТРАНЗАКЦИЯМ")
        report_lines.append(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        report_lines.append("─" * 40)

        total_all_usd = 0.0

        for wallet_id in sorted(self.transactions.keys()):
            report_lines.append(f"\nWallet: {wallet_id}")

            wallet_usd_total = 0.0
            currencies = self.transactions[wallet_id]

            for currency in sorted(currencies.keys()):
                amount = currencies[currency]
                report_lines.append(f"• {amount:.2f} {currency}")

                if currency in self.rates:
                    wallet_usd_total += amount * self.rates[currency]

            report_lines.append(f"Итого по кошельку: ${wallet_usd_total:.2f}")
            total_all_usd += wallet_usd_total

        report_lines.append("\n" + "═" * 40)
        report_lines.append("📈 ОБЩАЯ СТАТИСТИКА:")
        report_lines.append(f"• Кошельков: {len(self.transactions)}")
        report_lines.append(f"• Транзакций: {self.total_transactions}")
        report_lines.append(f"• Общая сумма: ${total_all_usd:.2f} USD")

        return "\n".join(report_lines)

    def clear_all(self):
        self.transactions.clear()
        self.total_transactions = 0

    def get_status(self):
        if not self.transactions:
            return None
        return {
            'wallet_count': len(self.transactions),
            'transaction_count': self.total_transactions,
        }


class TransactionBot:
    def __init__(self, token: str):
        self.token = token
        self.calculator = TransactionCalculator()
        self.application = Application.builder().token(token).build()
        self._setup_handlers()

    def _setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self._start_command))
        self.application.add_handler(CommandHandler("help", self._help_command))
        self.application.add_handler(CommandHandler("finish_count", self._finish_count_command))
        self.application.add_handler(CommandHandler("status", self._status_command))
        self.application.add_handler(CommandHandler("clear", self._clear_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 Бот-калькулятор транзакций\n\n"
            "Присылайте строки формата:\n"
            "Received: 10 #USDT ($10) from <wallet>\n\n"
            "Бот считает по значению после 'from'.\n"
            "Когда всё готово — /finish_count"
        )

    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🆘 Помощь\n\n"
            "Бот распознаёт строки с 'Received:' и 'from'.\n"
            "Кошелёк определяется по адресу/идентификатору после 'from'\n"
            "(или по полному адресу из ссылки tronscan/etherscan/bscscan).\n\n"
            "Пример:\n"
            "Received: 70 #USDT ($70) from TUpHuD...J2b9 (https://tronscan.org/#/address/TUpHuDkiCCmwaTZBHZvQdwWzGNm5t8J2b9)"
        )

    async def _finish_count_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.calculator.transactions:
            await update.message.reply_text("📭 Пока нет транзакций. Пришлите Received ... from ...")
            return

        report = self.calculator.get_total_report()
        self.calculator.clear_all()
        report += "\n\n✅ Отчет готов! Присылайте новые транзакции для следующего расчета."
        await update.message.reply_text(report)

    async def _status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        status = self.calculator.get_status()
        if not status:
            await update.message.reply_text("📭 Нет активных транзакций. Пришлите транзакции чтобы начать.")
            return

        await update.message.reply_text(
            f"📊 Текущий статус:\n"
            f"• Кошельков: {status['wallet_count']}\n"
            f"• Транзакций: {status['transaction_count']}\n\n"
            f"💡 Присылайте дополнительные транзакции или жмите /finish_count"
        )

    async def _clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.calculator.clear_all()
        await update.message.reply_text("✅ Все транзакции очищены. Можете начинать заново!")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        added = self.calculator.add_transactions(update.message.text)

        if added > 0:
            status = self.calculator.get_status()
            await update.message.reply_text(
                f"✅ Обработано транзакций: {added}\n\n"
                f"📊 Текущий статус:\n"
                f"• Кошельков: {status['wallet_count']}\n"
                f"• Всего транзакций: {status['transaction_count']}\n\n"
                f"💡 Присылайте дополнительные транзакции или жмите /finish_count чтобы посчитать"
            )
        else:
            await update.message.reply_text(
                "❌ Не удалось распознать транзакции.\n\n"
                "Нужен формат:\n"
                "Received: <amount> #<CUR> (...) from <wallet>\n\n"
                "Пример:\n"
                "Received: 10 #USDT ($10) from TEST123456"
            )

    def run(self):
        self.application.run_polling()
