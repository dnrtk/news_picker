# 朝の情報読み上げシステム 機能仕様書

> 対応要件定義：[01_Requests.md](01_Requests.md)

---

## 1. 処理フロー概要

### 1.1 タイムライン

```
07:30:00  スケジューラ起動
          └─ main.py 実行開始
07:30〜   [フェーズ1] 情報収集
          └─ 各プラグインの fetch() を順次実行
            ├─ TimeTreePlugin：本日の予定を取得
            └─ NewsPlugin：RSSからニュース取得 → LLM 要約
〜07:32   [フェーズ2] 原稿生成
          └─ 各プラグインの format() でテキスト生成 → 結合
〜07:35   [フェーズ3] 音声合成
          └─ VOICEVOX HTTP API へテキスト送信 → WAV ファイル生成
07:35〜   [フェーズ4] 再生
          └─ 生成済み WAV ファイルを順次再生（5〜10分）
終了後     一時 WAV ファイルを削除・ログ記録
```

### 1.2 実行方式

- **スケジューラ**：Windows タスクスケジューラで `uv run python main.py` を 7:30 に登録
  - Python 内スケジューラは使用しない（常駐プロセス不要）
- **フォールバック**：手動実行も可能（`uv run python main.py --now`）

---

## 2. ディレクトリ構成

```
news_picker/
├── main.py                   # エントリーポイント
├── config.yaml               # 設定ファイル
├── .env                      # APIキー等の機密情報（git管理外）
├── pyproject.toml            # 依存関係・プロジェクト設定（uv）
├── uv.lock                   # ロックファイル（uv）
│
├── core/
│   ├── __init__.py
│   ├── base_plugin.py        # BasePlugin 抽象クラス
│   ├── plugin_runner.py      # プラグイン管理・実行
│   ├── script_generator.py   # 原稿テキスト生成・結合
│   ├── tts.py                # VOICEVOX TTS
│   └── player.py             # 音声再生
│
├── plugins/
│   ├── __init__.py
│   ├── timetree_plugin.py    # TimeTree カレンダー
│   └── news_plugin.py        # ニュース取得・要約
│
├── tmp/                      # 音声ファイル一時保存（自動削除）
└── logs/                     # 実行ログ
```

---

## 3. データ構造

### 3.1 ContentItem

プラグインが返すコンテンツの共通型。

```python
@dataclass
class ContentItem:
    title: str           # 見出し・タイトル
    body: str            # 本文または要約テキスト
    source: str          # プラグイン名（"timetree", "news" 等）
    metadata: dict       # プラグイン固有の追加情報（任意）
```

### 3.2 AudioSegment

音声合成の単位。

```python
@dataclass
class AudioSegment:
    text: str            # 合成対象テキスト
    file_path: Path      # 生成する WAV ファイルパス
    order: int           # 再生順序
```

---

## 4. プラグイン仕様

### 4.1 BasePlugin インターフェース

```python
class BasePlugin(ABC):
    name: str            # プラグイン識別名
    order: int           # 読み上げ順序（昇順）
    enabled: bool        # 有効/無効

    @abstractmethod
    def fetch(self) -> list[ContentItem]:
        """情報を取得して ContentItem のリストを返す。失敗時は空リストを返す。"""
        ...

    @abstractmethod
    def format(self, items: list[ContentItem]) -> str:
        """ContentItem リストを読み上げ用の日本語テキストに整形して返す。"""
        ...
```

### 4.2 TimeTreePlugin

| 項目 | 内容 |
|------|------|
| 実行順序 | 1（最初に読み上げ） |
| データソース | TimeTree API v1 |
| 認証 | Personal Access Token（環境変数 `TIMETREE_ACCESS_TOKEN`） |
| 取得対象 | 本日 00:00〜23:59 のイベント |

**fetch() の動作**

1. TimeTree API `/calendars/{calendar_id}/upcoming_events` を呼び出す
2. 本日の日付でフィルタリング
3. 開始時刻の昇順にソート
4. `ContentItem` に変換して返す

**format() の出力例**

```
本日の予定をお知らせします。
本日は3件の予定があります。
10時00分から11時00分、チームミーティング。場所は会議室Aです。
14時30分から、歯科検診。
19時00分から、夕食、渋谷。
以上が本日の予定です。
```

予定なしの場合：
```
本日の予定はありません。
```

### 4.3 NewsPlugin

| 項目 | 内容 |
|------|------|
| 実行順序 | 2 |
| データソース | RSS フィード（Google ニュース + NHK） |
| 要約エンジン | Google Gemini API（`gemini-2.5-flash`） |
| 取得件数 | 最大 15 件（config で変更可） |

**初期 RSS ソース**

| ラベル | URL | 備考 |
|---|---|---|
| Google ニュース（総合） | `https://news.google.com/rss?hl=ja&gl=JP&ceid=JP:ja` | トップニュース |
| NHK トップ | `https://www3.nhk.or.jp/rss/news/cat0.xml` | 公共放送・速報性 |

> Google ニュースの RSS は認証不要・無料。複数メディアの記事が集約されるため幅広いトピックをカバーできる。カテゴリ別フィード（国内・経済・テクノロジー等）も同様に利用可能。

**fetch() の動作**

1. config に定義された RSS URL をすべてパース（`feedparser` 使用）
2. 重複記事をタイトルの類似度でフィルタリング
3. 公開日時の新しい順にソート
4. 上位 N 件を取得
5. 各記事を Gemini API で要約（2〜4文）
6. `logs/YYYYMMDD_news.yaml` にニュースログを書き出す
7. `ContentItem` に変換して返す

**LLM 要約プロンプト（1件ごと）**

```
以下のニュース記事を、ラジオで読み上げるための日本語で2〜4文に要約してください。
語尾は「〜です。〜ます。」調で統一し、固有名詞はそのまま使用してください。

タイトル: {title}
本文: {body}
```

**Gemini API 利用について**
- ライブラリ：`google-genai`
- モデル：`gemini-3-flash-preview`（失敗時 `gemini-2.5-flash` へフォールバック）
- 無料枠：1分あたり15リクエスト、1日1500リクエスト（2025年時点）
- 認証：Google AI Studio で取得した API キーを環境変数 `GEMINI_API_KEY` に設定

**ニュースログ（`logs/YYYYMMDD_news.yaml`）**

実行日ごとに以下の形式で保存する。ファイルが既に存在する場合は上書き。

```yaml
fetched_at: "2026-03-04T07:30:15+09:00"
count: 5
articles:
  - index: 1
    title: "記事タイトル"
    source_label: "Google ニュース"
    source_url: "https://news.google.com/rss?hl=ja&gl=JP&ceid=JP:ja"
    article_url: "https://actual-article.example.com/..."
    published_at: "2026-03-04T06:00:00+09:00"
    raw_body: "元の記事本文（feedparser の summary フィールド）"
    summary: "要約後のテキスト（Gemini API の出力）"
```

| フィールド | 説明 |
|---|---|
| `fetched_at` | fetch() 実行開始日時（ISO 8601） |
| `count` | 保存した記事数 |
| `index` | 読み上げ順（1始まり） |
| `title` | 記事タイトル |
| `source_label` | config.yaml に定義したソース名 |
| `source_url` | RSS フィードの URL |
| `article_url` | 記事本文へのリンク（feedparser の `link`） |
| `published_at` | 記事の公開日時（ISO 8601、不明時は空文字） |
| `raw_body` | 要約前の記事テキスト（feedparser の `summary`） |
| `summary` | Gemini API による要約テキスト |

**format() の出力例**

```
続いて、本日のニュースをお伝えします。
1件目。政府は〇〇の方針を決定しました。〜〜〜。
2件目。〇〇社は新製品を発表しました。〜〜〜。
（中略）
以上、本日のニュースをお伝えしました。
```

---

## 5. コアモジュール仕様

### 5.1 PluginRunner

```
役割：config からプラグインをロード、order 順に fetch() → format() を実行する
```

- `config.yaml` の `plugins` リストを読み込む
- `enabled: true` のプラグインのみ実行
- `order` の昇順に実行
- 各プラグインの実行を `try/except` で保護（1つが失敗しても続行）
- 各プラグインの出力テキストを `list[str]` で返す

### 5.2 ScriptGenerator

```
役割：各プラグインの出力テキストを結合して最終原稿を生成する
```

**出力フォーマット**

```
おはようございます。〇月〇日、〇曜日の朝の情報をお届けします。

{TimeTreePlugin の出力}

{NewsPlugin の出力}

以上で本日の朝の情報をお伝えしました。良い一日をお過ごしください。
```

### 5.3 TTSModule

```
役割：テキストを音声ファイル（WAV）に変換する
```

**VOICEVOX 利用フロー**

1. `http://localhost:50021` への接続確認
2. `/audio_query` エンドポイントへテキストを POST → クエリ JSON を取得
3. `/synthesis` エンドポイントへクエリ JSON を POST → WAV バイナリを取得
4. `tmp/` 以下に連番ファイルで保存（例：`tmp/001.wav`）

**パラメータ（config で変更可）**

| パラメータ | デフォルト値 | 説明 |
|---|---|---|
| `speaker_id` | 3（ずんだもん） | ❓ 要確認・選定 |
| `speed_scale` | 1.1 | 読み上げ速度 |
| `volume_scale` | 1.0 | 音量 |

**VOICEVOX 接続不可時**

- エラーログを出力して実行を中断する（フォールバックなし）
- VOICEVOXはローカルで事前起動しておく必要がある

**テキスト分割方針**

- 1回の API 呼び出しあたり最大 **200文字** を目安に分割
- 句点（。）で区切る

### 5.4 PlayerModule

```
役割：生成済みの WAV ファイルを順番に再生する
```

- `pygame.mixer` を使用して WAV ファイルを順次再生
- 再生完了後に `tmp/` 以下の WAV ファイルを全削除

---

## 6. 設定ファイル仕様

### 6.1 config.yaml

```yaml
# 全体設定
schedule:
  time: "07:30"

tts:
  engine: voicevox
  voicevox:
    host: "http://localhost:50021"
    speaker_id: 3
    speed_scale: 1.1
    volume_scale: 1.0

# プラグイン設定
plugins:
  # timetree は別ツールとして開発中。後で統合予定。
  # - name: timetree
  #   enabled: false
  #   order: 1

  - name: news
    enabled: true
    order: 2
    max_items: 15
    sources:
      - type: rss
        url: "https://news.google.com/rss?hl=ja&gl=JP&ceid=JP:ja"
        label: "Google ニュース"
      - type: rss
        url: "https://www3.nhk.or.jp/rss/news/cat0.xml"
        label: "NHK トップ"
```

### 6.2 APIキー管理（環境変数）

APIキー等の機密情報は **OS の環境変数** で管理する。コードに直接記述しない。

**環境変数一覧**

| 環境変数名 | 用途 | 必須 |
|---|---|---|
| `GEMINI_API_KEY` | Gemini API 認証 | ○ |
| `TIMETREE_ACCESS_TOKEN` | TimeTree API 認証（統合時） | △ |

**設定方法（Windows）**

```bat
# システム環境変数に永続設定（管理者権限不要のユーザー環境変数）
setx GEMINI_API_KEY "your_key_here"
setx TIMETREE_ACCESS_TOKEN "your_token_here"
```

**開発時の補助：`.env` ファイル**

ローカル開発時に限り、`python-dotenv` で `.env` から環境変数を読み込む。
`.env` は **`.gitignore` に必ず追加**してリポジトリに含めない。

```
# .env（開発時のみ・git管理外）
GEMINI_API_KEY=your_key_here
TIMETREE_ACCESS_TOKEN=your_token_here
```

**コードでの読み込み順序**

1. OS 環境変数を優先
2. OS 環境変数が未設定の場合のみ `.env` を参照（`python-dotenv` の `override=False`）

### 6.3 uv による環境管理

**セットアップ手順**

```bash
# 依存パッケージのインストール
uv sync

# スクリプト実行
uv run python main.py
```

**pyproject.toml の構成イメージ**

```toml
[project]
name = "news-picker"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "feedparser",
    "google-genai",
    "python-dotenv",
    "pyyaml",
    "pygame",
    "requests",
]
```

---

## 7. エラーハンドリング方針

| 状況 | 挙動 |
|------|------|
| TimeTree API エラー | スキップして次のプラグインへ。ログに記録 |
| RSS 取得失敗 | スキップ。ログに記録 |
| LLM API エラー | リトライ最大3回。失敗時は原文タイトルのみ読み上げ |
| VOICEVOX 接続不可 | 実行を中断。エラーログ記録 |

---

## 8. 未決定事項（要確認）

1. **VOICEVOX 話者**：ずんだもん（speaker_id: 3）に決定
2. **ニュース RSS ソース**：Google ニュース + NHK トップに決定
3. **LLM モデル**：`gemini-2.5-flash`（Google AI Studio）に決定
4. **TimeTreePlugin**：別ツールとして開発中。完成後に統合予定（現在は保留）
5. **読み上げ速度**：`speed_scale: 1.1` を初期値とし、実機確認後に調整
