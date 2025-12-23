# bot.py
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram import Update


@dataclass
class PendingTx:
    amount: float
    currency: str
    network: str
    wallet_short: str
    wallet_full: Optional[str] = None


class TransactionCalculator:
    def __init__(self):
        # transactions[network][wallet][currency] = sum_amount
        self.transactions = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
        self.total_transactions = 0  # количество обработанных строк Received

        # Примерные курсы для суммы в USD (можете менять)
        self.rates = {
            'USDT': 1.0,
            'USDC': 1.0,
            'BNB': 886.0,
            'TRX': 0.12,
            'ETH': 3500.0,
            'BTC': 68000.0,
            'SOL': 150.0,
        }

        # Received: 70 #USDT ($70) from ...
        self._re_amount_currency = re.compile(
            r'Received:\s*([\d.]+)\s*#?([A-Za-z0-9]{2,})',
            re.IGNORECASE
        )

        # from 0xef3a...13b20 OR from TMJnLC...UfGb OR from MEXC Hot wallet
        self._re_from_token = re.compile(r'\bfrom\s+([^\s\(\|]+)', re.IGNORECASE)

        # Address links (full addresses)
        self._re_bscscan_addr = re.compile(r'bscscan\.com/address/(0x[a-fA-F0-9]{40})', re.IGNORECASE)
        self._re_etherscan_addr = re.compile(r'etherscan\.io/address/(0x[a-fA-F0-9]{40})', re.IGNORECASE)
        self._re_tronscan_addr = re.compile(r'tronscan\.org/#/address/([A-Za-z0-9]{20,})', re.IGNORECASE)

        # Network tags like "#bnb |" or "#tron |"
        self._re_network_tag = re.compile(r'#(bnb|tron|eth)\b', re.IGNORECASE)

    # ---------- parsing helpers ----------

    def _detect_network_from_line(self, line: str) -> str:
        line_l = line.lower()

        if self._re_tronscan_addr.search(line):
            return "TRON"
        if self._re_bscscan_addr.search(line):
            return "BSC"
        if self._re_etherscan_addr.search(line):
            return "ETH"

        # fallback: tags
        m = self._re_network_tag.search(line)
        if m:
            tag = m.group(1).lower()
            if tag == "tron":
                return "TRON"
            if tag == "bnb":
                return "BSC"
            if tag == "eth":
                return "ETH"

        return "UNKNOWN"

    def _extract_full_wallet_from_links(self, line: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Возвращает (network, full_wallet) если нашли ссылку на address.
        """
        m = self._re_tronscan_addr.search(line)
        if m:
            return "TRON", m.group(1)

        m = self._re_bscscan_addr.search(line)
        if m:
            return "BSC", m.group(1)

        m = self._re_etherscan_addr.search(line)
        if m:
            return "ETH", m.group(1)

        return None, None

    def _extract_amount_currency(self, line: str) -> Tuple[Optional[float], Optional[str]]:
        m = self._re_amount_currency.search(line)
        if not m:
            return None, None
        try:
            amount = float(m.group(1))
            currency = m.group(2).upper()
            return amount, currency
        except ValueError:
            return None, None

    def _extract_wallet_short(self, line: str) -> Optional[str]:
        m = self._re_from_token.search(line)
        if not m:
            return None
        return m.group(1).strip()

    # ---------- core logic ----------

    def add_transactions(self, text: str) -> int:
        lines = text.strip().split('\n')
        added = 0
        pending: Optional[PendingTx] = None

        def finalize_pending():
            nonlocal pending, added
            if not pending:
                return

            wallet = pending.wallet_full or pending.wallet_short
            network = pending.network or "UNKNOWN"

            self.transactions[network][wallet][pending.currency] += pending.amount
            self.total_transactions += 1
            added += 1
            pending = None

        for raw in lines:
            line = raw.strip()
            if not line:
                continue

            # Если пришла строка Received — сначала закрываем прошлую pending, потом создаём новую
            if 'received:' in line.lower():
                finalize_pending()

                amount, currency = self._extract_amount_currency(line)
                if amount is None or currency is None:
                    continue

                wallet_short = self._extract_wallet_short(line)
                if not wallet_short:
                    continue

                # пытаемся взять полный адрес прямо из этой же строки
                net_link, wallet_full = self._extract_full_wallet_from_links(line)

                # сеть определим: сначала по ссылке, иначе по тегу/прочему
                network = net_link if net_link else self._detect_network_from_line(line)

                # если полный адрес уже есть — добавляем сразу, pending не нужен
                if wallet_full:
                    self.transactions[network][wallet_full][currency] += amount
                    self.total_transactions += 1
                    added += 1
                    pending = None
                else:
                    pending = PendingTx(
                        amount=amount,
                        currency=currency,
                        network=network,
                        wallet_short=wallet_short,
                        wallet_full=None
                    )
                continue

            # НЕ Received строка: если есть pending — попробуем подцепить полный address ссылкой
            if pending:
                net_link, wallet_full = self._extract_full_wallet_from_links(line)
                if wallet_full:
                    pending.wallet_full = wallet_full
                    # если сеть из ссылки точнее — обновим
                    if net_link and pending.network == "UNKNOWN":
                        pending.network = net_link
                else:
                    # иногда тег сети приходит отдельной строкой
                    if pending.network == "UNKNOWN":
                        pending.network = self._detect_network_from_line(line)

        # в конце закрываем pending, если осталась
        finalize_pending()
        return added

    def clear_all(self):
        self.transactions.clear()
        self.total_transactions = 0

    def get_status(self):
        if not self.transactions:
            return None
        wallet_count = sum(len(wallets) for wallets in self.transactions.values())
        return {
            "wallet_count": wallet_count,
            "transaction_count": self.total_transactions,
        }

    def get_total_report(self) -> str:
        if not self.transactions:
            return "📭 Нет транзакций для отчёта."

        report = []
        report.append("📊 ОТЧЁТ ПО ТРАНЗАКЦИЯМ")
        report.append(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        report.append("─" * 40)

        total_all_usd = 0.0

        # порядок сетей — чтобы было красиво
        network_order = ["BSC", "ETH", "TRON", "UNKNOWN"]
        networks = [n for n in network_order if n in self.transactions] + \
                   [n for n in sorted(self.transactions.keys()) if n not in network_order]

        for network in networks:
            report.append(f"\n🌐 {network}")
            wallets = self.transactions[network]

            for wallet in sorted(wallets.keys()):
                report.append(f"Wallet: {wallet}")
                wallet_usd_total = 0.0

                currencies = wallets[wallet]
                for cur in sorted(currencies.keys()):
                    amt = currencies[cur]
                    report.append(f"• {amt:.2f} {cur}")
                    if cur in self.rates:
                        wallet_usd_total += amt * self.rates[cur]

                report.append(f"Итого по кошельку: ${wallet_usd_total:.2f}\n")
                total_all_usd += wallet_usd_total

        wallet_count = sum(len(wallets) for wallets in self.transactions.values())

        report.append("═" * 40)
        report.append("📈 ОБЩАЯ СТАТИСТИКА:")
        report.append(f"• Кошельков: {wallet_count}")
        report.append(f"• Транзакций: {self.total_transactions}")
        report.append(f"• Общая сумма: ${total_all_usd:.2f} USD")

        return "\n".join(report)


class TransactionBot:
    def __init__(self, token: str):
        self.calculator = TransactionCalculator()
        self.application = Application.builder().token(token).build()
        self._setup_handlers()

    def _setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self._start))
        self.application.add_handler(CommandHandler("help", self._help))
        self.application.add_handler(CommandHandler("status", self._status))
        self.application.add_handler(CommandHandler("finish_count", self._finish))
        self.application.add_handler(CommandHandler("clear", self._clear))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))

    async def _start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 Бот-калькулятор транзакций\n\n"
            "Присылайте текст с блоками Cielo/Received.\n"
            "Я считаю по сети + адресу кошелька (беру полный адрес из ссылки).\n\n"
            "Команды:\n"
            "/status — статус\n"
            "/finish_count — отчёт и очистка\n"
            "/clear — очистить\n"
            "/help — помощь"
        )

    async def _help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🆘 Формат, который понимаю:\n"
            "Received: 70 #USDT ($70) from TUpHuD...J2b9 (https://tronscan.org/#/address/TUpHuD...)\n"
            "Received: 15 #USDT ($15) from 0xef3a...13b20 (https://bscscan.com/address/0x...)\n\n"
            "Если ссылка на address приходит следующей строкой — я тоже подцеплю её к транзакции."
        )

    async def _status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        st = self.calculator.get_status()
        if not st:
            await update.message.reply_text("📭 Нет активных транзакций. Пришлите транзакции, чтобы начать.")
            return
        await update.message.reply_text(
            f"📊 Текущий статус:\n"
            f"• Кошельков: {st['wallet_count']}\n"
            f"• Транзакций: {st['transaction_count']}\n\n"
            f"💡 Присылайте ещё или жмите /finish_count"
        )

    async def _clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.calculator.clear_all()
        await update.message.reply_text("✅ Все транзакции очищены. Можно начинать заново!")

    async def _finish(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.calculator.transactions:
            await update.message.reply_text("📭 Пока нет транзакций. Пришлите данные.")
            return
        report = self.calculator.get_total_report()
        self.calculator.clear_all()
        report += "\n\n✅ Отчёт готов! Можете присылать новые транзакции."
        await update.message.reply_text(report)

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        added = self.calculator.add_transactions(update.message.text)
        if added > 0:
            st = self.calculator.get_status()
            await update.message.reply_text(
                f"✅ Обработано транзакций: {added}\n\n"
                f"📊 Статус:\n"
                f"• Кошельков: {st['wallet_count']}\n"
                f"• Всего транзакций: {st['transaction_count']}\n\n"
                f"💡 Жмите /finish_count для отчёта"
            )
        else:
            await update.message.reply_text(
                "❌ Не удалось распознать транзакции.\n\n"
                "Нужна строка вида:\n"
                "Received: <amount> #<CUR> ... from ... (ссылка на .../address/...)\n"
            )

    def run(self):
        self.application.run_polling()
