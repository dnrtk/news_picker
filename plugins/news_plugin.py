import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import yaml
from google import genai

from core.base_plugin import BasePlugin, ContentItem
from core.config_loader import get_env

logger = logging.getLogger(__name__)

MODELS = ["gemini-3-flash-preview", "gemini-2.5-flash"]  # 優先順にフォールバック
BATCH_SIZE = 10  # 1リクエストにまとめる最大件数
LOG_DIR = Path("logs")

BATCH_PROMPT = """\
以下の{n}件のニュース記事を、それぞれラジオで読み上げるための日本語で2〜4文に要約してください。
語尾は「〜です。〜ます。」調で統一し、固有名詞はそのまま使用してください。
記号や括弧は使わず、自然に読み上げられる文章にしてください。

必ず以下のJSON形式のみで返してください（他のテキストは不要）:
{{"summaries": ["1件目の要約", "2件目の要約", ...]}}

{articles}"""

ARTICLE_TEMPLATE = "【記事{i}】\nタイトル: {title}\n本文: {body}"


class NewsPlugin(BasePlugin):
    name = "news"
    order = 2

    def __init__(self, config: dict):
        super().__init__(config)
        self.max_items: int = config.get("max_items", 15)
        self.sources: list[dict] = config.get("sources", [])
        api_key = get_env("GEMINI_API_KEY")
        self._genai_client = genai.Client(api_key=api_key)

    def fetch(self) -> list[ContentItem]:
        fetched_at = datetime.now(timezone.utc).astimezone()

        raw_entries = self._fetch_rss()  # list of (entry, source_dict)
        deduped = self._deduplicate(raw_entries)
        sorted_entries = sorted(
            deduped,
            key=lambda es: es[0].get("published_parsed") or (),
            reverse=True,
        )
        top_entries = sorted_entries[: self.max_items]

        # (title, body) のリストを作成（要約用）
        articles = [
            (e.get("title", "").strip(), e.get("summary", e.get("title", "")).strip())
            for e, _ in top_entries
        ]

        # BATCH_SIZE 件ずつまとめて要約
        summaries: list[str] = []
        for i in range(0, len(articles), BATCH_SIZE):
            batch = articles[i : i + BATCH_SIZE]
            batch_summaries = self._summarize_batch(batch)
            summaries.extend(batch_summaries)

        # ニュースログを保存
        self._write_news_log(fetched_at, top_entries, articles, summaries)

        items = []
        for (title, _), summary in zip(articles, summaries):
            items.append(ContentItem(title=title, body=summary, source=self.name))
        return items

    def _fetch_rss(self) -> list[tuple[dict, dict]]:
        """各エントリを (entry, source_dict) のタプルで返す。"""
        entries: list[tuple[dict, dict]] = []
        for source in self.sources:
            url = source.get("url", "")
            label = source.get("label", url)
            try:
                feed = feedparser.parse(url)
                logger.info(f"[news] {label}: {len(feed.entries)} 件取得")
                for entry in feed.entries:
                    entries.append((entry, source))
            except Exception as e:
                logger.error(f"[news] {label} RSS 取得失敗: {e}")
        return entries

    def _deduplicate(self, entries: list[tuple[dict, dict]]) -> list[tuple[dict, dict]]:
        seen_titles: set[str] = set()
        result = []
        for entry, source in entries:
            title = entry.get("title", "").strip()
            normalized = title[:20]
            if normalized not in seen_titles:
                seen_titles.add(normalized)
                result.append((entry, source))
        return result

    def _write_news_log(
        self,
        fetched_at: datetime,
        top_entries: list[tuple[dict, dict]],
        articles: list[tuple[str, str]],
        summaries: list[str],
    ) -> None:
        """logs/YYYYMMDD_news.yaml にニュースの詳細情報を書き出す。"""
        LOG_DIR.mkdir(exist_ok=True)
        log_path = LOG_DIR / f"{fetched_at.strftime('%Y%m%d')}_news.yaml"

        article_records = []
        for i, ((entry, source), (title, raw_body), summary) in enumerate(
            zip(top_entries, articles, summaries), start=1
        ):
            # published_parsed は time.struct_time なので ISO 文字列に変換
            published_at = ""
            if entry.get("published_parsed"):
                try:
                    import calendar
                    ts = calendar.timegm(entry["published_parsed"])
                    published_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                except Exception:
                    pass

            article_records.append({
                "index": i,
                "title": title,
                "source_label": source.get("label", ""),
                "source_url": source.get("url", ""),
                "article_url": entry.get("link", ""),
                "published_at": published_at,
                "raw_body": raw_body,
                "summary": summary,
            })

        log_data = {
            "fetched_at": fetched_at.isoformat(),
            "count": len(article_records),
            "articles": article_records,
        }

        try:
            with open(log_path, "w", encoding="utf-8") as f:
                yaml.dump(log_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            logger.info(f"[news] ニュースログを保存しました: {log_path}")
        except Exception as e:
            logger.error(f"[news] ニュースログの保存に失敗しました: {e}")

    def _summarize_batch(self, articles: list[tuple[str, str]], retries: int = 3) -> list[str]:
        """複数記事を1リクエストでまとめて要約する。失敗時はタイトルのリストを返す。"""
        articles_text = "\n\n".join(
            ARTICLE_TEMPLATE.format(i=i + 1, title=title, body=body[:400])
            for i, (title, body) in enumerate(articles)
        )
        prompt = BATCH_PROMPT.format(n=len(articles), articles=articles_text)

        for model in MODELS:
            result = self._try_summarize_batch(prompt, articles, model, retries)
            if result is not None:
                return result
            logger.warning(f"[news] {model} 失敗。次のモデルへ")

        logger.error("[news] 全モデルで要約失敗。タイトルのみ使用")
        return [title for title, _ in articles]

    def _try_summarize_batch(
        self, prompt: str, articles: list[tuple[str, str]], model: str, retries: int
    ) -> list[str] | None:
        for attempt in range(retries):
            try:
                response = self._genai_client.models.generate_content(
                    model=model,
                    contents=prompt,
                )
                text = response.text.strip()
                # ```json ... ``` のコードブロックを除去
                if text.startswith("```"):
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]
                data = json.loads(text)
                summaries = data["summaries"]
                if len(summaries) == len(articles):
                    logger.info(f"[news] バッチ要約成功 ({model}): {len(articles)} 件")
                    return summaries
                logger.warning(f"[news] 件数不一致: 期待{len(articles)}件 / 実際{len(summaries)}件")
                return self._pad_summaries(summaries, articles)
            except Exception as e:
                err_str = str(e)
                # 503はリトライせず即座に次のモデルへ
                if "503" in err_str or "UNAVAILABLE" in err_str:
                    logger.warning(f"[news] {model} 503 - 次のモデルへスキップ")
                    return None
                logger.warning(f"[news] バッチ要約失敗 ({model}, 試行 {attempt + 1}/{retries}): {e}")
                if attempt < retries - 1:
                    wait = 15
                    try:
                        for d in e.args[0].get("error", {}).get("details", []):
                            if "retryDelay" in d:
                                wait = int(d["retryDelay"].rstrip("s")) + 1
                                break
                    except Exception:
                        pass
                    logger.info(f"[news] {wait}秒待機してリトライ")
                    time.sleep(wait)
        return None

    def _pad_summaries(self, summaries: list[str], articles: list[tuple[str, str]]) -> list[str]:
        """件数が足りない場合にタイトルで補完する。"""
        result = list(summaries)
        while len(result) < len(articles):
            result.append(articles[len(result)][0])
        return result[: len(articles)]

    def format(self, items: list[ContentItem]) -> str:
        if not items:
            return "本日のニュースは取得できませんでした。"

        today = datetime.now(timezone.utc).astimezone()
        date_str = f"{today.month}月{today.day}日"

        lines = [f"続いて、{date_str}のニュースをお伝えします。"]
        for i, item in enumerate(items, start=1):
            lines.append(f"{i}件目。{item.body}")
        lines.append("以上、本日のニュースをお伝えしました。")
        return "\n".join(lines)
