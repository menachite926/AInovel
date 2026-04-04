"""
AInovel 自動執筆CLI
外交官の俺、戦えない魔王に転生したが交渉だけで世界を支配する

使い方:
    python write.py --plot "プロット内容" --episodes 3
    python write.py --plot "..." --episodes 2 --from-chapter 14
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.markdown import Markdown

console = Console()

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "novel_config.json"
EPISODES_DIR = BASE_DIR / "episodes"
SETTINGS_DIR = BASE_DIR / "settings"
KB_DIR = BASE_DIR / "knowledge_base"


def load_config() -> dict:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_settings() -> str:
    """settings/ フォルダの3ファイルを読み込んで結合する。"""
    parts = []
    files = {
        "world.md": "【世界観設定】",
        "characters.md": "【キャラクター設定】",
        "plot_overview.md": "【プロット・執筆方針】",
    }
    for filename, label in files.items():
        path = SETTINGS_DIR / filename
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"{label}\n{content}")
        else:
            console.print(f"[yellow]警告: {path} が見つかりません[/yellow]")
    return "\n\n---\n\n".join(parts)


def load_knowledge_base() -> str:
    """knowledge_base/ のファイルを読み込む。"""
    parts = []
    for path in sorted(KB_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8").strip()
        if content:
            parts.append(f"【{path.stem}】\n{content}")
    return "\n\n---\n\n".join(parts)


def load_recent_chapters(config: dict, from_chapter: int) -> str:
    """直近N話をキャッシュから読み込む。なければスクレイピングを試みる。"""
    num_recent = config.get("recent_chapters_for_context", 5)
    start = max(1, from_chapter - num_recent)
    end = from_chapter - 1

    if end < 1:
        return ""

    chapters = []
    cache_dir = EPISODES_DIR / "cache"

    for i in range(start, end + 1):
        cache_path = cache_dir / f"ch_{i:03d}.txt"
        if cache_path.exists():
            chapters.append(cache_path.read_text(encoding="utf-8"))
        else:
            # キャッシュがなければ取得を試みる
            try:
                from fetch_novel import fetch_chapter
                text = fetch_chapter(i, config["url"])
                chapters.append(text)
                console.print(f"[dim]第{i}話を取得しました[/dim]")
            except Exception as e:
                console.print(f"[yellow]第{i}話の取得をスキップしました: {e}[/yellow]")

    if not chapters:
        return ""

    joined = "\n\n===\n\n".join(chapters)
    return f"【直近{len(chapters)}話の本文（文体・設定参考用）】\n{joined}"


def build_system_prompt(settings: str, knowledge_base: str, config: dict) -> str:
    title = config["title"]
    protagonist = config["protagonist_name"]
    target_len = config["episode_length_target"]

    return f"""あなたはなろう系小説の執筆アシスタントです。
以下の設定・知識ベースに基づき、「{title}」の続きを執筆してください。

## 小説情報
- タイトル: {title}
- 主人公: {protagonist}
- 目標文字数: 1話あたり約{target_len}字

## 設定資料
{settings}

---

## 執筆パターン知識ベース
{knowledge_base}

---

## 執筆の絶対ルール
1. 設定に記載されている「禁止事項」を絶対に守ること
2. 各キャラクターの口調・性格を設定通りに維持すること
3. 1話は約{target_len}字を目安にすること（3,500〜6,000字の範囲内）
4. 各話の末尾は必ずクリフハンガーまたは次話への引きで終わること
5. 主人公ヴォルドは原則として武力ではなく交渉・策略で解決すること
6. なろう読者が喜ぶ「爽快感・逆転」を意識した構成にすること
7. 出力は各話を以下のMarkdown形式で出力すること:

```
# 第XX話 タイトル

本文...

---
```

複数話を連続して出力する場合は、各話を `---` で区切ること。
"""


def ask_clarifying_questions(
    client: anthropic.Anthropic,
    system_prompt: str,
    plot: str,
    recent_context: str,
    from_chapter: int,
    num_episodes: int,
) -> tuple[str, list]:
    """Claudeに曖昧な点を質問させる。質問なしなら空文字列を返す。"""
    context_section = f"\n\n{recent_context}" if recent_context else ""

    user_message = f"""以下のプロットに基づき、第{from_chapter}話から{num_episodes}話分の小説を執筆します。
{context_section}

【今回のプロット】
{plot}

執筆前に確認したい点があれば質問してください。
特に問題なければ「質問なし」と答えてください。
（質問は3つ以内にしてください）"""

    messages = [{"role": "user", "content": user_message}]

    console.print("\n[bold cyan]Claudeが内容を確認中...[/bold cyan]")

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1000,
        system=system_prompt,
        messages=messages,
    )

    reply = response.content[0].text.strip()
    messages.append({"role": "assistant", "content": reply})

    if "質問なし" in reply or "特に質問はありません" in reply or reply.lower().startswith("no question"):
        return "", messages

    return reply, messages


def generate_episodes(
    client: anthropic.Anthropic,
    system_prompt: str,
    messages: list,
    answers: str,
    from_chapter: int,
    num_episodes: int,
    plot: str,
) -> str:
    """本文を生成する。"""
    if answers:
        messages.append({"role": "user", "content": answers})

    generate_prompt = (
        f"では、第{from_chapter}話から第{from_chapter + num_episodes - 1}話まで、"
        f"計{num_episodes}話分を一括で執筆してください。\n"
        f"各話を `---` で区切り、それぞれに話タイトルを付けてください。\n"
        f"プロット: {plot}"
    )

    if not answers:
        # 質問なしの場合は初回メッセージからそのまま生成
        messages.append({"role": "user", "content": generate_prompt})
    else:
        messages.append({"role": "user", "content": generate_prompt})

    console.print(f"\n[bold green]第{from_chapter}話〜第{from_chapter + num_episodes - 1}話を生成中...[/bold green]")

    with console.status("[bold green]執筆中...[/bold green]"):
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=8000,
            system=system_prompt,
            messages=messages,
        )

    return response.content[0].text.strip()


def save_episodes(content: str, from_chapter: int, num_episodes: int, plot: str) -> list[Path]:
    """生成されたエピソードをファイルに保存する。"""
    EPISODES_DIR.mkdir(exist_ok=True)

    # `---` で分割して各話を取得
    raw_parts = content.split("\n---\n")
    # 空の部分を除去
    parts = [p.strip() for p in raw_parts if p.strip() and p.strip() != "---"]

    saved_paths = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    for i, part in enumerate(parts):
        chapter_num = from_chapter + i
        filename = EPISODES_DIR / f"ch_{chapter_num:03d}.md"

        footer = f"\n\n---\n*生成日時: {now}*  \n*プロット: {plot[:100]}{'...' if len(plot) > 100 else ''}*"
        full_content = part + footer

        filename.write_text(full_content, encoding="utf-8")
        saved_paths.append(filename)
        console.print(f"[green]✓ {filename.name} を保存しました[/green]")

    return saved_paths


def count_chars(text: str) -> int:
    return len(text.replace("\n", "").replace(" ", ""))


def main():
    parser = argparse.ArgumentParser(
        description="AInovel 自動執筆CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python write.py --plot "ドワーフ王国との鉄鉱石交渉。裏で暗殺者が動いている" --episodes 3
  python write.py --plot "エルフ女王との外交交渉" --episodes 2 --from-chapter 14
        """,
    )
    parser.add_argument("--plot", "-p", required=True, help="今回のプロット・あらすじ")
    parser.add_argument("--episodes", "-e", type=int, default=1, help="生成する話数（デフォルト: 1）")
    parser.add_argument("--from-chapter", "-f", type=int, default=None, help="開始話数（指定しない場合は自動検出）")
    parser.add_argument("--no-questions", action="store_true", help="質問フェーズをスキップして直接生成")
    args = parser.parse_args()

    # API キー確認
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red]エラー: 環境変数 ANTHROPIC_API_KEY が設定されていません[/red]")
        sys.exit(1)

    # 設定読み込み
    config = load_config()

    # 開始話数の自動検出
    if args.from_chapter is None:
        existing = sorted(EPISODES_DIR.glob("ch_*.md"))
        if existing:
            last_num = int(existing[-1].stem.replace("ch_", ""))
            args.from_chapter = last_num + 1
        else:
            args.from_chapter = 11  # デフォルト（既存10話の次）
        console.print(f"[dim]開始話数: 第{args.from_chapter}話（自動検出）[/dim]")

    # ヘッダー表示
    console.print(Panel(
        f"[bold]{config['title']}[/bold]\n"
        f"第{args.from_chapter}話〜第{args.from_chapter + args.episodes - 1}話 を生成します\n"
        f"プロット: {args.plot[:80]}{'...' if len(args.plot) > 80 else ''}",
        title="[cyan]AInovel 自動執筆システム[/cyan]",
        border_style="cyan",
    ))

    # 各種データ読み込み
    console.print("\n[dim]設定ファイルを読み込み中...[/dim]")
    settings = load_settings()
    knowledge_base = load_knowledge_base()
    recent_context = load_recent_chapters(config, args.from_chapter)

    if recent_context:
        console.print(f"[dim]直近話の本文をコンテキストに追加しました[/dim]")

    # Claude クライアント初期化
    client = anthropic.Anthropic(api_key=api_key)

    # システムプロンプト構築
    system_prompt = build_system_prompt(settings, knowledge_base, config)

    # 質問フェーズ
    questions = ""
    messages = []

    if not args.no_questions:
        questions, messages = ask_clarifying_questions(
            client, system_prompt, args.plot, recent_context, args.from_chapter, args.episodes
        )

        if questions:
            console.print("\n[bold yellow]Claudeからの確認事項:[/bold yellow]")
            console.print(Panel(questions, border_style="yellow"))
            answers = Prompt.ask("\n[bold]回答してください[/bold] (スキップする場合はEnter)")
        else:
            console.print("[dim]確認事項なし。直接執筆に進みます。[/dim]")
            answers = ""
    else:
        answers = ""
        messages = []

    # 本文生成
    content = generate_episodes(
        client, system_prompt, messages, answers,
        args.from_chapter, args.episodes, args.plot
    )

    # 保存
    console.print("\n[bold]生成された本文:[/bold]")
    console.print(Panel(
        content[:500] + ("..." if len(content) > 500 else ""),
        title="プレビュー（先頭500字）",
        border_style="green",
    ))

    saved = save_episodes(content, args.from_chapter, args.episodes, args.plot)

    # サマリ
    char_count = count_chars(content)
    console.print(Panel(
        f"[bold green]✓ 生成完了[/bold green]\n"
        f"生成話数: {len(saved)}話\n"
        f"総文字数: {char_count:,}字\n"
        f"1話平均: {char_count // max(len(saved), 1):,}字\n"
        f"保存先: {EPISODES_DIR}/",
        title="[green]生成結果[/green]",
        border_style="green",
    ))


if __name__ == "__main__":
    main()
