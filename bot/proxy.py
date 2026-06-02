import random
import os

def load_proxies_from_file(file_path='proxy.txt'):
    if not os.path.exists(file_path):
        return []
    with open(file_path, 'r') as f:
        return [line.strip() for line in f if line.strip()]

def format_proxy(proxy):
    parts = proxy.split(':')
    if len(parts) != 4:
        return None
    host, port, username, password = parts
    return f"http://{username}:{password}@{host}:{port}"

def proxies(file_path='proxy.txt', max_retries=1, library="requests"):
    proxy_list = load_proxies_from_file(file_path)
    if not proxy_list:
        return None
    proxy = random.choice(proxy_list)
    formatted = format_proxy(proxy)
    if formatted:
        return {'http': formatted, 'https': formatted}
    return None

async def proxies_aiohttp(file_path='proxy.txt', max_retries=1):
    return proxies(file_path)
