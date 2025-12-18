# bot.py
import os
import re
import logging
from collections import defaultdict
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)


class TransactionCalculator:
    """
    Новая логика (без условий по конкретным хэштегам):
    - Любая строка, начинающаяся с #, задаёт текущий "тег" (группа).
      Пример: "#oscar max bnb" или "#oscar max trc20"
    - Любая строка, где распознана сумма+валюта (желательно после 'Received:')
      добавляется как отдельная транзакция в текущий тег.
    - Кол-во "кошельков" в общей статистике считаем по уникальным адресам из 'from ...'
      (если адреса нет — используем тег как суррогатный идентификатор).
    - В отчёте суммируем по тегам и валютам (как вы и запросили).
    """

    def __init__(self):
        # tag -> list[tx]
        self.transactions = defaultdict(list)

        # Курсы для общей суммы (примерные)
        self.rates = {
            "USDT": 1.0, "USDC": 1.0,
            "BNB": 886.0, "TRX": 0.12,
            "ETH": 3500.0, "BTC": 68000.0, "SOL": 150.0,
        }

    @staticmethod
    def _normalize_tag(tag_line: str) -> str:
        """
        '#oscar max bnb' -> 'oscar max bnb'
        """
        tag = tag_line.strip()
        if tag.startswith("#"):
            tag = tag[1:]
        tag = re.sub(r"\s+", " ", tag).strip()
        return tag.lower()

    @staticmethod
    def _extract_address(line: str) -> str | None:
        m = re.search(r"\bfrom\s+([A-Za-z0-9\.]+)", line, re.IGNORECASE)
        return m.group(1) if m else None

    @staticmethod
    def _extract_amount_currency(line: str):
        """
        Достаём сумму и валюту.

        Сначала пытаемся наиболее точный формат:
          'Received: 121.97 #USDT ...'
        Если не найден — запасной вариант (менее строгий).

        Важно: делаем так, чтобы не “ловить” цифры из URL/txhash.
        """
        # 1) Приоритетный шаблон "Received: <amount> #<currency>"
        m = re.search(r"\breceived:\s*([0-9]+(?:\.[0-9]+)?)\s*#?([A-Za-z]{2,10})\b", line, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1)), m.group(2).upper()
            except ValueError:
                return None, None

        # 2) Запасной: ищем "<amount> #USDT" или "<amount> USDT" в тексте,
        # но стараемся не брать из ссылок: отрезаем всё после '(' с URL при необходимости.
        # Это упрощённая защита от мусора.
        safe_part = line.split("http")[0]  # до первой ссылки
        m2 = re.search(r"\b([0-9]+(?:\.[0-9]+)?)\s*#?([A-Za-z]{2,10})\b", safe_part, re.IGNORECASE)
        if m2:
            try:
                return float(m2.group(1)), m2.group(2).upper()
            except ValueError:
                return None, None

        return None, None

    def add_transactions(self, text: str) -> int:
        lines = text.splitlines()
        current_tag = None
        added = 0

        for raw in lines:
            line = raw.strip()
            if not line:
                continue

            # 1) Любой тег
            if line.startswith("#"):
                current_tag = self._normalize_tag(line)
                continue

            # 2) Транзакцию добавляем только если уже есть current_tag
            if not current_tag:
                continue

            amount, currency = self._extract_amount_currency(line)
            if amount is None or currency is None:
                continue

            address = self._extract_address(line)

            self.transactions[current_tag].append({
                "amount": amount,
                "currency": currency,
                "address": address
            })
            added += 1

        return added

    def clear_all(self):
        self.transactions.clear()

    def get_status(self):
        if not self.transactions:
            return None

        tx_count = sum(len(v) for v in self.transactions.values())

        unique_wallets = set()
        for tag, v in self.transactions.items():
            for tx in v:
                if tx.get("address"):
                    unique_wallets.add(tx["address"])
                else:
                    # если адрес не найден — считаем по тегу
                    unique_wallets.add(f"tag:{tag}")

        return {
            "wallet_count": len(unique_wallets),
            "transaction_count": tx_count
        }

    def get_total_report(self) -> str:
        if not self.transactions:
            return "📭 Нет транзакций для отчета."

        report_lines = []
        report_lines.append("📊 ОТЧЕТ ПО ТРАНЗАКЦИЯМ")
        report_lines.append(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        report_lines.append("─" * 40)

        total_usd = 0.0
        total_tx = 0

        unique_wallets = set()

        # Стабильный вывод: по алфавиту тегов
        for tag in sorted(self.transactions.keys()):
            tx_list = self.transactions[tag]
            if not tx_list:
                continue

            # Суммируем по валютам внутри тега
            sums = defaultdict(float)
            for tx in tx_list:
                sums[tx["currency"]] += tx["amount"]
                total_tx += 1

                if tx.get("address"):
                    unique_wallets.add(tx["address"])
                else:
                    unique_wallets.add(f"tag:{tag}")

            report_lines.append(f"\n#{tag}")
            report_lines.append(f"Транзакций: {len(tx_list)}")

            for cur in sorted(sums.keys()):
                amt = sums[cur]
                report_lines.append(f"{amt:.2f} {cur}")

                if cur in self.rates:
                    total_usd += amt * self.rates[cur]

        report_lines.append("\n" + "═" * 40)
        report_lines.append("📈 ОБЩАЯ СТАТИСТИКА:")
        report_lines.append(f"• Кошельков: {len(unique_wallets)}")
        report_lines.append(f"• Транзакций: {total_tx}")
        report_lines.append(f"• Общая сумма: ${total_usd:.2f} USD")

        return "\n".join(report_lines)


class TransactionBot:
    def __init__(self, token: str):
        self.token = token
        self.calculator = TransactionCalculator()
        self.user_last_messages = {}

        self.application = Application.builder().token(token).concurrent_updates(True).build()
        self._setup_handlers()

    def _setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self._start_command))
        self.application.add_handler(CommandHandler("help", self._help_command))
        self.application.add_handler(CommandHandler("finish_count", self._finish_count_command))
        self.application.add_handler(CommandHandler("status", self._status_command))
        self.application.add_handler(CommandHandler("clear", self._clear_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.user_last_messages.pop(update.effective_user.id, None)
        await update.message.reply_text(
            "🤖 Бот-калькулятор транзакций\n\n"
            "Правила:\n"
            "1) Любой хэштег (#...) задаёт группу.\n"
            "2) Любая строка с суммой (обычно 'Received: ...') считается транзакцией.\n"
            "3) В отчёте: суммирование по хэштегам + общий итог.\n\n"
            "Команды:\n"
            "/finish_count — сформировать отчет\n"
            "/status — текущий статус\n"
            "/clear — очистить\n"
            "/help — помощь"
        )

    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🆘 Помощь\n\n"
            "Пример ввода (как вы пересылаете из Cielo):\n"
            "#oscar max bnb\n"
            "Received: 29 #USDT ($29) from 0xef3a...13b20\n"
            "#oscar max trc20\n"
            "Received: 135 #USDT ($135) from TMJnLC...UfGb\n\n"
            "Важно:\n"
            "• Бот НЕ имеет списка 'разрешённых' хэштегов — принимает любые.\n"
            "• Транзакции считаются по факту строк с суммой.\n"
            "• Кошельки считаются по уникальным адресам из 'from ...'."
        )

    async def _finish_count_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.user_last_messages.pop(update.effective_user.id, None)

        if not self.calculator.transactions:
            message = "📭 У вас пока нет транзакций. Пришлите транзакции для расчёта."
        else:
            message = self.calculator.get_total_report()
            self.calculator.clear_all()
            message += "\n\n✅ Отчет готов! Присылайте новые транзакции для следующего расчета."

        await update.message.reply_text(message)

    async def _status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.user_last_messages.pop(update.effective_user.id, None)

        status = self.calculator.get_status()
        if not status:
            await update.message.reply_text("📭 Нет активных транзакций. Пришлите транзакции чтобы начать.")
            return

        await update.message.reply_text(
            "📊 Текущий статус:\n"
            f"• Кошельков: {status['wallet_count']}\n"
            f"• Транзакций: {status['transaction_count']}\n\n"
            "💡 Присылайте дополнительные транзакции или жмите /finish_count"
        )

    async def _clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.user_last_messages.pop(update.effective_user.id, None)
        self.calculator.clear_all()
        await update.message.reply_text("✅ Все транзакции очищены. Можно начинать заново!")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        added = self.calculator.add_transactions(update.message.text)

        if added <= 0:
            self.user_last_messages.pop(user_id, None)
            await update.message.reply_text(
                "❌ Не удалось распознать транзакции.\n\n"
                "Проверьте, что:\n"
                "1) Есть строка с хэштегом (начинается с #)\n"
                "2) Ниже есть строка с суммой (обычно 'Received: ...')"
            )
            return

        status = self.calculator.get_status()
        msg = (
            f"✅ Добавлено транзакций: {added}\n\n"
            "📊 Текущий статус:\n"
            f"• Кошельков: {status['wallet_count']}\n"
            f"• Всего транзакций: {status['transaction_count']}\n\n"
            "💡 Присылайте ещё или жмите /finish_count"
        )

        last_id = self.user_last_messages.get(user_id)
        if last_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=last_id,
                    text=msg
                )
                return
            except Exception:
                pass

        new_msg = await update.message.reply_text(msg)
        self.user_last_messages[user_id] = new_msg.message_id

    def run(self):
        self.application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TOKEN") or "ВАШ_ТОКЕН_ЗДЕСЬ"
    bot = TransactionBot(TOKEN)
    bot.run()
