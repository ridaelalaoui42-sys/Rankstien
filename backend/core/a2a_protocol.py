"""RankStein — A2A Protocol (Agent-to-Agent Communication)
Central message bus for inter-agent communication with topic routing.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger("rankstein.a2a")


@dataclass
class A2AMessage:
    message_id: str
    sender_agent: str
    receiver_agent: str
    topic: str
    content: dict
    metadata: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: str = "sent"


class A2ABus:
    """Central message bus for agent-to-agent communication."""

    _instance: A2ABus | None = None

    def __init__(self):
        self._agents: dict[str, dict] = {}
        self._subscribers: dict[str, dict[str, list[Callable]]] = {}
        self._queues: dict[str, asyncio.Queue] = {}

    @classmethod
    def get_instance(cls) -> A2ABus:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_agent(self, agent_id: str, capabilities: dict) -> None:
        self._agents[agent_id] = {
            "capabilities": capabilities,
            "status": "active",
            "registered_at": datetime.now(UTC).isoformat(),
        }
        self._queues[agent_id] = asyncio.Queue(maxsize=1000)
        logger.info("Agent registered: %s (capabilities: %s)", agent_id, list(capabilities.keys()))

    def unregister_agent(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)
        self._queues.pop(agent_id, None)
        for topic in list(self._subscribers.keys()):
            self._subscribers[topic].pop(agent_id, None)
        logger.info("Agent unregistered: %s", agent_id)

    def subscribe(self, agent_id: str, topic: str, callback: Callable) -> None:
        if topic not in self._subscribers:
            self._subscribers[topic] = {}
        if agent_id not in self._subscribers[topic]:
            self._subscribers[topic][agent_id] = []
        self._subscribers[topic][agent_id].append(callback)
        logger.info("Agent %s subscribed to topic: %s", agent_id, topic)

    def publish(self, sender: str, topic: str, message: dict) -> None:
        msg = A2AMessage(
            message_id=f"{sender}_{topic}_{datetime.now(UTC).timestamp()}",
            sender_agent=sender,
            receiver_agent="*",
            topic=topic,
            content=message,
        )
        # Match exact topic and wildcard patterns
        matched_topics = [
            t
            for t in self._subscribers
            if t == topic or t.endswith(".*") or topic.startswith(t.rsplit(".", 1)[0])
        ]
        for matched_topic in matched_topics:
            for agent_id, callbacks in self._subscribers.get(matched_topic, {}).items():
                for cb in callbacks:
                    try:
                        if asyncio.iscoroutinefunction(cb):
                            asyncio.create_task(cb(msg))
                        else:
                            cb(msg)
                    except Exception as e:
                        logger.error("Callback error for agent %s on topic %s: %s", agent_id, topic, e)
        # Also push to agent queue if receiver specified
        receiver = message.get("receiver")
        if receiver and receiver in self._queues:
            try:
                self._queues[receiver].put_nowait(msg)
            except asyncio.QueueFull:
                logger.warning("Queue full for agent %s, dropping message", receiver)
        logger.info("Published to topic '%s' from %s (receivers: %d)", topic, sender, len(matched_topics))

    async def receive(self, agent_id: str, timeout: float = 60.0) -> A2AMessage | None:
        queue = self._queues.get(agent_id)
        if not queue:
            return None
        try:
            return await asyncio.wait_for(queue.get(), timeout=timeout)
        except TimeoutError:
            return None

    def get_agent(self, agent_id: str) -> dict | None:
        agent = self._agents.get(agent_id)
        return {"id": agent_id, **agent} if agent else None

    def list_agents(self) -> list[dict]:
        return [{"id": aid, **info} for aid, info in self._agents.items()]

    def get_agents_for_domain(self, domain_id: str) -> list[dict]:
        return [a for a in self.list_agents() if a.get("domain_id") == domain_id]

    def unregister_domain_agents(self, domain_id: str) -> None:
        to_remove = [aid for aid, info in self._agents.items() if info.get("domain_id") == domain_id]
        for aid in to_remove:
            self.unregister_agent(aid)
