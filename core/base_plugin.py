from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ContentItem:
    title: str
    body: str
    source: str
    metadata: dict = field(default_factory=dict)


class BasePlugin(ABC):
    name: str = ""
    order: int = 99
    enabled: bool = True

    def __init__(self, config: dict):
        self.config = config
        self.enabled = config.get("enabled", True)
        self.order = config.get("order", self.order)

    @abstractmethod
    def fetch(self) -> list[ContentItem]:
        """情報を取得して ContentItem のリストを返す。失敗時は空リストを返す。"""
        ...

    @abstractmethod
    def format(self, items: list[ContentItem]) -> str:
        """ContentItem リストを読み上げ用の日本語テキストに整形して返す。"""
        ...
