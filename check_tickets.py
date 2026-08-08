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
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import requests
from playwright.sync_api import sync_playwright

JST = timezone(timedelta(hours=9))
CUTOFF = datetime(2026, 8, 23, 18, 0, 0, tzinfo=JST)

STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")

# 「8/23」の表記ゆれ + 「大宮」を両方含むかで判定する
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


# チケット東京のカレンダーは「18:00●」(全席種予約可能)「18:00▲」(席種により予約可能)
# 「18:00×」(予定枚数終了)のように、時刻の直後に記号が付く。
# ●か▲が無い限り、日付や会場名だけがページに残っていても「完売中」なので通知しない。
AVAILABILITY_MARK_PATTERN = r"\d{1,2}:\d{2}\s*[●▲]"


def kyodotokyo_is_available(text: str) -> bool:
    return re.search(AVAILABILITY_MARK_PATTERN, text) is not None


def fetch_rendered_text(context, url: str, timeout_ms: int = 8000) -> str:
    """サイトごとに新しいタブでページを開き、レンダリング後のテキストを取得する"""
    page = context.new_page()
    try:
        try:
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        except Exception:
            # domcontentloadedすら取れない場合、少し待ってから現状のテキストを試みる
            pass
        # JSでの追加描画を待つ(networkidleは不安定なため固定待機に変更)
        page.wait_for_timeout(1500)
        return page.inner_text("body")
    finally:
        page.close()


def check_all_sites() -> list[str]:
    """再販が検知されたサイト名のリストを返す"""
    found_on = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--disable-http2"]  # 一部サイトのHTTP/2ブロック対策
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            )
        )

        for name, url in SITES.items():
            try:
                text = fetch_rendered_text(context, url)
                if "セッション情報が切断されました" in text:
                    # チケット東京はセッション制御で直接アクセスできないことがある
                    print(f"[{name}] セッション切断のため今回はスキップ (best effort)")
                    continue
                if not text_matches(text):
                    print(f"[{name}] 該当なし")
                    continue
                if name == "チケット東京" and not kyodotokyo_is_available(text):
                    # 「8/23」「大宮」の文字はあるが、●/▲マークが無い＝まだ完売中
                    print(f"[{name}] 8/23 大宮 の記載はあるが、まだ予約可能マーク(●/▲)が無いため完売中と判断")
                    continue
                print(f"[{name}] 8/23 大宮 の記載を検知しました！")
                found_on.append((name, url))
            except Exception as e:
                print(f"[{name}] 取得中にエラー: {e}")

        browser.close()
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
