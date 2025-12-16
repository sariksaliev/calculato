import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',') if id.strip()]
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

    # Регулярные выражения для распознавания транзакций
    TRANSACTION_PATTERNS = {
        # Ищем сумму и валюту: "Received: 0.5 #BNB" или "Received: 130 #USDT"
        'amount_currency': r'Received:\s*([\d.]+)\s*#(\w+)',
        'coin': r'#(tron|bnb|eth|btc|sol|matic|avax|ftm|arb)\b',
        'wallet': r'from\s+(\w+\.\.\.\w+|\w{10,})',
        'dollar_value': r'\(\$([\d.]+)\)'
    }

    # Поддерживаемые монеты
    SUPPORTED_COINS = ['TRON', 'BNB', 'ETH', 'BTC', 'SOL', 'MATIC', 'AVAX', 'FTM', 'ARB']

    # Соответствие хэштегов сетей и их нативных монет
    NETWORK_TO_CURRENCY = {
        'tron': 'TRX',
        'bnb': 'BNB',
        'eth': 'ETH',
        'btc': 'BTC',
        'sol': 'SOL',
        'matic': 'MATIC',
        'avax': 'AVAX',
        'ftm': 'FTM',
        'arb': 'ETH',
    }