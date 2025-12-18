# bot.py
import re
import logging
from collections import defaultdict
from datetime import datetime
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram import Update

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


class TransactionCalculator:
    def __init__(self):
        self.transactions = defaultdict(list)
        self.rates = {
            'USDT': 1.0, 'USDC': 1.0, 'BNB': 886.0, 'TRX': 0.12,
            'ETH': 3500.0, 'BTC': 68000.0, 'SOL': 150.0,
        }
        self.total_transactions_added = 0

    def add_transactions(self, text):
        lines = text.strip().split('\n')
        current_wallet = None
        transactions_added = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            line_lower = line.lower()

            if 'oscar' in line_lower and 'max' in line_lower and 'bnb' in line_lower:
                current_wallet = 'oscar_max_bnb'
                continue
            elif 'oscar' in line_lower and ('mini' in line_lower or 'mimi' in line_lower) and 'bnb' in line_lower:
                current_wallet = 'oscar_mini_bnb'
                continue
            elif 'jack' in line_lower and 'med' in line_lower and 'trc' in line_lower:
                current_wallet = 'jack_trc20'
                continue
            elif 'oscar' in line_lower and 'max' in line_lower and 'trc' in line_lower:
                current_wallet = 'oscar_max_trc20'
                continue
            elif line.startswith('#'):
                content = line[1:].lower().strip()
                if 'oscar' in content and 'max' in content and 'bnb' in content:
                    current_wallet = 'oscar_max_bnb'
                elif 'oscar' in content and 'max' in content and 'trc' in content:
                    current_wallet = 'oscar_max_trc20'
                elif 'oscar' in content and ('mini' in content or 'mimi' in content):
                    current_wallet = 'oscar_mini_bnb'
                elif 'jack' in content:
                    current_wallet = 'jack_trc20'
                continue

            if current_wallet and 'received:' in line_lower:
                amount, currency = self._extract_transaction(line)
                if amount and currency:
                    self.transactions[current_wallet].append({
                        'amount': amount,
                        'currency': currency
                    })
                    transactions_added += 1

        self.total_transactions_added += transactions_added
        return transactions_added

    def _extract_transaction(self, line):
        patterns = [
            r'(\d+\.?\d*)\s*#([A-Za-z]{2,})',
            r'(\d+\.?\d*)\s+([A-Za-z]{2,})',
            r'#([a-z]{2,})\s*\(.*?(\d+\.?\d*)',
        ]

        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                try:
                    groups = match.groups()

                    if pattern == patterns[0]:
                        amount = float(groups[0])
                        currency = groups[1].upper()
                        return amount, currency

                    elif pattern == patterns[1]:
                        amount = float(groups[0])
                        currency = groups[1].upper()
                        return amount, currency

                    elif pattern == patterns[2]:
                        currency = groups[0].upper()
                        amount = float(groups[1])
                        return amount, currency

                except (ValueError, IndexError, AttributeError):
                    continue

        return None, None

    def get_total_report(self):
        if not self.transactions:
            return "📭 Нет транзакций для отчета."

        report_lines = []
        report_lines.append("📊 ОТЧЕТ ПО ТРАНЗАКЦИЯМ")
        report_lines.append(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        report_lines.append("─" * 40)

        total_all_usd = 0
        total_wallets = len(self.transactions)
        total_transactions = self.total_transactions_added

        wallet_order = ['oscar_max_bnb', 'oscar_max_trc20', 'oscar_mini_bnb', 'jack_trc20']

        for wallet_name in wallet_order:
            if wallet_name in self.transactions and self.transactions[wallet_name]:
                wallet_transactions = self.transactions[wallet_name]
                wallet_tx_count = len(wallet_transactions)

                currency_sums = defaultdict(float)
                for tx in wallet_transactions:
                    currency_sums[tx['currency']] += tx['amount']

                if wallet_name == 'oscar_max_bnb':
                    report_lines.append(f"\n#oscar max bnb")
                elif wallet_name == 'oscar_max_trc20':
                    report_lines.append(f"\n#oscar max trc20")
                elif wallet_name == 'oscar_mini_bnb':
                    report_lines.append(f"\n#oscar MINI Bnb")
                elif wallet_name == 'jack_trc20':
                    report_lines.append(f"\n#Jack med trc20")
                else:
                    report_lines.append(f"\n#{wallet_name}")

                report_lines.append(f"Транзакций: {wallet_tx_count}")

                for currency, amount in sorted(currency_sums.items()):
                    report_lines.append(f"{amount:.2f} {currency}")

                    if currency in self.rates:
                        total_all_usd += amount * self.rates[currency]

        report_lines.append("\n" + "═" * 40)
        report_lines.append("📈 ОБЩАЯ СТАТИСТИКА:")
        report_lines.append(f"• Кошельков: {total_wallets}")
        report_lines.append(f"• Транзакций: {total_transactions}")
        report_lines.append(f"• Общая сумма: ${total_all_usd:.2f} USD")

        return "\n".join(report_lines)

    def count_transactions(self):
        return self.total_transactions_added

    def clear_all(self):
        self.transactions.clear()
        self.total_transactions_added = 0

    def get_status(self):
        if not self.transactions:
            return None

        total_tx = 0
        for wallet_txs in self.transactions.values():
            total_tx += len(wallet_txs)

        return {
            'wallet_count': len(self.transactions),
            'transaction_count': total_tx,
        }


class TransactionBot:
    def __init__(self, token: str):
        self.token = token
        self.calculator = TransactionCalculator()
        self.user_last_messages = {}

        self.application = Application.builder() \
            .token(token) \
            .concurrent_updates(True) \
            .build()

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
        if user_id in self.user_last_messages:
            del self.user_last_messages[user_id]

        message = (
            "🤖 Бот-калькулятор транзакций\n\n"
            "Просто пришлите транзакции текстом.\n"
            "Я распознаю кошельки и суммы автоматически.\n\n"
            "Когда все готово - нажмите /finish_count\n\n"
            "Команды:\n"
            "/finish_count - посчитать отчет\n"
            "/status - текущий статус\n"
            "/clear - очистить все\n"
            "/help - помощь"
        )
        await update.message.reply_text(message)

    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = (
            "🆘 Помощь\n\n"
            "Как использовать:\n"
            "1. Копируйте текст из истории транзакций\n"
            "2. Присылайте боту\n"
            "3. Нажимайте /finish_count для отчета\n\n"
            "Пример транзакций:\n"
            "#oscar max bnb\n"
            "Received: 19.99 #USDT ($19.99) from Binance\n"
            "#oscar max bnb\n"
            "Received: 29.99 #USDT ($29.99) from Binance\n\n"
            "Что будет в отчете:\n"
            "#oscar max bnb\n"
            "Транзакций: 2\n"
            "49.98 USDT"
        )
        await update.message.reply_text(message)

    async def _finish_count_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id in self.user_last_messages:
            del self.user_last_messages[user_id]

        if not self.calculator.transactions:
            message = "📭 У вас пока нет транзакций. Пришлите транзакции для расчета."
        else:
            message = self.calculator.get_total_report()
            self.calculator.clear_all()
            message += "\n\n✅ Отчет готов! Присылайте новые транзакции для следующего расчета."

        await update.message.reply_text(message)

    async def _status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id in self.user_last_messages:
            del self.user_last_messages[user_id]

        status = self.calculator.get_status()
        if not status:
            message = "📭 Нет активных транзакций. Пришлите транзакции чтобы начать."
        else:
            message = (
                f"📊 Текущий статус:\n"
                f"• Кошельков: {status['wallet_count']}\n"
                f"• Транзакций: {status['transaction_count']}\n\n"
                f"💡 Присылайте дополнительные транзакции или жмите /finish_count чтобы посчитать"
            )

        await update.message.reply_text(message)

    async def _clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id in self.user_last_messages:
            del self.user_last_messages[user_id]

        self.calculator.clear_all()
        message = "✅ Все транзакции очищены. Можете начинать заново!"
        await update.message.reply_text(message)

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text

        transactions_added = self.calculator.add_transactions(text)

        if transactions_added > 0:
            status = self.calculator.get_status()
            message = (
                f"✅ Обработано транзакций: {transactions_added}\n\n"
                f"📊 Текущий статус:\n"
                f"• Кошельков: {status['wallet_count']}\n"
                f"• Всего транзакций: {status['transaction_count']}\n\n"
                f"💡 Присылайте дополнительные транзакции или жмите /finish_count чтобы посчитать"
            )

            if user_id in self.user_last_messages:
                last_msg_id = self.user_last_messages[user_id]
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=last_msg_id,
                        text=message
                    )
                except:
                    new_message = await update.message.reply_text(message)
                    self.user_last_messages[user_id] = new_message.message_id
            else:
                new_message = await update.message.reply_text(message)
                self.user_last_messages[user_id] = new_message.message_id

        else:
            if user_id in self.user_last_messages:
                del self.user_last_messages[user_id]

            message = (
                "❌ Не удалось распознать транзакции\n\n"
                "Попробуйте скопировать как есть из истории:\n\n"
                "#oscar max bnb\n"
                "Received: 19.99 #USDT ($19.99) from Binance Hot wallet\n"
                "#bnb | Cielo | ViewTx\n\n"
                "Или:\n"
                "#Jack med trc20\n"
                "Received: 199.99 #USDT ($199.99) from MEXC Hot wallet\n"
                "#trc | Cielo | ViewTx"
            )
            await update.message.reply_text(message)

    def run(self):
        print("[BOT] Бот запускается...")
        self.application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    # Вставьте сюда свой токен
    TOKEN = "ВАШ_ТОКЕН_ЗДЕСЬ"

    print("[BOT] Запуск бота...")
    bot = TransactionBot(TOKEN)
    bot.run()