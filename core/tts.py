import logging
import re
import shutil
from io import BytesIO
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


class TTSModule:
    def __init__(self, tts_config: dict, tmp_dir: Path):
        self.config = tts_config
        self.tmp_dir = tmp_dir
        self.tmp_dir.mkdir(exist_ok=True)
        self.engine = tts_config.get("engine", "voicevox")

        vox_cfg = tts_config.get("voicevox", {})
        self.voicevox_host = vox_cfg.get("host", "http://localhost:50021")
        self.speaker_id = vox_cfg.get("speaker_id", 3)
        self.speed_scale = vox_cfg.get("speed_scale", 1.1)
        self.volume_scale = vox_cfg.get("volume_scale", 1.0)

    def synthesize_all(self, text: str) -> list[Path]:
        """テキストを分割して音声ファイルを生成し、ファイルパスのリストを返す。"""
        chunks = self._split_text(text)
        logger.info(f"[tts] {len(chunks)} チャンクに分割")

        if self.engine == "voicevox" and self._check_voicevox():
            return self._synthesize_voicevox(chunks)
        else:
            if self.engine == "voicevox":
                logger.warning("[tts] VOICEVOX 接続不可。gTTS にフォールバック")
            return self._synthesize_gtts(chunks)

    def _split_text(self, text: str, max_len: int = 200) -> list[str]:
        """句点・改行で分割し、max_len 文字以内のチャンクにまとめる。"""
        sentences = re.split(r'(?<=[。！？\n])', text)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(current) + len(sentence) <= max_len:
                current += sentence
            else:
                if current:
                    chunks.append(current)
                current = sentence
        if current:
            chunks.append(current)
        return chunks

    def _check_voicevox(self) -> bool:
        try:
            resp = requests.get(f"{self.voicevox_host}/version", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def _synthesize_voicevox(self, chunks: list[str]) -> list[Path]:
        files: list[Path] = []
        for i, chunk in enumerate(chunks):
            out_path = self.tmp_dir / f"{i:04d}.wav"
            try:
                query_resp = requests.post(
                    f"{self.voicevox_host}/audio_query",
                    params={"text": chunk, "speaker": self.speaker_id},
                    timeout=30,
                )
                query_resp.raise_for_status()
                query = query_resp.json()
                query["speedScale"] = self.speed_scale
                query["volumeScale"] = self.volume_scale

                synth_resp = requests.post(
                    f"{self.voicevox_host}/synthesis",
                    params={"speaker": self.speaker_id},
                    json=query,
                    timeout=60,
                )
                synth_resp.raise_for_status()
                out_path.write_bytes(synth_resp.content)
                files.append(out_path)
                logger.info(f"[tts] VOICEVOX [{i+1}/{len(chunks)}] -> {out_path.name}")
            except Exception as e:
                logger.error(f"[tts] VOICEVOX チャンク {i} 失敗: {e}")
        return files

    def _synthesize_gtts(self, chunks: list[str]) -> list[Path]:
        from gtts import gTTS
        files: list[Path] = []
        for i, chunk in enumerate(chunks):
            out_path = self.tmp_dir / f"{i:04d}.mp3"
            try:
                tts = gTTS(text=chunk, lang="ja")
                tts.save(str(out_path))
                files.append(out_path)
                logger.info(f"[tts] gTTS [{i+1}/{len(chunks)}] -> {out_path.name}")
            except Exception as e:
                logger.error(f"[tts] gTTS チャンク {i} 失敗: {e}")
        return files

    def cleanup(self):
        """tmp ディレクトリの音声ファイルを削除する。"""
        for f in self.tmp_dir.glob("*.wav"):
            f.unlink()
        for f in self.tmp_dir.glob("*.mp3"):
            f.unlink()
        logger.info("[tts] 一時ファイルを削除しました")
