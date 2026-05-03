"""Tests for P2 features: artifacts, templates, rate limiting, offline."""

import asyncio

import pytest
from unittest.mock import AsyncMock

pytestmark = pytest.mark.unit

from guild.core.artifacts import ArtifactManager
from guild.core.templates import Template, TemplateManager
from guild.core.ratelimit import RateLimiter, ToolQueue
from guild.core.offline import OfflineManager
from guild.core.storage import Storage


# --- Artifacts ---

class TestArtifactManager:
    def test_save_and_get(self, tmp_path):
        mgr = ArtifactManager(tmp_path / "artifacts", Storage(tmp_path / "db"))
        path = mgr.save("t1", "output.txt", "hello world")
        assert path.exists()
        assert mgr.get("t1", "output.txt") == "hello world"

    def test_list_for_task(self, tmp_path):
        mgr = ArtifactManager(tmp_path / "artifacts", Storage(tmp_path / "db"))
        mgr.save("t1", "a.txt", "aaa")
        mgr.save("t1", "b.txt", "bbb")
        files = mgr.list_for_task("t1")
        assert len(files) == 2

    def test_get_nonexistent(self, tmp_path):
        mgr = ArtifactManager(tmp_path / "artifacts", Storage(tmp_path / "db"))
        assert mgr.get("nope", "nope.txt") is None

    def test_list_empty_task(self, tmp_path):
        mgr = ArtifactManager(tmp_path / "artifacts", Storage(tmp_path / "db"))
        assert mgr.list_for_task("nope") == []


# --- Templates ---

class TestTemplate:
    def test_render(self):
        t = Template(name="test", task_template="Fix {bug} in {file}")
        result = t.render(bug="login crash", file="auth.py")
        assert result == "Fix login crash in auth.py"

    def test_render_no_params(self):
        t = Template(name="test", task_template="Do the thing")
        assert t.render() == "Do the thing"


class TestTemplateManager:
    def test_save_and_list(self, tmp_path):
        mgr = TemplateManager(tmp_path / "templates")
        t = Template(name="dev", description="Dev workflow", team="dev-loop",
                     task_template="Build {feature}", parameters=["feature"])
        mgr.save(t)
        templates = mgr.list()
        assert len(templates) == 1
        assert templates[0].name == "dev"

    def test_get_by_name(self, tmp_path):
        mgr = TemplateManager(tmp_path / "templates")
        mgr.save(Template(name="review", task_template="Review {pr}"))
        t = mgr.get("review")
        assert t is not None
        assert t.name == "review"

    def test_get_nonexistent(self, tmp_path):
        mgr = TemplateManager(tmp_path / "templates")
        assert mgr.get("nope") is None


# --- Rate Limiting ---

class TestRateLimiter:
    async def test_allows_within_limit(self):
        limiter = RateLimiter(max_calls=5, window_seconds=1.0)
        for _ in range(5):
            await limiter.acquire()
        assert limiter.available == 0

    async def test_available_count(self):
        limiter = RateLimiter(max_calls=10, window_seconds=60.0)
        assert limiter.available == 10
        await limiter.acquire()
        assert limiter.available == 9


class TestToolQueue:
    async def test_limits_concurrency(self):
        queue = ToolQueue(max_concurrent=2)
        results = []

        async def task(n):
            results.append(f"start-{n}")
            await asyncio.sleep(0.05)
            results.append(f"end-{n}")
            return n

        await asyncio.gather(
            queue.execute(task(1)),
            queue.execute(task(2)),
            queue.execute(task(3)),
        )
        assert len(results) == 6
        assert queue.active_count == 0


# --- Offline ---

class TestOfflineManager:
    async def test_check_connectivity_online(self):
        provider = AsyncMock()
        provider.health_check = AsyncMock(return_value=True)
        mgr = OfflineManager(provider)
        assert await mgr.check_connectivity() is True
        assert mgr.is_online is True

    async def test_check_connectivity_offline(self):
        provider = AsyncMock()
        provider.health_check = AsyncMock(return_value=False)
        mgr = OfflineManager(provider)
        assert await mgr.check_connectivity() is False
        assert mgr.is_online is False

    async def test_list_models_when_offline(self):
        provider = AsyncMock()
        provider.list_models = AsyncMock(side_effect=Exception("offline"))
        mgr = OfflineManager(provider)
        models = await mgr.list_local_models()
        assert models == []
