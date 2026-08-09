#!/usr/bin/env python3
"""
玉置浩二 8/23 大宮公演 チケット再販監視スクリプト

対象サイト:
  - ローチケ (l-tike.com)
  - チケットぴあ (t.pia.jp)
  - イープラス (eplus.jp)
  - チケット東京 (tickets.kyodotokyo.com) ※ベストエフォート

「8/23」および「大宮」という文字列が対象ページに同時に出現したら
再販売とみなし、ntfy.sh 経由で通知する。

一度通知したら state.json に記録し、以降は再通知しない。
また 2026-08-23 18:00 (JST) を過ぎたら自動的に監視を打ち切る。

各サイトのチェックは別プロセスで実行し、一定時間で応答が無ければ
OSレベルで強制終了する(Playwrightが内部で完全にフリーズしても
全体が巻き込まれないようにするため)。
"""

import json
import functools
import multiprocessing as mp
import os
import re
import sys
from datetime import datetime, timezone, timedelta

print = functools.partial(print, flush=True)

import requests

JST = timezone(timedelta(hours=9))
CUTOFF = datetime(2026, 8, 23, 18, 0, 0, tzinfo=JST)

STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")

DATE_PATTERNS = [
    r"8\s*/\s*23",
    r"8\s*\.\s*23",
    r"8月\s*23日",
    r"08\s*/\s*23",
]
VENUE_PATTERN = r"大宮"

SITES = {
    "ローチケ": "https://l-tike.com/concert/mevent/?mid=305125",
    "ぴあ": "https://t.pia.jp/pia/artist/artists.do?artistsCd=11011325",
    "イープラス": "https://eplus.jp/sf/word/0000000710",
    "チケット東京": "https://tickets.kyodotokyo.com/asp/evt/evtdtl.aspx?dmf=1&ecd=KDT06010&ucd=&jdt=&kai=",
}

NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
PER_SITE_HARD_TIMEOUT_SEC = 20


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"notified": False}


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def text_matches(text: str) -> bool:
    has_date = any(re.search(p, text) for p in DATE_PATTERNS)
    has_venue = re.search(VENUE_PATTERN, text) is not None
    return has_date and has_venue


# ●▲(黒塗り・デスクトップ表記)に加え、◯△(白抜き・モバイル表記)にも対応
# ◯はU+25EF(LARGE CIRCLE)であり、○(U+25CB WHITE CIRCLE)とは別文字なので両方含める
AVAILABILITY_MARK_PATTERN = r"\d{1,2}:\d{2}\s*[●▲○◯△]"


def kyodotokyo_is_available(text: str) -> bool:
    return re.search(AVAILABILITY_MARK_PATTERN, text) is not None


def _fetch_worker(url: str, result_queue: "mp.Queue"):
    """別プロセスで実行される。ここが固まってもterminate()で殺せる。"""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--disable-http2"])
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0 Safari/537.36"
                )
            )
            page = context.new_page()
            try:
                page.goto(url, timeout=8000, wait_until="domcontentloaded")
            except Exception:
                pass
            page.wait_for_timeout(1500)
            text = page.evaluate("document.body ? document.body.innerText : ''")
            browser.close()
        result_queue.put(("ok", text))
    except Exception as e:
        result_queue.put(("error", str(e)))


def fetch_with_hard_timeout(url: str):
    """サイト取得を別プロセスで実行し、時間切れならOSレベルで強制終了する"""
    ctx = mp.get_context("fork")
    result_queue = ctx.Queue()
    proc = ctx.Process(target=_fetch_worker, args=(url, result_queue))
    proc.start()
    proc.join(PER_SITE_HARD_TIMEOUT_SEC)

    if proc.is_alive():
        proc.terminate()
        proc.join(3)
        if proc.is_alive():
            proc.kill()
            proc.join(3)
        return None, f"{PER_SITE_HARD_TIMEOUT_SEC}秒経過したため強制終了しました"

    if not result_queue.empty():
        status, payload = result_queue.get()
        if status == "ok":
            return payload, None
        return None, payload

    return None, "プロセスが結果を返さずに終了しました"


def check_all_sites() -> list:
    found_on = []
    for name, url in SITES.items():
        text, error = fetch_with_hard_timeout(url)

        if error is not None:
            print(f"[{name}] 取得中にエラー: {error}")
            continue

        if "セッション情報が切断されました" in text:
            print(f"[{name}] セッション切断のため今回はスキップ (best effort)")
            continue
        if not text_matches(text):
            print(f"[{name}] 該当なし")
            continue
        if name == "チケット東京" and not kyodotokyo_is_available(text):
            print(f"[{name}] 8/23 大宮 の記載はあるが、まだ予約可能マーク(●/▲/◯/△)が無いため完売中と判断")
            continue

        print(f"[{name}] 8/23 大宮 の記載を検知しました！")
        found_on.append((name, url))

    return found_on


def send_ntfy_notification(found_on):
    if not NTFY_TOPIC:
        print("NTFY_TOPIC が設定されていません。通知をスキップします。")
        return
    site_names = "、".join(name for name, _ in found_on)
    lines = [f"{name}: {url}" for name, url in found_on]
    message = f"検知サイト: {site_names}\n\n" + "\n".join(lines)

    resp = requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Title": "玉置浩二 8/23大宮 チケット再販売！".encode("utf-8"),
            "Priority": "urgent",
            "Tags": "ticket,rotating_light",
        },
        timeout=15,
    )
    resp.raise_for_status()
    print("ntfy通知を送信しました。")


def main():
    now = datetime.now(JST)
    print(f"現在時刻(JST): {now.isoformat()}")

    if now > CUTOFF:
        print("8/23 18:00 を過ぎたため監視を終了します。")
        return

    state = load_state()
    if state.get("notified"):
        print("既に通知済みのため、今回のチェックはスキップします。")
        return

    found_on = check_all_sites()

    if found_on:
        send_ntfy_notification(found_on)
        state["notified"] = True
        state["notified_at"] = now.isoformat()
        state["found_on"] = [name for name, _ in found_on]
        save_state(state)
    else:
        print("再販売はまだ検知されませんでした。")


if __name__ == "__main__":
    sys.exit(main())
