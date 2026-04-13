import sys
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

import re
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
]

CHECK_INTERVAL_MIN = 28
CHECK_INTERVAL_MAX = 35
KEYWORD_DELAY_MIN = 1.0
KEYWORD_DELAY_MAX = 2.5
LONG_BREAK_CHANCE = 0.1
LONG_BREAK_MIN = 60
MAX_RETRIES = 5
MAX_SEEN_PRODUCTS = 2000
DISCORD_TIMEOUT = 10
DISCORD_RETRIES = 2
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


# ─── seen_products: pid 기반 중복 방지 ───
seen_products = set()
seen_order = deque()

# ─── seen_signatures: (정규화 제목 + 가격) 기반 재등록 방지 ───
seen_signatures = set()
sig_order = deque()

item_counter = 0

# Session: 기본 헤더 누적 방지를 위해 headers를 매 요청마다 명시적으로 전달
session = requests.Session()
session.headers.clear()


# ─── 유틸 함수 ───

def normalize_title(name: str) -> str:
    """공백·특수문자 제거 후 소문자화 → 재등록 감지용"""
    return re.sub(r'[\s\W_]+', '', name).lower()

def make_signature(name: str, price) -> str:
    return f"{normalize_title(name)}_{price}"

def format_price(price) -> str:
    try:
        return f"{int(float(str(price))):,}원"
    except (ValueError, TypeError):
        return "가격 미정"

def add_seen(product_id: str):
    """pid를 seen_products에 추가, 최대 크기 수동 관리"""
    if product_id in seen_products:
        return
    if len(seen_products) >= MAX_SEEN_PRODUCTS:
        old = seen_order.popleft()
        seen_products.discard(old)
    seen_products.add(product_id)
    seen_order.append(product_id)

def add_signature(sig: str):
    """signature를 seen_signatures에 추가, 최대 크기 수동 관리"""
    if sig in seen_signatures:
        return
    if len(seen_signatures) >= MAX_SEEN_PRODUCTS:
        old = sig_order.popleft()
        seen_signatures.discard(old)
    seen_signatures.add(sig)
    sig_order.append(sig)


# ─── Discord 전송 ───

def post_discord(url: str, data: dict) -> bool:
    """단일 웹훅 URL로 전송, timeout + 재시도"""
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

def send_discord(message: str):
    data = {"content": message}
    for url in DISCORD_WEBHOOK_URLS:
        post_discord(url, data)

def send_discord_embed(keyword: str, name: str, price, link: str, image_url, index: int, is_similar: bool = False):
    title = f"🔔 [{index}번째] {name}"
    color = 0xFFA500 if is_similar else 0xFF6600  # 유사 매물은 색상 구분

    fields = [
        {"name": "키워드", "value": keyword, "inline": True},
        {"name": "가격", "value": format_price(price), "inline": True},
    ]
    if is_similar:
        fields.append({
            "name": "⚠️ 유사 매물 감지",
            "value": "이전에 동일한 제목+가격의 매물이 등록된 적 있습니다. 재등록일 수 있습니다.",
            "inline": False,
        })

    embed = {
        "title": title,
        "url": link,
        "color": color,
        "fields": fields,
    }
    if image_url:
        embed["image"] = {"url": image_url}

    data = {"embeds": [embed]}
    for url in DISCORD_WEBHOOK_URLS:
        post_discord(url, data)


# ─── 번개장터 검색 ───

def search_bunjang(keyword: str, initial: bool = False) -> list:
    """
    keyword로 번개장터 검색.
    initial=True 이면 알림 없이 기존 상품만 seen에 등록 (봇 시작 시 사용).
    반환값: [(name, price, link, image_url), ...]  (initial=True면 항상 [])
    """
    url = f"https://api.bunjang.co.kr/api/1/find_v2.json?q={keyword}&n=50&page=0&order=date"

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
                if not product_id:
                    continue

                name  = item.get("name", "상품명 없음")
                price = item.get("price", "")
                link  = f"https://www.bunjang.co.kr/products/{product_id}"
                image = item.get("product_image") or ""
                if image:
                    image = image.replace("{res}", "360")

                sig = make_signature(name, price)

                # 초기 스캔: seen에 등록만 하고 알림 없음
                if initial:
                    add_seen(product_id)
                    add_signature(sig)
                    continue

                # pid 중복 체크
                if product_id in seen_products:
                    continue

                # 재등록 감지: (정규화 제목 + 가격) 동일 → 차단 아닌 유사 표시
                is_similar = sig in seen_signatures

                add_seen(product_id)
                if not is_similar:
                    add_signature(sig)
                else:
                    print(f"[유사 매물] pid={product_id} / {name} ({format_price(price)})")

                new_items.append((name, price, link, image or None, is_similar))

            return new_items

        except Exception as e:
            wait = (2 ** attempt) * 5
            print(f"[{keyword}] 오류: {e}. {wait}초 대기 후 재시도... (시도 {attempt}/{MAX_RETRIES})")
            time.sleep(wait)

    print(f"[{keyword}] 최대 재시도 초과. 이번 사이클 건너뜀.")
    return []


# ─── 메인 루프 ───

def monitor():
    global item_counter

    print("=" * 40)
    print("번개장터 감시 봇 시작")
    print(f"키워드: {KEYWORDS}")
    print(f"확인 간격: {CHECK_INTERVAL_MIN}~{CHECK_INTERVAL_MAX}초 (랜덤)")
    print(f"웹훅 개수: {len(DISCORD_WEBHOOK_URLS)}")
    print("=" * 40)
    send_discord("✅ 번개장터 감시 봇이 시작되었습니다!")

    # 초기 스캔: 기존 상품 seen에 등록, 알림 없음
    print("기존 상품 스캔 중...")
    for keyword in KEYWORDS:
        search_bunjang(keyword, initial=True)
        time.sleep(random.uniform(KEYWORD_DELAY_MIN, KEYWORD_DELAY_MAX))
    print("감시 시작!")

    while True:
        if random.random() < LONG_BREAK_CHANCE:
            print(f"[{time.strftime('%H:%M:%S')}] 긴 휴식 중... ({LONG_BREAK_MIN}초)")
            time.sleep(LONG_BREAK_MIN)
            continue

        interval = random.uniform(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX)
        print(f"[{time.strftime('%H:%M:%S')}] 확인 중... (다음 확인: {interval:.0f}초 후)")

        shuffled = KEYWORDS.copy()
        random.shuffle(shuffled)

        for keyword in shuffled:
            new_items = search_bunjang(keyword)
            for name, price, link, image_url, is_similar in new_items:
                item_counter += 1
                tag = "[유사]" if is_similar else "[신규]"
                print(f"[{item_counter}번째]{tag} {name} / {format_price(price)}")
                send_discord_embed(keyword, name, price, link, image_url, item_counter, is_similar=is_similar)
            time.sleep(random.uniform(KEYWORD_DELAY_MIN, KEYWORD_DELAY_MAX))

        time.sleep(interval)


# ─── 시그널 핸들러 ───

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
