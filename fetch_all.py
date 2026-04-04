#!/usr/bin/env python3
"""第1〜12話をSyosetuから取得してepisodesフォルダに保存する。"""

import time
import requests
from pathlib import Path
from bs4 import BeautifulSoup

BASE_URL = "https://ncode.syosetu.com/n5758lu/"
EPISODES_DIR = Path("episodes")
EPISODES_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://ncode.syosetu.com/",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


def safe_filename(s: str) -> str:
    for ch, rep in [("/", "／"), ("\\", "＼"), (":", "："), ("*", "＊"),
                    ("?", "？"), ('"', '"'), ("<", "＜"), (">", "＞"), ("|", "｜")]:
        s = s.replace(ch, rep)
    return s


for chapter_num in range(1, 13):
    url = f"{BASE_URL}{chapter_num}/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # タイトル取得
        title_tag = (
            soup.find("p", class_="novel_subtitle")
            or soup.find("h1", class_="p-novel__title")
            or soup.find("p", class_="p-novel__subtitle")
        )
        title = title_tag.get_text(strip=True) if title_tag else f"第{chapter_num}話"

        # 本文取得
        body_tag = (
            soup.find("div", id="novel_honbun")
            or soup.find("div", class_="p-novel__body")
        )
        if body_tag is None:
            print(f"  第{chapter_num}話: 本文タグ見つからず（HTML構造確認が必要）")
            continue

        lines = []
        for tag in body_tag.find_all(["p", "br"]):
            text = tag.get_text()
            lines.append(text)
        body = "\n".join(lines).strip()

        # ファイル名: ep01_タイトル.md
        filename = EPISODES_DIR / f"ep{chapter_num:02d}_{safe_filename(title)}.md"
        content = f"# {title}\n\n{body}"
        filename.write_text(content, encoding="utf-8")

        char_count = len(body.replace("\n", ""))
        print(f"  第{chapter_num:02d}話 [{char_count:,}字]: {filename.name}")
        time.sleep(1)

    except Exception as e:
        print(f"  第{chapter_num}話 エラー: {e}")

print("完了")
