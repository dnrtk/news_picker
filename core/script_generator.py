from datetime import datetime


class ScriptGenerator:
    OPENING = "おはようございます。{date}の朝の情報をお届けします。"
    CLOSING = "以上で本日の朝の情報をお伝えしました。良い一日をお過ごしください。"

    def generate(self, plugin_texts: list[str]) -> str:
        today = datetime.now()
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        date_str = f"{today.month}月{today.day}日、{weekdays[today.weekday()]}曜日"

        parts = [self.OPENING.format(date=date_str)]
        parts.extend(plugin_texts)
        parts.append(self.CLOSING)
        return "\n\n".join(parts)
