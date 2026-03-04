import logging
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import py7zr
import requests

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com/repos/VOICEVOX/voicevox_engine/releases/latest"
ENGINE_STARTUP_TIMEOUT = 90  # seconds


class TTSModule:
    def __init__(self, tts_config: dict, tmp_dir: Path):
        self.config = tts_config
        self.tmp_dir = tmp_dir
        self.tmp_dir.mkdir(exist_ok=True)
        self._engine_process: subprocess.Popen | None = None

        vox_cfg = tts_config.get("voicevox", {})
        self.voicevox_host = vox_cfg.get("host", "http://localhost:50021")
        self.speaker_id = vox_cfg.get("speaker_id", 3)
        self.speed_scale = vox_cfg.get("speed_scale", 1.1)
        self.volume_scale = vox_cfg.get("volume_scale", 1.0)
        self.engine_dir = Path(vox_cfg.get("engine_dir", "voicevox_engine"))
        self.download_url: str | None = vox_cfg.get("download_url")

    def synthesize_all(self, text: str) -> list[Path]:
        """テキストを分割して音声ファイルを生成し、ファイルパスのリストを返す。"""
        chunks = self._split_text(text)
        logger.info(f"[tts] {len(chunks)} チャンクに分割")

        if not self._ensure_engine():
            logger.error("[tts] VOICEVOX ENGINE を起動できませんでした。")
            return []
        return self._synthesize_voicevox(chunks)

    def _ensure_engine(self) -> bool:
        """VOICEVOX が起動済みでなければ自動起動する。必要に応じて自動ダウンロード。"""
        if self._check_voicevox():
            logger.info("[tts] VOICEVOX は既に起動中です")
            return True

        exe = self.engine_dir / "run.exe"
        if not exe.exists():
            logger.info("[tts] VOICEVOX ENGINE が見つかりません。ダウンロードします...")
            if not self._download_engine():
                return False

        logger.info(f"[tts] VOICEVOX ENGINE を起動します: {exe}")
        try:
            self._engine_process = subprocess.Popen(
                [str(exe.resolve())],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            logger.error(f"[tts] VOICEVOX ENGINE の起動に失敗しました: {e}")
            return False

        logger.info(f"[tts] VOICEVOX ENGINE の起動を待機中（最大 {ENGINE_STARTUP_TIMEOUT} 秒）...")
        for i in range(ENGINE_STARTUP_TIMEOUT):
            if self._check_voicevox():
                logger.info(f"[tts] VOICEVOX ENGINE 起動完了（{i + 1} 秒）")
                return True
            time.sleep(1)

        logger.error(f"[tts] VOICEVOX ENGINE が {ENGINE_STARTUP_TIMEOUT} 秒以内に応答しませんでした")
        self._engine_process.terminate()
        self._engine_process = None
        return False

    def _download_engine(self) -> bool:
        """設定済み URL または GitHub API から VOICEVOX ENGINE をダウンロード・展開する。"""
        url = self.download_url
        if url:
            return self._download_from_url(url)
        return self._download_from_github_api()

    def _download_from_url(self, url: str) -> bool:
        """指定 URL からダウンロードして展開する。フォーマットは URL から自動判定。"""
        if ".7z." in url:
            return self._download_split_7z(url)
        if url.endswith(".zip"):
            return self._download_and_extract_zip(url)
        logger.error(f"[tts] 未対応のアーカイブ形式です: {url}")
        return False

    def _download_split_7z(self, url_part1: str) -> bool:
        """スプリット 7z アーカイブ（.7z.001, .7z.002, ...）を全パートダウンロードして展開する。"""
        # .001 より前の部分を取得し、.001 .002 ... と順に試みる
        base_url = re.sub(r'\.\d{3}$', '', url_part1)  # ".001" を除去
        part_paths: list[Path] = []
        download_dir = Path(".")

        for i in range(1, 999):
            part_url = f"{base_url}.{i:03d}"
            part_name = part_url.split("/")[-1]
            part_path = download_dir / part_name

            try:
                logger.info(f"[tts] ダウンロード中: {part_name}")
                with requests.get(part_url, stream=True, timeout=600) as r:
                    if r.status_code == 404:
                        logger.info(f"[tts] {part_name} が見つかりません。全 {i - 1} パートのダウンロード完了")
                        break
                    r.raise_for_status()
                    total = int(r.headers.get("content-length", 0))
                    downloaded = 0
                    last_pct = -1
                    with open(part_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 1024):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total:
                                pct = int(downloaded / total * 10) * 10
                                if pct != last_pct:
                                    logger.info(
                                        f"[tts]   {pct}%"
                                        f" ({downloaded // 1024 // 1024} MB"
                                        f" / {total // 1024 // 1024} MB)"
                                    )
                                    last_pct = pct
                part_paths.append(part_path)
            except Exception as e:
                logger.error(f"[tts] {part_name} のダウンロードに失敗しました: {e}")
                for p in part_paths:
                    p.unlink(missing_ok=True)
                return False

        if not part_paths:
            logger.error("[tts] ダウンロードするファイルが見つかりませんでした")
            return False

        return self._extract_7z(part_paths[0], part_paths)

    def _download_and_extract_zip(self, url: str) -> bool:
        """単一 zip ファイルをダウンロードして展開する。"""
        zip_name = url.split("/")[-1]
        zip_path = Path(zip_name)
        try:
            logger.info(f"[tts] ダウンロード中: {zip_name}")
            with requests.get(url, stream=True, timeout=600) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                last_pct = -1
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = int(downloaded / total * 10) * 10
                            if pct != last_pct:
                                logger.info(f"[tts]   {pct}% ({downloaded // 1024 // 1024} MB / {total // 1024 // 1024} MB)")
                                last_pct = pct

            logger.info(f"[tts] 展開中: {zip_path}")
            self.engine_dir.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(self.engine_dir.parent)
            zip_path.unlink()
            return self._locate_and_rename_engine_dir()
        except Exception as e:
            logger.error(f"[tts] zip ダウンロード・展開に失敗しました: {e}")
            zip_path.unlink(missing_ok=True)
            return False

    def _extract_7z(self, first_part: Path, all_parts: list[Path]) -> bool:
        """7z（スプリット含む）を展開し、一時ファイルを削除する。"""
        try:
            logger.info(f"[tts] 展開中: {first_part}")
            self.engine_dir.parent.mkdir(parents=True, exist_ok=True)
            with py7zr.SevenZipFile(first_part, mode="r") as sz:
                sz.extractall(path=self.engine_dir.parent)
            for p in all_parts:
                p.unlink(missing_ok=True)
            return self._locate_and_rename_engine_dir()
        except Exception as e:
            logger.error(f"[tts] 7z 展開に失敗しました: {e}")
            for p in all_parts:
                p.unlink(missing_ok=True)
            return False

    def _locate_and_rename_engine_dir(self) -> bool:
        """展開後の run.exe を探し、engine_dir の名前に合わせてリネームする。"""
        exe_candidates = list(self.engine_dir.parent.rglob("run.exe"))
        if not exe_candidates:
            logger.error("[tts] 展開後に run.exe が見つかりません")
            return False

        extracted_dir = exe_candidates[0].parent
        if extracted_dir.resolve() != self.engine_dir.resolve():
            if self.engine_dir.exists():
                shutil.rmtree(self.engine_dir)
            extracted_dir.rename(self.engine_dir)

        logger.info(f"[tts] VOICEVOX ENGINE のセットアップ完了: {self.engine_dir}")
        return True

    def _download_from_github_api(self) -> bool:
        """GitHub API で最新リリースの Windows CPU 版を探してダウンロードする。"""
        try:
            logger.info("[tts] GitHub からリリース情報を取得中...")
            resp = requests.get(GITHUB_API_URL, timeout=30)
            resp.raise_for_status()
            release = resp.json()

            # windows-cpu のアセットを探す（.7z.001 または .zip）
            asset = None
            for a in release["assets"]:
                name = a["name"].lower()
                if "windows" in name and "cpu" in name:
                    if ".7z.001" in name or name.endswith(".zip"):
                        asset = a
                        break

            if asset is None:
                logger.error("[tts] Windows CPU 版のアセットが見つかりません")
                logger.error(f"[tts] リリースページ: {release.get('html_url', '')}")
                return False

            logger.info(f"[tts] アセット: {asset['name']}")
            return self._download_from_url(asset["browser_download_url"])

        except Exception as e:
            logger.error(f"[tts] GitHub API からの取得に失敗しました: {e}")
            return False

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

    def cleanup(self):
        """tmp ディレクトリの音声ファイルを削除し、自動起動したエンジンを終了する。"""
        for f in self.tmp_dir.glob("*.wav"):
            f.unlink()
        logger.info("[tts] 一時ファイルを削除しました")

        if self._engine_process is not None:
            logger.info("[tts] VOICEVOX ENGINE を終了します")
            self._engine_process.terminate()
            self._engine_process = None
