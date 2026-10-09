"""Test doubles shared by several test modules."""
from app.llm import MockTarget


class SpyTarget(MockTarget):
    """MockTarget that records what it was sent."""

    def __init__(self, label="spy@test", **kw):
        super().__init__(label, chunk_delay_s=0, **kw)
        self.histories, self.systems, self.langs = [], [], []

    async def stream(self, system, history, lang, flatten=False):
        self.histories.append(history)
        self.systems.append(system)
        self.langs.append(lang)
        async for item in super().stream(system, history, lang, flatten):
            yield item
