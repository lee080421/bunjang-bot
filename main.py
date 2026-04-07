import sys
sys.stdout.reconfigure(encoding='utf-8')
import signal
import requests
import time
import random
import os

# ===== 설정 =====
DISCORD_WEBHOOK_URLS = [
    os.environ.get("DISCORD_WEBHOOK_URL_1"),  # 서버 1 웹훅
    os.environ.get("DISCORD_WEBHOOK_URL_2"),  # 서버 2 웹훅
]

DISCORD_WEBHOOK_URLS = [url for url in DISCORD_WEBHOOK_URLS if url]

KEYWORDS = [
    "뉴진스",
    "뉴진스 배너",
    "뉴진스 코카콜라",
    "뉴진스 배그"
]

CHECK_INTERVAL_MIN = 15   # 확인 간격 최소 (초)
CHECK_INTERVAL_MAX = 25   # 확인 간격 최대 (초)
KEYWORD_DELAY_MIN = 1.0   # 키워드 간 딜레이 최소 (초)
KEYWORD_DELAY_MAX = 2.5   # 키워드 간 딜레이 최대 (초)
LONG_BREAK_CHANCE = 0.1   # 긴 휴식 확률 (10%)
LONG_BREAK_MIN = 60       # 긴 휴식 (초)
MAX_RETRIES = 5           # 최대 재시도 횟수
# ================

# 최신 브라우저 User-Agent 목록 (Chrome 130+)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
]

# UA별 sec-ch-ua 매핑
SEC_CH_UA_MAP = {
    "Chrome/131": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Chrome/130": '"Google Chrome";v="130", "Chromium";v="130", "Not_A Brand";v="24"',
    "Firefox":    None,
    "Safari":     None,
}

def get_sec_ch_ua(ua: str):
    if "Chrome/131" in ua:
        return SEC_CH_UA_MAP["Chrome/131"]
    if "Chrome/130" in ua:
        return SEC_CH_UA_MAP["Chrome/130"]
    return None

def get_headers():
    """매 요청마다 자연스러운 브라우저 헤더 반환"""
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

seen_products = set()

# 전역 세션 (쿠키 자동 유지)
session = requests.Session()

def send_discord(message):
    data = {"content": message}
    for url in DISCORD_WEBHOOK_URLS:
        try:
            requests.post(url, json=data)
        except Exception as e:
            print(f"디스코드 전송 오류 ({url[:40]}...): {e}")

def send_discord_embed(keyword, name, price, link, image_url):
    data = {
        "embeds": [{
            "title": f"🔔 {name}",
            "url": link,
            "color": 0xFF6600,
            "fields": [
                {"name": "키워드", "value": keyword, "inline": True},
                {"name": "가격", "value": f"{price}원", "inline": True},
            ],
            "image": {"url": image_url} if image_url else None,
        }]
    }
    if not image_url:
        del data["embeds"][0]["image"]
    for url in DISCORD_WEBHOOK_URLS:
        try:
            requests.post(url, json=data)
        except Exception as e:
            print(f"디스코드 전송 오류 ({url[:40]}...): {e}")

def search_bunjang(keyword):
    """번개장터 API로 키워드 검색 후 새 상품 반환 (429 처리 + 지수 백오프)"""
    url = f"https://api.bunjang.co.kr/api/1/find_v2.json?q={keyword}&n=30&page=0&order=date"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, headers=get_headers(), timeout=10)

            # 429: Rate limit — 대기 후 재시도
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                wait = max(retry_after, 60) * attempt  # 지수 백오프
                print(f"[{keyword}] 429 Rate Limit. {wait}초 대기 후 재시도... (시도 {attempt}/{MAX_RETRIES})")
                time.sleep(wait)
                continue

            # 기타 HTTP 에러
            if response.status_code != 200:
                wait = (2 ** attempt) * 5  # 지수 백오프: 10, 20, 40, 80, 160초
                print(f"[{keyword}] HTTP {response.status_code}. {wait}초 대기 후 재시도... (시도 {attempt}/{MAX_RETRIES})")
                time.sleep(wait)
                continue

            data = response.json()
            new_items = []
            for item in data.get("list", []):
                product_id = str(item.get("pid", ""))
                if product_id and product_id not in seen_products:
                    seen_products.add(product_id)
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
    print("=" * 40)
    print("번개장터 감시 봇 시작")
    print(f"키워드: {KEYWORDS}")
    print(f"확인 간격: {CHECK_INTERVAL_MIN}~{CHECK_INTERVAL_MAX}초 (랜덤)")
    print("=" * 40)
    send_discord("✅ 번개장터 감시 봇이 시작되었습니다!")

    print("기존 상품 스캔 중...")
    for keyword in KEYWORDS:
        search_bunjang(keyword)
        time.sleep(random.uniform(KEYWORD_DELAY_MIN, KEYWORD_DELAY_MAX))
    print("감시 시작!\n")

    while True:
        # 가끔 긴 휴식
        if random.random() < LONG_BREAK_CHANCE:
            long_wait = LONG_BREAK_MIN
            print(f"[{time.strftime('%H:%M:%S')}] 긴 휴식 중... ({long_wait:.0f}초)")
            time.sleep(long_wait)

        interval = random.uniform(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX)
        print(f"[{time.strftime('%H:%M:%S')}] 확인 중... (다음 확인: {interval:.0f}초 후)")

        for keyword in KEYWORDS:
            new_items = search_bunjang(keyword)
            for name, price, link, image_url in new_items:
                print(f"새 상품: {name} / {price}원")
                send_discord_embed(keyword, name, price, link, image_url)
            time.sleep(random.uniform(KEYWORD_DELAY_MIN, KEYWORD_DELAY_MAX))

        time.sleep(interval)

if __name__ == "__main__":
  def shutdown(signum, frame):
    print(f"\n신호 수신({signum}). 봇 종료")
    send_discord("🛑 봇이 종료되었습니다.")
    sys.exit(0)

if __name__ == "__main__":
    # SIGTERM(클라우드 종료), SIGINT(Ctrl+C) 모두 처리
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        monitor()
    except Exception as e:
        print(f"예기치 못한 오류: {e}")
        send_discord(f"⚠️ 봇이 오류로 종료되었습니다: {e}")
