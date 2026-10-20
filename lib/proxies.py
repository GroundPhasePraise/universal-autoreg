"""proxies.py — пул прокси: SQLite (таблица pool) или txt-файл, live-проверка.

Правила (из практики):
- sticky-прокси на ВЕСЬ флоу одного аккаунта (verify/register/login с одного IP, иначе 403 anti-bot)
- live-тест перед волной (ThreadPool, ~20с на 250 прокси)
- free-пул протухает за часы — перепроверять каждый запуск
- panel/new-api банят прокси-IP (403) — панели напрямую, GH через прокси
"""
import os, random, socket, sqlite3, threading, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(__file__)
DB = os.environ.get("UA_PROXY_DB", os.path.join(HERE, "..", "data", "proxies.db"))
TXT = os.environ.get("UA_PROXY_TXT", os.path.join(HERE, "..", "data", "proxies.txt"))


def load_pool():
    """Все живые прокси: сначала sqlite, потом txt. Формат: http://user:pass@host:port"""
    out = []
    if os.path.exists(DB):
        try:
            con = sqlite3.connect(DB)
            rows = con.execute("SELECT url FROM pool WHERE alive=1").fetchall()
            con.close()
            out += [r[0] for r in rows]
        except sqlite3.Error:
            pass
    if os.path.exists(TXT):
        out += [l.strip() for l in open(TXT, encoding="utf-8") if l.strip() and not l.startswith("#")]
    return list(dict.fromkeys(out))


def check_one(url, test_url="https://github.com/login", timeout=10):
    """Проверить прокси. ВАЖНО: verify=True — SSL-MITM прокси (verify=False пропускал их)
    Firefox/Camoufox убивает SEC_ERROR_UNKNOWN_ISSUER."""
    try:
        import ssl
        ctx = ssl.create_default_context()
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": url, "https": url}),
            urllib.request.HTTPSHandler(context=ctx))
        req = urllib.request.Request(test_url, headers={"User-Agent": "Mozilla/5.0"})
        with opener.open(req, timeout=timeout) as r:
            return url, r.status in (200, 302)
    except Exception:
        return url, False


def live_pool(test_url="https://github.com/login", workers=40, limit=None):
    pool = load_pool()
    if limit:
        pool = pool[:limit]
    good = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for url, ok in ex.map(lambda u: check_one(u, test_url), pool):
            if ok:
                good.append(url)
    return good


class StickyRotator:
    """Один прокси = один аккаунт (sticky). Авто-ротация при смерти opener'а."""

    def __init__(self, pool=None, test_url="https://github.com/login"):
        self.pool = list(pool if pool is not None else live_pool(test_url))
        random.shuffle(self.pool)
        self._i = 0
        self._lock = threading.Lock()

    def next(self):
        with self._lock:
            if not self.pool:
                return None
            p = self.pool[self._i % len(self.pool)]
            self._i += 1
            return p

    def ban(self, url):
        with self._lock:
            if url in self.pool:
                self.pool.remove(url)

    def __len__(self):
        return len(self.pool)


if __name__ == "__main__":
    pool = load_pool()
    print(f"pool total: {len(pool)}")
    live = live_pool(limit=min(len(pool), 100))
    print(f"live (first 100 tested): {len(live)}")
