import logging
import time
from pathlib import Path

import pygame

logger = logging.getLogger(__name__)


class PlayerModule:
    def __init__(self):
        pygame.mixer.init()

    def play_files(self, files: list[Path]):
        """音声ファイルを順番に再生する。"""
        if not files:
            logger.warning("[player] 再生ファイルがありません")
            return

        logger.info(f"[player] {len(files)} ファイルの再生を開始します")
        for i, path in enumerate(sorted(files)):
            logger.info(f"[player] [{i+1}/{len(files)}] {path.name}")
            try:
                pygame.mixer.music.load(str(path))
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
            except Exception as e:
                logger.error(f"[player] {path.name} の再生失敗: {e}")

        logger.info("[player] 再生完了")

    def quit(self):
        pygame.mixer.quit()
