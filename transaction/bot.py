import re
from collections import defaultdict
from datetime import datetime


class TransactionCalculator:
    def __init__(self):
        # wallet_id -> currency -> amount_sum
        self.transactions = defaultdict(lambda: defaultdict(float))
        self.total_transactions = 0  # количество распознанных строк Received

        self.rates = {
            'USDT': 1.0,
            'USDC': 1.0,
            'BNB': 886.0,
            'TRX': 0.12,
            'ETH': 3500.0,
            'BTC': 68000.0,
            'SOL': 150.0,
        }

        self._re_amount_currency = re.compile(
            r'Received:\s*([\d.]+)\s*#([A-Za-z0-9]{2,})',
            re.IGNORECASE
        )

        # 1) Полные адреса из ссылок (Cielo часто даёт полный адрес в url)
        self._re_tronscan_addr = re.compile(r'tronscan\.org/#/address/([A-Za-z0-9]{20,})', re.IGNORECASE)
        self._re_etherscan_addr = re.compile(r'etherscan\.io/address/(0x[a-fA-F0-9]{40})', re.IGNORECASE)
        self._re_bscscan_addr = re.compile(r'bscscan\.com/address/(0x[a-fA-F0-9]{40})', re.IGNORECASE)

        # 2) Фолбэк: то, что идёт сразу после "from" до пробела/скобки/|
        self._re_from_token = re.compile(r'\bfrom\s+([^\s\(\|]+)', re.IGNORECASE)

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
            amount = float(m.group(1))
            currency = m.group(2).upper()
            return amount, currency
        except ValueError:
            return None, None

    def _extract_wallet_id(self, line: str):
        # Сначала пытаемся вытащить полный адрес из ссылок
        for rx in (self._re_tronscan_addr, self._re_etherscan_addr, self._re_bscscan_addr):
            m = rx.search(line)
            if m:
                return m.group(1)

        # Если ссылок нет — берём токен после from (может быть сокращённый)
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
