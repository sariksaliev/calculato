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
        self.total_transactions = 0  # количество распознанных строк Received

        # Курсы для подсчёта общей суммы в USD (примерные, задайте свои при необходимости)
        self.rates = {
            'USDT': 1.0,
            'USDC': 1.0,
            'BNB': 886.0,
            'TRX': 0.12,
            'ETH': 3500.0,
            'BTC': 68000.0,
            'SOL': 150.0,
        }

        # Шаблоны парсинга
        self._re_amount_currency = re.compile(r'Received:\s*([\d.]+)\s*#([A-Za-z0-9]{2,})', re.IGNORECASE)
        # Берём всё после "from" до конца строки или до "|" (часто встречается в пересланных сообщениях)
        self._re_from_wallet = re.compile(r'\bfrom\s+(.+?)(?:\s*\||\s*$)', re.IGNORECASE)

    def add_transactions(self, text: str) -> int:
        lines = text.strip().split('\n')
        added = 0

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            # Ищем только строки, где явно есть Received
            if 'received:' not in line.lower():
                continue

            amount, currency, wallet_id = self._extract_transaction(line)
            if amount is None or currency is None or wallet_id is None:
                continue

            self.transactions[wallet_id][currency] += amount
            self.total_transactions += 1
            added += 1

        return added

    def _extract_transaction(self, line: str):
        """
        Возвращает: (amount: float, currency: str, wallet_id: str)
        wallet_id — то, что стоит после 'from' (адрес или текстовый идентификатор).
        """
        m_amt = self._re_amount_currency.search(line)
        m_wal = self._re_from_wallet.search(line)

        if not m_amt or not m_wal:
            return None, None, None

        try:
            amount = float(m_amt.group(1))
            currency = m_amt.group(2).upper()
            wallet_id = m_wal.group(1).strip()

            # Небольшая санитарная очистка (на случай лишних пробелов/точек)
            wallet_id = re.sub(r'\s{2,}', ' ', wallet_id)
            return amount, currency, wallet_id
        except ValueError:
            return None, None, None

    def get_total_report(self) -> str:
        if not self.transactions:
            return "📭 Нет транзакций для отчёта."

        report_lines = []
        report_lines.append("📊 ОТЧЕТ ПО ТРАНЗАКЦИЯМ")
        report_lines.append(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        report_lines.append("─" * 40)

        total_all_usd = 0.0

        # Стабильный порядок вывода (алфавитный по wallet_id)
        for wallet_id in sorted(self.transactions.keys()):
            currencies = self.transactions[wallet_id]

            report_lines.append(f"\nWallet: {wallet_id}")

            wallet_usd_total = 0.0

            # Валюты тоже сортируем для аккуратности
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
        self.user_last_messages = {}  # последние статус-сообщения по user_id
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
        user_id = update.effective_user.id
        self.user_last_messages.pop(user_id, None)

        message = (
            "🤖 Бот-калькулятор транзакций\n\n"
            "Отправьте строки с транзакциями формата:\n"
            "Received: 10 #USDT ($10) from 0xef3a...13b20\n\n"
            "Ключ — значение после слова 'from' (адрес/идентификатор).\n\n"
            "Когда всё готово — /finish_count\n\n"
            "Команды:\n"
            "/finish_count - сформировать отчет\n"
            "/status - текущий статус\n"
            "/clear - очистить все\n"
            "/help - помощь"
        )
        await update.message.reply_text(message)

    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = (
            "🆘 Помощь\n\n"
            "Бот считает транзакции по идентификатору после 'from'.\n\n"
            "Пример:\n"
            "Received: 19.99 #USDT ($19.99) from 0xef3a...13b20\n"
            "Received: 0.50 #BNB ($443) from 0xef3a...13b20\n\n"
            "В отчёте будет:\n"
            "Wallet: 0xef3a...13b20\n"
            "• 19.99 USDT\n"
            "• 0.50 BNB\n"
            "Итого по кошельку: $...\n"
        )
        await update.message.reply_text(message)

    async def _finish_count_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        self.user_last_messages.pop(user_id, None)

        if not self.calculator.transactions:
            message = "📭 Пока нет транзакций. Пришлите текст с Received ... from ..."
        else:
            message = self.calculator.get_total_report()
            self.calculator.clear_all()
            message += "\n\n✅ Отчет готов! Присылайте новые транзакции для следующего расчета."

        await update.message.reply_text(message)

    async def _status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        self.user_last_messages.pop(user_id, None)

        status = self.calculator.get_status()
        if not status:
            message = "📭 Нет активных транзакций. Пришлите транзакции, чтобы начать."
        else:
            message = (
                f"📊 Текущий статус:\n"
                f"• Кошельков: {status['wallet_count']}\n"
                f"• Транзакций: {status['transaction_count']}\n\n"
                f"💡 Присылайте дополнительные транзакции или нажмите /finish_count"
            )

        await update.message.reply_text(message)

    async def _clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        self.user_last_messages.pop(user_id, None)

        self.calculator.clear_all()
        await update.message.reply_text("✅ Все транзакции очищены. Можно начинать заново.")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text

        added = self.calculator.add_transactions(text)

        if added > 0:
            status = self.calculator.get_status()
            message = (
                f"✅ Обработано транзакций: {added}\n\n"
                f"📊 Текущий статус:\n"
                f"• Кошельков: {status['wallet_count']}\n"
                f"• Всего транзакций: {status['transaction_count']}\n\n"
                f"💡 Присылайте ещё транзакции или нажмите /finish_count"
            )

            # обновляем “статусное” сообщение редактированием (как у вас было)
            if user_id in self.user_last_messages:
                last_msg_id = self.user_last_messages[user_id]
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=last_msg_id,
                        text=message
                    )
                except Exception:
                    new_message = await update.message.reply_text(message)
                    self.user_last_messages[user_id] = new_message.message_id
            else:
                new_message = await update.message.reply_text(message)
                self.user_last_messages[user_id] = new_message.message_id

        else:
            self.user_last_messages.pop(user_id, None)
            await update.message.reply_text(
                "❌ Не удалось распознать транзакции.\n\n"
                "Проверьте, что строка содержит формат:\n"
                "Received: <amount> #<CUR> (...) from <wallet>\n\n"
                "Пример:\n"
                "Received: 10 #USDT ($10) from 0xef3a...13b20"
            )

    def run(self):
        self.application.run_polling()
