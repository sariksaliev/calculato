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
    hashtag: Optional[str] = None


class TransactionCalculator:
    def __init__(self):
        # transactions[hashtag][currency] = sum_amount
        # hashtag хранится как есть, например "#oscar max bnb"
        self.transactions = defaultdict(lambda: defaultdict(float))
        self.total_transactions = 0  # количество обработанных строк Received
        self.wallets_seen = set()  # для подсчета уникальных кошельков

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
        
        # Хештег в формате #something ... network (например, #oscar max bnb, #oscar max trc20)
        self._re_hashtag = re.compile(r'#([^\s]+(?:\s+[^\s]+)*)', re.IGNORECASE)

    # ---------- parsing helpers ----------

    def _extract_hashtag_from_text(self, text: str) -> Optional[str]:
        """Извлекает хештег из текста (например, #oscar max bnb)"""
        lines = text.strip().split('\n')
        for line in lines:
            line = line.strip()
            # Пропускаем строки с "Received:" и служебные строки
            if 'received:' in line.lower() or 'переслано' in line.lower() or 'forwarded' in line.lower():
                continue
            # Ищем хештег в начале строки
            if line.startswith('#'):
                # Если в строке есть |, берем только часть до |
                if '|' in line:
                    line = line.split('|')[0].strip()
                # Извлекаем весь хештег (может быть многословным: #oscar max bnb)
                # Берем все слова, начинающиеся с #
                parts = line.split()
                if parts and parts[0].startswith('#'):
                    hashtag = ' '.join(parts)  # Берем все слова как хештег
                    hashtag_lower = hashtag.lower()
                    # Проверяем, что это не просто тег сети (#bnb, #tron)
                    simple_tags = ['#bnb', '#tron', '#eth', '#btc', '#sol']
                    if hashtag_lower not in simple_tags:
                        # Если хештег содержит пробелы (многословный) или длиннее простого тега - это хештег кошелька
                        if ' ' in hashtag or len(hashtag) > 5:
                            return hashtag
        return None

    def _detect_network_from_hashtag(self, hashtag: str) -> str:
        """Определяет сеть из хештега (например, #oscar max bnb -> BSC, #oscar max trc20 -> TRON)"""
        hashtag_lower = hashtag.lower()
        
        # Проверяем различные варианты сетей в хештеге
        if 'trc20' in hashtag_lower or 'tron' in hashtag_lower:
            return "TRON"
        if 'bnb' in hashtag_lower:
            return "BSC"
        if 'eth' in hashtag_lower or 'ethereum' in hashtag_lower:
            return "ETH"
        if 'btc' in hashtag_lower or 'bitcoin' in hashtag_lower:
            return "BTC"
        if 'sol' in hashtag_lower or 'solana' in hashtag_lower:
            return "SOL"
        
        return "UNKNOWN"

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
        current_hashtag = None
        network_from_hashtag = None
        
        # Сначала ищем хештег во всем тексте (для случая одного хештега на все транзакции)
        global_hashtag = self._extract_hashtag_from_text(text)
        if global_hashtag:
            network_from_hashtag = self._detect_network_from_hashtag(global_hashtag)

        def finalize_pending():
            nonlocal pending, added
            if not pending:
                return

            # Используем хештег для группировки, если он есть
            if pending.hashtag:
                hashtag_key = pending.hashtag
            else:
                # Если хештега нет, используем сеть как ключ (fallback)
                hashtag_key = f"#{pending.network}"

            # Добавляем транзакцию по хештегу
            self.transactions[hashtag_key][pending.currency] += pending.amount
            self.total_transactions += 1
            added += 1
            
            # Сохраняем кошелек для статистики
            wallet = pending.wallet_full or pending.wallet_short
            if wallet:
                self.wallets_seen.add(wallet)
            
            pending = None

        for i, raw in enumerate(lines):
            line = raw.strip()
            if not line:
                continue

            # Проверяем, является ли строка хештегом
            if line.startswith('#') and '|' not in line:
                # Ищем хештег в этой строке
                potential_hashtag = self._extract_hashtag_from_text(line)
                if potential_hashtag:
                    current_hashtag = potential_hashtag
                    network_from_hashtag = self._detect_network_from_hashtag(potential_hashtag)
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

                # Используем текущий хештег или глобальный
                hashtag_to_use = current_hashtag or global_hashtag

                # сеть определим: сначала из хештега, потом по ссылке, иначе по тегу/прочему
                if network_from_hashtag and network_from_hashtag != "UNKNOWN":
                    network = network_from_hashtag
                elif net_link:
                    network = net_link
                else:
                    network = self._detect_network_from_line(line)

                # если полный адрес уже есть — добавляем сразу, pending не нужен
                if wallet_full:
                    hashtag_key = hashtag_to_use if hashtag_to_use else f"#{network}"
                    self.transactions[hashtag_key][currency] += amount
                    self.total_transactions += 1
                    added += 1
                    self.wallets_seen.add(wallet_full)
                    pending = None
                else:
                    pending = PendingTx(
                        amount=amount,
                        currency=currency,
                        network=network,
                        wallet_short=wallet_short,
                        wallet_full=None,
                        hashtag=hashtag_to_use
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
        self.wallets_seen.clear()

    def get_status(self):
        if not self.transactions:
            return None
        wallet_count = len(self.wallets_seen)
        return {
            "wallet_count": wallet_count,
            "transaction_count": self.total_transactions,
        }

    def get_total_report(self) -> str:
        if not self.transactions:
            return "📭 Нет транзакций для отчёта."

        report = []
        total_all_usd = 0.0

        # Сортируем хештеги для красивого вывода
        hashtags = sorted(self.transactions.keys())

        for hashtag in hashtags:
            currencies = self.transactions[hashtag]
            hashtag_total_usd = 0.0
            
            # Выводим хештег
            report.append(hashtag)
            
            # Выводим суммы по валютам
            for cur in sorted(currencies.keys()):
                amt = currencies[cur]
                report.append(f"{amt:.2f} {cur}")
                if cur in self.rates:
                    hashtag_total_usd += amt * self.rates[cur]
            
            total_all_usd += hashtag_total_usd

        # Разделитель
        report.append("─" * 40)
        
        # Общая статистика
        report.append("📈 ОБЩАЯ СТАТИСТИКА:")
        wallet_count = len(self.wallets_seen)
        report.append(f"• Кошельков: {wallet_count}")
        report.append(f"• Транзакций: {self.total_transactions}")
        report.append(f"• Общая сумма: ${total_all_usd:.2f} USD")

        return "\n".join(report)


class TransactionBot:
    def __init__(self, token: str):
        self.calculator = TransactionCalculator()
        self.application = Application.builder().token(token).build()
        self.last_hashtag = {}  # user_id -> hashtag для хранения последнего хештега пользователя
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
        user_id = update.effective_user.id
        self.calculator.clear_all()
        if user_id in self.last_hashtag:
            del self.last_hashtag[user_id]
        await update.message.reply_text("✅ Все транзакции очищены. Можно начинать заново!")

    async def _finish(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.calculator.transactions:
            await update.message.reply_text("📭 Пока нет транзакций. Пришлите данные.")
            return
        user_id = update.effective_user.id
        report = self.calculator.get_total_report()
        self.calculator.clear_all()
        if user_id in self.last_hashtag:
            del self.last_hashtag[user_id]
        report += "\n\n✅ Отчет готов! Присылайте новые транзакции для следующего расчета."
        await update.message.reply_text(report)

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text
        
        # Проверяем, является ли сообщение только хештегом (без транзакций)
        hashtag = self.calculator._extract_hashtag_from_text(text)
        has_received = 'received:' in text.lower()
        
        if hashtag and not has_received:
            # Сообщение содержит только хештег(и) - сохраняем последний
            lines = text.strip().split('\n')
            saved_hashtags = []
            for line in lines:
                line = line.strip()
                if line.startswith('#'):
                    h = self.calculator._extract_hashtag_from_text(line)
                    if h:
                        saved_hashtags.append(h)
                        self.last_hashtag[user_id] = h
            if saved_hashtags:
                hashtags_text = '\n'.join(saved_hashtags)
                await update.message.reply_text(
                    f"✅ Хештег(и) сохранён(ы):\n{hashtags_text}\n\n"
                    f"💡 Будет использован последний: {self.last_hashtag[user_id]}\n"
                    f"Теперь пришлите транзакции для этого хештега."
                )
            else:
                await update.message.reply_text("❌ Не удалось распознать хештег.")
            return
        
        # Если есть сохраненный хештег и в тексте нет хештега, добавляем его в начало
        if self.last_hashtag.get(user_id) and not hashtag:
            text = f"{self.last_hashtag[user_id]}\n{text}"
            hashtag = self.last_hashtag[user_id]
        
        added = self.calculator.add_transactions(text)
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
