"""The Anthropic API call behind the API rater (fiftyoff/rater.py). The only module that imports the SDK; only
rater.py (the entry point) imports it, never the tracker (rule 7). The key comes from ANTHROPIC_API_KEY in .env
and is never logged.
"""

from __future__ import annotations

import anthropic

from .rater import RaterConfig, Reply


def make_call(client: anthropic.Anthropic | None = None):
    client = client or anthropic.Anthropic(max_retries=3)

    def call(system: str, user: str, cfg: RaterConfig) -> Reply:
        # The rubric is the stable prefix, cached across batches; the products follow it. 1-hour TTL: batches run 15 min
        # apart, so a 5-minute entry expired before every batch (written each time, never read); each read restarts
        # the hour. Thinking stays adaptive (Sonnet 5.5 can't disable it); effort keeps it short for a rating task.
        m = client.messages.create(
            model=cfg.model_id, max_tokens=cfg.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": cfg.effort},
        )
        u = m.usage
        return Reply(text="".join(b.text for b in m.content if b.type == "text"), stop_reason=m.stop_reason,
                     request_id=getattr(m, "_request_id", None), input_tokens=u.input_tokens or 0,
                     output_tokens=u.output_tokens or 0, cache_read_tokens=u.cache_read_input_tokens or 0,
                     cache_write_tokens=u.cache_creation_input_tokens or 0)

    return call
