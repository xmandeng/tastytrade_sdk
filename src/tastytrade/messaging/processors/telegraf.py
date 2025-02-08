from tastytrade.messaging.models.events import BaseEvent
from tastytrade.messaging.processors.default import BaseEventProcessor


class TelegrafHTTP(BaseEventProcessor):
    name = "telegraf_http_v2"

    def process_event(self, event: BaseEvent) -> None:
        pass
