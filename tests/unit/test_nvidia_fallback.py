import unittest
import asyncio

from rankstein.domain import get_registry
from backend.scripts.turbo_articles import _call_nvidia_nemotron_for_article


class TestNvidiaNemotronFallback(unittest.TestCase):
    def test_call_nvidia_nemotron_for_article(self):
        domain = get_registry().get("recetadolce")
        result = asyncio.run(_call_nvidia_nemotron_for_article("tarta de manzana", domain))
        # Direct NVIDIA generation is retired in favor of Hermes; returns None
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
