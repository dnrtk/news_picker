import importlib
import logging
from typing import TYPE_CHECKING

from core.base_plugin import BasePlugin

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

PLUGIN_MAP = {
    "news": ("plugins.news_plugin", "NewsPlugin"),
    "timetree": ("plugins.timetree_plugin", "TimeTreePlugin"),
}


class PluginRunner:
    def __init__(self, plugin_configs: list[dict]):
        self.plugins: list[BasePlugin] = []
        for cfg in plugin_configs:
            name = cfg.get("name")
            enabled = cfg.get("enabled", True)
            if not enabled:
                logger.info(f"[{name}] disabled, skip")
                continue
            if name not in PLUGIN_MAP:
                logger.warning(f"[{name}] 未知のプラグインです。スキップします。")
                continue
            module_path, class_name = PLUGIN_MAP[name]
            try:
                module = importlib.import_module(module_path)
                plugin_class = getattr(module, class_name)
                self.plugins.append(plugin_class(cfg))
                logger.info(f"[{name}] ロード完了")
            except Exception as e:
                logger.error(f"[{name}] ロード失敗: {e}")

        self.plugins.sort(key=lambda p: p.order)

    def run(self) -> list[str]:
        """全プラグインを order 順に実行し、各 format() 結果のリストを返す。"""
        results = []
        for plugin in self.plugins:
            name = plugin.name
            try:
                logger.info(f"[{name}] fetch 開始")
                items = plugin.fetch()
                logger.info(f"[{name}] {len(items)} 件取得")
                text = plugin.format(items)
                results.append(text)
            except Exception as e:
                logger.error(f"[{name}] 実行エラー: {e}")
        return results
