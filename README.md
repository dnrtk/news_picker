# news_picker

毎朝 7:30 に RSS からニュースを取得・要約し、VOICEVOX で音声読み上げするシステム。

## 機能

- RSS フィード（Google ニュース / NHK）からトップニュースを取得
- Google Gemini API で日本語要約（2〜4文、ラジオ風）
- VOICEVOX（ローカル）で音声合成 → スピーカー再生
- プラグイン構造により情報ソースを追加可能

## 動作の流れ

```
07:30  起動
       ├─ [NewsPlugin] RSS 取得 → Gemini で要約
〜07:32 原稿生成（オープニング + ニュース + クロージング）
〜07:35 VOICEVOX で音声合成（WAV を tmp/ に保存）
07:35〜 音声再生（5〜10 分）
終了後  tmp/ の WAV ファイルを削除
```

## 前提条件

- `GEMINI_API_KEY` が環境変数に設定済み
- VOICEVOX ENGINE は**初回実行時に自動ダウンロード**されます（約 1〜2 GB）

## セットアップ

```bash
# 1. 環境変数を設定（Windows）
setx GEMINI_API_KEY "your_key_here"

# 2. 依存パッケージをインストール
uv sync

# 3. （任意）.env で開発時のキー補完
cp .env.example .env
# .env を編集してキーを設定
```

## 実行

```bash
# 即時実行
uv run python main.py
```

## 自動実行（Windows タスクスケジューラ）

プロジェクトルートに `run.bat` が用意されているので、これをタスクスケジューラーに登録する。

### 登録手順

**1. タスクスケジューラーを開く**

```
Win + R → taskschd.msc → Enter
```

**2. タスクの作成**

右ペインの「タスクの作成」をクリック。

**3. 全般タブ**

| 項目 | 値 |
|------|-----|
| 名前 | `news_picker` |
| セキュリティオプション | 「ユーザーがログオンしているかどうかにかかわらず実行する」を選択 |

**4. トリガータブ → 「新規」**

| 項目 | 値 |
|------|-----|
| タスクの開始 | スケジュールに従う |
| 設定 | 毎日 |
| 開始 | `07:30:00` |

**5. 操作タブ → 「新規」**

| 項目 | 値 |
|------|-----|
| 操作 | プログラムの開始 |
| プログラム/スクリプト | `C:\ws\github\news_picker\run.bat`（実際のパスに変更） |
| 開始（オプション） | `C:\ws\github\news_picker`（プロジェクトのフォルダ） |

**6. 条件タブ**

| 項目 | 値 |
|------|-----|
| ネットワーク接続時のみタスクを開始する | チェック |

**7. 設定タブ**

| 項目 | 値 |
|------|-----|
| タスクを停止するまでの時間 | `1時間` |

「OK」で保存。パスワードを求められたらログインパスワードを入力。

### 動作確認

タスクを右クリック →「実行する」で即時起動してログを確認。

```
logs\YYYYMMDD.log          # 実行ログ
logs\YYYYMMDD_news.yaml    # 取得ニュースの詳細
```

## 設定

`config.yaml` で動作をカスタマイズできる。

```yaml
tts:
  voicevox:
    engine_dir: "voicevox_engine"  # ENGINE の保存先（なければ自動ダウンロード）
    speaker_id: 3        # 話者（3: ずんだもん）
    speed_scale: 1.1     # 読み上げ速度
    volume_scale: 1.0    # 音量

plugins:
  - name: news
    max_items: 15        # 取得件数（上限）
    sources:
      - url: "https://news.google.com/rss?hl=ja&gl=JP&ceid=JP:ja"
        label: "Google ニュース"
      - url: "https://www3.nhk.or.jp/rss/news/cat0.xml"
        label: "NHK トップ"
```

## 環境変数

| 変数名 | 用途 | 必須 |
|--------|------|------|
| `GEMINI_API_KEY` | Gemini API 認証 | ○ |
| `TIMETREE_ACCESS_TOKEN` | TimeTree 連携（将来） | - |

## プロジェクト構成

```
news_picker/
├── main.py                 # エントリーポイント
├── config.yaml             # 設定ファイル
├── pyproject.toml          # 依存関係（uv）
├── core/
│   ├── base_plugin.py      # プラグイン基底クラス
│   ├── config_loader.py    # 設定・環境変数読み込み
│   ├── plugin_runner.py    # プラグイン実行管理
│   ├── script_generator.py # 原稿テキスト生成
│   ├── tts.py              # VOICEVOX 音声合成
│   └── player.py           # 音声再生
├── plugins/
│   └── news_plugin.py      # ニュース取得・要約
├── tmp/                    # 音声ファイル一時保存（自動削除）
└── logs/                   # 実行ログ
```

## VOICEVOX ENGINE について

VOICEVOX ENGINE は起動時に自動で管理されます。

| 状況 | 動作 |
|------|------|
| `voicevox_engine/run.exe` が存在する | そのまま起動 |
| `voicevox_engine/` が存在しない | GitHub から自動ダウンロード（約 1〜2 GB） |
| VOICEVOX が既に別プロセスで起動中 | そちらをそのまま使用 |

終了時にプロセスを自動終了します。手動で起動していた場合は終了しません。

## 注意事項

- Gemini API は無料枠（1日 1500 リクエスト）を使用。1回の実行で最大 2 リクエスト
- 初回実行時はダウンロードのため数分〜十数分かかります
