import sys
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

import requests
import time
import random
import os
import signal
from collections import deque

# ===== 설정 =====
DISCORD_WEBHOOK_URLS = [
    os.environ.get("DISCORD_WEBHOOK_URL_1"),
    os.environ.get("DISCORD_WEBHOOK_URL_2"),
]
DISCORD_WEBHOOK_URLS = [url for url in DISCORD_WEBHOOK_URLS if url]

KEYWORDS = [
    "뉴진스",
    "뉴진스 배너",
    "뉴진스 코카콜라",
    "뉴진스 배그"
]

CHECK_INTERVAL_MIN = 15
CHECK_INTERVAL_MAX = 25
KEYWORD_DELAY_MIN = 1.0
KEYWORD_DELAY_MAX = 2.5
LONG_BREAK_CHANCE = 0.1
LONG_BREAK_MIN = 60
MAX_RETRIES = 5
MAX_SEEN_PRODUCTS = 2000     # seen_products 최대 크기
DISCORD_TIMEOUT = 10         # 디스코드 요청 타임아웃
DISCORD_RETRIES = 2          # 디스코드 전송 재시도 횟수
# ================

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
]

SEC_CH_UA_MAP = {
    "Chrome/131": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Chrome/130": '"Google Chrome";v="130", "Chromium";v="130", "Not_A Brand";v="24"',
}

def get_sec_ch_ua(ua: str):
    if "Chrome/131" in ua:
        return SEC_CH_UA_MAP["Chrome/131"]
    if "Chrome/130" in ua:
        return SEC_CH_UA_MAP["Chrome/130"]
    return None

def get_headers():
    ua = random.choice(USER_AGENTS)
    headers = {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.bunjang.co.kr/",
        "Origin": "https://www.bunjang.co.kr",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    }
    sec_ch_ua = get_sec_ch_ua(ua)
    if sec_ch_ua:
        headers["sec-ch-ua"] = sec_ch_ua
        headers["sec-ch-ua-mobile"] = "?0"
        headers["sec-ch-ua-platform"] = '"Windows"'
    return headers

# seen_products: set + deque로 최대 크기 제한 (메모리 누수 방지)
seen_products = set()
seen_order = deque(maxlen=MAX_SEEN_PRODUCTS)

# 매물 카운터 (봇 시작 후 알림 보낸 매물 순번)
item_counter = 0

session = requests.Session()

def add_seen(product_id):
    """seen_products에 추가하면서 최대 크기 유지"""
    if product_id in seen_products:
        return
    if len(seen_order) >= MAX_SEEN_PRODUCTS:
        old = seen_order[0]  # 가장 오래된 항목
        seen_products.discard(old)
    seen_products.add(product_id)
    seen_order.append(product_id)

def post_discord(url, data):
    """디스코드 전송 (timeout + 재시도)"""
    for attempt in range(1, DISCORD_RETRIES + 2):
        try:
            r = requests.post(url, json=data, timeout=DISCORD_TIMEOUT)
            if r.status_code in (200, 204):
                return True
            print(f"디스코드 응답 {r.status_code} ({url[:40]}...) 시도 {attempt}")
        except Exception as e:
            print(f"디스코드 전송 오류 ({url[:40]}...): {e} 시도 {attempt}")
        time.sleep(2)
    return False

def send_discord(message):
    data = {"content": message}
    for url in DISCORD_WEBHOOK_URLS:
        post_discord(url, data)

def send_discord_embed(keyword, name, price, link, image_url, index):
    embed = {
        "title": f"🔔 [{index}번째] {name}",
        "url": link,
        "color": 0xFF6600,
        "fields": [
            {"name": "키워드", "value": keyword, "inline": True},
            {"name": "가격", "value": f"{int(price):,}원" if str(price).isdigit() else f"{price}원", "inline": True},
        ],
    }
    if image_url:
        embed["image"] = {"url": image_url}
    data = {"embeds": [embed]}
    for url in DISCORD_WEBHOOK_URLS:
        post_discord(url, data)

def search_bunjang(keyword):
    url = f"https://api.bunjang.co.kr/api/1/find_v2.json?q={keyword}&n=30&page=0&order=date"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, headers=get_headers(), timeout=10)

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                wait = max(retry_after, 60) * attempt
                print(f"[{keyword}] 429 Rate Limit. {wait}초 대기 후 재시도... (시도 {attempt}/{MAX_RETRIES})")
                time.sleep(wait)
                continue

            if response.status_code != 200:
                wait = (2 ** attempt) * 5
                print(f"[{keyword}] HTTP {response.status_code}. {wait}초 대기 후 재시도... (시도 {attempt}/{MAX_RETRIES})")
                time.sleep(wait)
                continue

            data = response.json()
            new_items = []
            for item in data.get("list", []):
                product_id = str(item.get("pid", ""))
                if product_id and product_id not in seen_products:
                    add_seen(product_id)
                    name = item.get("name", "상품명 없음")
                    price = item.get("price", "")
                    link = f"https://www.bunjang.co.kr/products/{product_id}"
                    image = item.get("product_image", "").replace("{res}", "360")
                    new_items.append((name, price, link, image or ""))
            return new_items

        except Exception as e:
            wait = (2 ** attempt) * 5
            print(f"[{keyword}] 오류: {e}. {wait}초 대기 후 재시도... (시도 {attempt}/{MAX_RETRIES})")
            time.sleep(wait)

    print(f"[{keyword}] 최대 재시도 초과. 이번 사이클 건너뜀.")
    return []

def monitor():
    global item_counter

    print("=" * 40)
    print("번개장터 감시 봇 시작")
    print(f"키워드: {KEYWORDS}")
    print(f"확인 간격: {CHECK_INTERVAL_MIN}~{CHECK_INTERVAL_MAX}초 (랜덤)")
    print(f"웹훅 개수: {len(DISCORD_WEBHOOK_URLS)}")
    print("=" * 40)
    send_discord("✅ 번개장터 감시 봇이 시작되었습니다!")

    print("기존 상품 스캔 중...")
    for keyword in KEYWORDS:
        search_bunjang(keyword)
        time.sleep(random.uniform(KEYWORD_DELAY_MIN, KEYWORD_DELAY_MAX))
    print("감시 시작!\n")

    while True:
        # 가끔 긴 휴식 (걸리면 이번 사이클은 휴식만)
        if random.random() < LONG_BREAK_CHANCE:
            print(f"[{time.strftime('%H:%M:%S')}] 긴 휴식 중... ({LONG_BREAK_MIN}초)")
            time.sleep(LONG_BREAK_MIN)
            continue

        interval = random.uniform(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX)
        print(f"[{time.strftime('%H:%M:%S')}] 확인 중... (다음 확인: {interval:.0f}초 후)")

        # 키워드 순서 셔플 (패턴 회피)
        shuffled = KEYWORDS.copy()
        random.shuffle(shuffled)

        for keyword in shuffled:
            new_items = search_bunjang(keyword)
            for name, price, link, image_url in new_items:
                item_counter += 1
                print(f"[{item_counter}번째] 새 상품: {name} / {price}원")
                send_discord_embed(keyword, name, price, link, image_url, item_counter)
            time.sleep(random.uniform(KEYWORD_DELAY_MIN, KEYWORD_DELAY_MAX))

        time.sleep(interval)

def shutdown(signum, frame):
   def shutdown(signum, frame):
    print("=" * 40, flush=True)
    print(f"🛑 봇 종료 (신호: {signum})", flush=True)
    print("=" * 40, flush=True)
    send_discord(f"🛑 봇이 종료되었습니다. (신호: {signum})")
    sys.exit(0)
if __name__ == "__main__":
    if not DISCORD_WEBHOOK_URLS:
        print("⚠️ 경고: 웹훅 URL이 하나도 설정되지 않았습니다! 환경변수를 확인하세요.")
        sys.exit(1)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        monitor()
    except Exception as e:
        print(f"예기치 못한 오류: {e}")
        send_discord(f"⚠️ 봇이 오류로 종료되었습니다: {e}")
        sys.exit(1)
