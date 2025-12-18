# bot.py
import os
import re
import logging
from collections import defaultdict
from datetime import datetime

from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram import Update

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


class TransactionCalculator:
    """
    Логика:
    - current_wallet определяется по хэштегу/строке (#oscar max bnb / #oscar max trc20 и т.д.)
    - каждая найденная сумма+валюта = отдельная транзакция
    - "кошельки" в общей статистике считаются по уникальным адресам after 'from ...'
    """
    def __init__(self):
        # Группируем для отчёта по "типам" (oscar_max_bnb и т.п.)
        self.transactions = defaultdict(list)

        # Курсы для пересчёта в USD (примерные/ручные)
        self.rates = {
            'USDT': 1.0, 'USDC': 1.0,
            'BNB': 886.0, 'TRX': 0.12,
            'ETH': 3500.0, 'BTC': 68000.0, 'SOL': 150.0,
        }

    def _detect_wallet_key(self, line_lower: str):
        """
        Определяем группу (wallet key) по строке/хэштегу.
        Возвращает ключ или None.
        """
        # Схема на основе ваших текущих правил
        if ('oscar' in line_lower) and ('max' in line_lower) and ('bnb' in line_lower):
            return 'oscar_max_bnb'
        if ('oscar' in line_lower) and ('max' in line_lower) and ('trc' in line_lower):
            return 'oscar_max_trc20'
        if ('oscar' in line_lower) and (('mini' in line_lower) or ('mimi' in line_lower)) and ('bnb' in line_lower):
            return 'oscar_mini_bnb'
        if ('jack' in line_lower) and ('trc' in line_lower):
            return 'jack_trc20'

        return None

    def _extract_tx(self, line: str):
        """
        Извлекаем из строки:
        - amount (float)
        - currency (str)
        - address (str|None) из "from XXXXX"
        - tx_url (str|None) если есть ссылка на bscscan/tronscan (опционально)

        Важно: НЕ привязано к 'Received:'.
        """
        line_stripped = line.strip()

        # 1) amount + currency (учитываем варианты "121.97 #USDT" и "121.97 USDT")
        m = re.search(r'(\d+(?:\.\d+)?)\s*#?([A-Za-z]{2,})', line_stripped, re.IGNORECASE)
        if not m:
            return None

        try:
            amount = float(m.group(1))
            currency = m.group(2).upper()
        except ValueError:
            return None

        # 2) address после "from ..."
        address = None
        m_addr = re.search(r'\bfrom\s+([A-Za-z0-9\.]+)', line_stripped, re.IGNORECASE)
        if m_addr:
            address = m_addr.group(1)

        # 3) tx url (не обязательно)
        tx_url = None
        m_url = re.search(r'(https?://\S+)', line_stripped, re.IGNORECASE)
        if m_url:
            tx_url = m_url.group(1)

        return {
            "amount": amount,
            "currency": currency,
            "address": address,
            "tx_url": tx_url
        }

    def add_transactions(self, text: str) -> int:
        """
        Принимает текст (может быть одним сообщением с несколькими строками).
        Находит wallet_key и транзакции.
        Каждая найденная сумма = отдельная транзакция.
        """
        lines = text.splitlines()
        current_wallet = None
        added = 0

        for raw in lines:
            line = raw.strip()
            if not line:
                continue

            line_lower = line.lower()

            # 1) Обновляем current_wallet если нашли маркер
            #    (строка может быть "#oscar max bnb" или просто "oscar max bnb")
            wallet_key = None
            if line_lower.startswith('#'):
                wallet_key = self._detect_wallet_key(line_lower[1:])
            else:
                wallet_key = self._detect_wallet_key(line_lower)

            if wallet_key:
                current_wallet = wallet_key
                continue

            # 2) Пытаемся извлечь транзакцию из любой строки
            #    но добавляем только если уже знаем current_wallet
            if not current_wallet:
                continue

            tx = self._extract_tx(line)
            if not tx:
                continue

            self.transactions[current_wallet].append(tx)
            added += 1

        return added

    def get_status(self):
        if not self.transactions:
            return None

        tx_count = sum(len(v) for v in self.transactions.values())

        unique_addresses = set()
        for v in self.transactions.values():
            for tx in v:
                addr = tx.get("address")
                if addr:
                    unique_addresses.add(addr)

        return {
            "wallet_count": len(unique_addresses),     # реальное число кошельков по адресам
            "transaction_count": tx_count
        }

    def clear_all(self):
        self.transactions.clear()

    def get_total_report(self) -> str:
        if not self.transactions:
            return "📭 Нет транзакций для отчета."

        report_lines = []
        report_lines.append("📊 ОТЧЕТ ПО ТРАНЗАКЦИЯМ")
        report_lines.append(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        report_lines.append("─" * 40)

        wallet_titles = {
            'oscar_max_bnb': '#oscar max bnb',
            'oscar_max_trc20': '#oscar max trc20',
            'oscar_mini_bnb': '#oscar mini bnb',
            'jack_trc20': '#jack med trc20',
        }

        wallet_order = ['oscar_max_bnb', 'oscar_max_trc20', 'oscar_mini_bnb', 'jack_trc20']

        total_usd = 0.0
        total_transactions = 0

        unique_addresses = set()

        for wallet_key in wallet_order:
            tx_list = self.transactions.get(wallet_key, [])
            if not tx_list:
                continue

            report_lines.append(f"\n{wallet_titles.get(wallet_key, wallet_key)}")
            report_lines.append(f"Транзакций: {len(tx_list)}")

            for tx in tx_list:
                amount = tx["amount"]
                currency = tx["currency"]
                addr = tx.get("address")

                # Детальная строка по каждой транзакции
                if addr:
                    report_lines.append(f"• {amount:.2f} {currency}  (from {addr})")
                    unique_addresses.add(addr)
                else:
                    report_lines.append(f"• {amount:.2f} {currency}")

                if currency in self.rates:
                    total_usd += amount * self.rates[currency]

            total_transactions += len(tx_list)

        # Общее число кошельков — по уникальным адресам
        wallet_count = len(unique_addresses)

        report_lines.append("\n" + "═" * 40)
        report_lines.append("📈 ОБЩАЯ СТАТИСТИКА:")
        report_lines.append(f"• Кошельков: {wallet_count}")
        report_lines.append(f"• Транзакций: {total_transactions}")
        report_lines.append(f"• Общая сумма: ${total_usd:.2f} USD")

        return "\n".join(report_lines)


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
        self.user_last_messages.pop(user_id, None)

        message = (
            "🤖 Бот-калькулятор транзакций\n\n"
            "Пришлите транзакции текстом (можно пересылкой).\n"
            "Каждая найденная сумма = отдельная транзакция.\n"
            "Кошельки считаются по уникальным адресам из 'from ...'.\n\n"
            "Когда всё готово — нажмите /finish_count\n\n"
            "Команды:\n"
            "/finish_count — сформировать отчет\n"
            "/status — текущий статус\n"
            "/clear — очистить\n"
            "/help — помощь"
        )
        await update.message.reply_text(message)

    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = (
            "🆘 Помощь\n\n"
            "Как использовать:\n"
            "1) Пересылайте сообщения с транзакциями\n"
            "2) В тексте должен встречаться маркер кошелька, например:\n"
            "   #oscar max bnb\n"
            "   #oscar max trc20\n"
            "3) Затем строки вида:\n"
            "   Received: 121.97 #USDT ($121.97) from 0xaa22...dee02\n\n"
            "Важно:\n"
            "• Каждая сумма считается отдельной транзакцией\n"
            "• Кошельки считаются по уникальным адресам после 'from'\n"
        )
        await update.message.reply_text(message)

    async def _finish_count_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        self.user_last_messages.pop(user_id, None)

        if not self.calculator.transactions:
            message = "📭 У вас пока нет транзакций. Пришлите транзакции для расчёта."
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
            message = "📭 Нет активных транзакций. Пришлите транзакции чтобы начать."
        else:
            message = (
                f"📊 Текущий статус:\n"
                f"• Кошельков: {status['wallet_count']}\n"
                f"• Транзакций: {status['transaction_count']}\n\n"
                f"💡 Присылайте дополнительные транзакции или жмите /finish_count"
            )

        await update.message.reply_text(message)

    async def _clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        self.user_last_messages.pop(user_id, None)

        self.calculator.clear_all()
        await update.message.reply_text("✅ Все транзакции очищены. Можно начинать заново!")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text

        added = self.calculator.add_transactions(text)

        if added > 0:
            status = self.calculator.get_status()
            message = (
                f"✅ Добавлено транзакций: {added}\n\n"
                f"📊 Текущий статус:\n"
                f"• Кошельков: {status['wallet_count']}\n"
                f"• Всего транзакций: {status['transaction_count']}\n\n"
                f"💡 Присылайте ещё или жмите /finish_count"
            )

            # Обновляем одно “статус-сообщение” вместо спама
            last_msg_id = self.user_last_messages.get(user_id)
            if last_msg_id:
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=last_msg_id,
                        text=message
                    )
                    return
                except Exception:
                    pass

            new_message = await update.message.reply_text(message)
            self.user_last_messages[user_id] = new_message.message_id
            return

        # Если ничего не распознали
        self.user_last_messages.pop(user_id, None)
        await update.message.reply_text(
            "❌ Не удалось распознать транзакции.\n\n"
            "Убедитесь, что в сообщении есть:\n"
            "1) строка с кошельком, например: #oscar max bnb\n"
            "2) строка с суммой, например: Received: 29 #USDT ($29) from 0x...\n"
        )

    def run(self):
        print("[BOT] Бот запускается...")
        self.application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    # Рекомендуется хранить токен в .env / переменных окружения
    # Например: export BOT_TOKEN="123:ABC"
    TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TOKEN") or "ВАШ_ТОКЕН_ЗДЕСЬ"

    if TOKEN == "ВАШ_ТОКЕН_ЗДЕСЬ":
        print("[BOT] ВНИМАНИЕ: TOKEN не задан. Укажите BOT_TOKEN в окружении или вставьте токен в код.")
    bot = TransactionBot(TOKEN)
    bot.run()
