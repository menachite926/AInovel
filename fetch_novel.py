"""
Syosetu (小説家になろう) から話を取得するヘルパー。
ローカルキャッシュあり。
"""

import os
import time
import argparse
import requests
from pathlib import Path
from bs4 import BeautifulSoup

BASE_URL = "https://ncode.syosetu.com/n5758lu/"
CACHE_DIR = Path(__file__).parent / "episodes" / "cache"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://ncode.syosetu.com/",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


def _cache_path(chapter_num: int) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"ch_{chapter_num:03d}.txt"


def fetch_chapter(chapter_num: int, base_url: str = BASE_URL) -> str:
    """指定話数をSyosetuから取得（キャッシュあり）。"""
    cache = _cache_path(chapter_num)
    if cache.exists():
        return cache.read_text(encoding="utf-8")

    url = f"{base_url.rstrip('/')}/{chapter_num}/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"第{chapter_num}話の取得に失敗しました: {e}") from e

    soup = BeautifulSoup(resp.text, "html.parser")

    # 話タイトル
    title_tag = soup.find("p", class_="novel_subtitle") or soup.find("h1", class_="p-novel__title")
    title = title_tag.get_text(strip=True) if title_tag else f"第{chapter_num}話"

    # 本文
    body_tag = (
        soup.find("div", id="novel_honbun")
        or soup.find("div", class_="p-novel__body")
    )
    if body_tag is None:
        raise RuntimeError(f"第{chapter_num}話: 本文が見つかりませんでした（HTMLが変わった可能性）")

    lines = []
    for tag in body_tag.find_all(["p", "br"]):
        text = tag.get_text()
        lines.append(text)
    body = "\n".join(lines).strip()

    content = f"# {title}\n\n{body}"
    cache.write_text(content, encoding="utf-8")
    return content


def get_recent_chapters(base_url: str = BASE_URL, num_recent: int = 5, latest: int | None = None) -> list[str]:
    """直近N話を取得してコンテキスト用リストとして返す。

    Args:
        base_url: 小説のベースURL
        num_recent: 取得する話数
        latest: 最新話番号（Noneの場合は自動検出）
    """
    if latest is None:
        latest = _detect_latest_chapter(base_url)

    chapters = []
    start = max(1, latest - num_recent + 1)
    for i in range(start, latest + 1):
        try:
            text = fetch_chapter(i, base_url)
            chapters.append(text)
            time.sleep(0.5)  # サーバー負荷軽減
        except RuntimeError as e:
            print(f"警告: {e}")
    return chapters


def _detect_latest_chapter(base_url: str) -> int:
    """目次ページから最新話番号を取得する。"""
    try:
        resp = requests.get(base_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 話リンクを全取得して最大値を返す
        links = soup.find_all("a", href=True)
        import re
        chapter_nums = []
        pattern = re.compile(r"/n5758lu/(\d+)/")
        for a in links:
            m = pattern.search(a["href"])
            if m:
                chapter_nums.append(int(m.group(1)))

        if chapter_nums:
            return max(chapter_nums)
    except Exception as e:
        print(f"警告: 最新話番号の自動検出に失敗しました ({e})")

    # フォールバック: キャッシュから最大番号を取得
    if CACHE_DIR.exists():
        cached = [int(p.stem.replace("ch_", "")) for p in CACHE_DIR.glob("ch_*.txt")]
        if cached:
            return max(cached)

    return 10  # デフォルト値


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Syosetu話取得ツール")
    parser.add_argument("--chapter", "-c", type=int, help="取得する話番号")
    parser.add_argument("--recent", "-r", type=int, default=5, help="直近N話を取得")
    parser.add_argument("--latest", "-l", type=int, help="最新話番号（指定しない場合は自動検出）")
    parser.add_argument("--test", action="store_true", help="接続テスト（第1話取得）")
    args = parser.parse_args()

    if args.test or args.chapter:
        ch = args.chapter or 1
        print(f"第{ch}話を取得中...")
        try:
            text = fetch_chapter(ch)
            print(text[:500])
            print("...(取得成功)")
        except RuntimeError as e:
            print(f"エラー: {e}")
    else:
        print(f"直近{args.recent}話を取得中...")
        chapters = get_recent_chapters(num_recent=args.recent, latest=args.latest)
        print(f"{len(chapters)}話取得完了")
        for i, ch in enumerate(chapters, 1):
            print(f"\n--- 話 {i} ---")
            print(ch[:200])
