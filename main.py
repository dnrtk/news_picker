import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from core.config_loader import load_config, load_env
from core.plugin_runner import PluginRunner
from core.player import PlayerModule
from core.script_generator import ScriptGenerator
from core.tts import TTSModule

LOG_DIR = Path("logs")
TMP_DIR = Path("tmp")


def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"{datetime.now().strftime('%Y%m%d')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run():
    logger = logging.getLogger(__name__)
    logger.info("=== 朝の情報読み上げ 開始 ===")

    # 設定・環境変数の読み込み
    load_env()
    cfg = load_config()

    # フェーズ1: 情報収集
    logger.info("[Phase 1] 情報収集")
    runner = PluginRunner(cfg.get("plugins", []))
    plugin_texts = runner.run()

    if not plugin_texts:
        logger.error("全プラグインが失敗しました。終了します。")
        return

    # フェーズ2: 原稿生成
    logger.info("[Phase 2] 原稿生成")
    script = ScriptGenerator().generate(plugin_texts)
    logger.info(f"原稿文字数: {len(script)} 文字")

    # フェーズ3: 音声合成
    logger.info("[Phase 3] 音声合成")
    tts = TTSModule(cfg.get("tts", {}), TMP_DIR)
    audio_files = tts.synthesize_all(script)

    if not audio_files:
        logger.error("音声合成に失敗しました。終了します。")
        return

    # フェーズ4: 再生
    logger.info("[Phase 4] 再生開始")
    player = PlayerModule()
    try:
        player.play_files(audio_files)
    finally:
        player.quit()
        tts.cleanup()

    logger.info("=== 朝の情報読み上げ 完了 ===")


def main():
    parser = argparse.ArgumentParser(description="朝の情報読み上げシステム")
    parser.add_argument("--now", action="store_true", help="即時実行")
    args = parser.parse_args()

    setup_logging()

    # --now オプションまたは引数なしで即時実行
    run()


if __name__ == "__main__":
    main()
