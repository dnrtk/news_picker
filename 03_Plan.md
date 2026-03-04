# 朝の情報読み上げシステム 実装計画

> 対応仕様書：[02_Specifications.md](02_Specifications.md)

各フェーズは依存関係の順に並んでいる。原則として上から順に実施する。

---

## Phase 1: プロジェクト基盤セットアップ

- [x] `uv init` でプロジェクト初期化（`pyproject.toml` 生成）
- [x] 依存パッケージを `uv add` で追加
  - [x] `feedparser`
  - [x] `google-genai`（`google-generativeai` は非推奨のため新パッケージを使用）
  - [x] `python-dotenv`
  - [x] `pyyaml`
  - [x] `pygame`
  - [x] `requests`
  - ~~`gtts`~~（削除：gTTSフォールバックは廃止）
- [x] `.gitignore` に `.env`、`tmp/`、`logs/`、`.venv/` を追加
- [x] `config.yaml` のひな型を作成（仕様書 §6.1 の内容）
- [x] `.env` のひな型（`.env.example`）を作成
- [x] `tmp/`、`logs/` ディレクトリを作成

---

## Phase 2: コア基盤の実装

- [x] `core/base_plugin.py`：`ContentItem` dataclass を実装
- [x] `core/base_plugin.py`：`BasePlugin` 抽象クラスを実装（`fetch` / `format`）
- [x] `core/config_loader.py`：`config.yaml` と環境変数の読み込みを実装
  - [x] OS 環境変数を優先し、未設定時のみ `.env` を参照（`override=False`）
- [x] `core/plugin_runner.py`：`PluginRunner` を実装
  - [x] config からプラグインをロード
  - [x] `enabled` フラグと `order` 順に従って実行
  - [x] 各プラグインを `try/except` で保護

---

## Phase 3: NewsPlugin の実装

- [x] `plugins/news_plugin.py`：`BasePlugin` を継承したクラスを作成
- [x] `fetch()`：`feedparser` で RSS をパース
  - [x] 複数 RSS ソースを結合
  - [x] タイトルの類似度による重複除去
  - [x] 公開日時の降順ソート・上位 N 件に絞り込み
- [x] `fetch()`：Gemini API（`gemini-2.5-flash`）で各記事を要約
  - [x] プロンプト実装（仕様書 §4.3 の内容）
  - [x] API エラー時のリトライ（最大3回）
  - [x] リトライ全失敗時は原文タイトルのみ使用
- [x] `format()`：読み上げテキストへの整形
- [x] `logs/YYYYMMDD_news.yaml` へのニュースログ出力（仕様書 §4.3）
- [x] 単体動作確認（コンソールにテキスト出力）

---

## Phase 4: TTS モジュールの実装

- [x] `core/tts.py`：`TTSModule` クラスを作成
- [x] VOICEVOX 連携の実装
  - [x] エンジン起動確認（`http://localhost:50021` への疎通チェック）
  - [x] `/audio_query` → `/synthesis` の API 呼び出し
  - [x] テキストを句点で分割（1チャンク最大200文字）し、連番 WAV を `tmp/` に保存
- ~~gTTS フォールバックの実装~~（廃止：VOICEVOX 接続不可時はエラー終了）
- [x] 単体動作確認

---

## Phase 5: 原稿生成・再生モジュールの実装

- [x] `core/script_generator.py`：`ScriptGenerator` を実装
  - [x] オープニング・クロージングのテンプレート文を付加
  - [x] 各プラグイン出力を `order` 順に結合
- [x] `core/player.py`：`PlayerModule` を実装
  - [x] `pygame.mixer` で音声ファイルを連番順に再生
  - [x] 再生完了後に `tmp/` 以下の音声ファイルを全削除（TTSModule.cleanup）

---

## Phase 6: main.py の実装・結合

- [x] `main.py` に全モジュールを組み合わせた処理フローを実装
  - [x] フェーズ1（情報収集）→ フェーズ2（原稿生成）→ フェーズ3（音声合成）→ フェーズ4（再生）
- [x] `--now` オプションで即時実行できる CLI を実装
- [x] `logs/` へのログ出力を実装（実行日時・各フェーズの完了・エラー）
- [x] エンドツーエンドの動作確認（15件取得・正常終了）

---

## Phase 7: Windows タスクスケジューラ登録

- [ ] タスクスケジューラの設定手順をドキュメント化（`README.md` または `docs/setup.md`）
  - [ ] トリガー：毎日 07:30
  - [ ] 操作：`uv run python main.py` をプロジェクトディレクトリで実行
  - [ ] 条件：ネットワーク接続時のみ実行
- [ ] 実機で 7:30 の自動実行を確認

---

## Phase 8: 調整・チューニング

- [ ] VOICEVOX の読み上げ速度（`speed_scale`）を実機で確認・調整
- [ ] ニュース件数・要約文字数を調整して再生時間を 5〜10 分に収める
- [ ] Google ニュース RSS の記事品質を確認（必要に応じてソース追加・変更）

---

## Phase 9: TimeTree プラグイン統合（別ツール完成後）

- [ ] 別ツールの TimeTree 読み出し実装を `plugins/timetree_plugin.py` に移植
- [ ] `config.yaml` の timetree セクションを有効化
- [ ] 環境変数 `TIMETREE_ACCESS_TOKEN` を設定
- [ ] 動作確認
