import os
from pathlib import Path

import yaml
from dotenv import load_dotenv


def load_config(config_path: str = "config.yaml") -> dict:
    """config.yaml を読み込んで返す。"""
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_env():
    """環境変数を読み込む。OS 環境変数を優先し、未設定の場合のみ .env を参照する。"""
    load_dotenv(override=False)


def get_env(key: str) -> str:
    """環境変数を取得する。未設定の場合は ValueError を送出する。"""
    value = os.environ.get(key)
    if not value:
        raise ValueError(
            f"環境変数 '{key}' が設定されていません。"
            f".env ファイルまたは OS の環境変数に設定してください。"
        )
    return value
