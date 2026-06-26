"""UpstreamRepo 的 upstream 管理行为。"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Setting, Upstream
from rosetta.server.repository.upstream import UpstreamRepo


async def _insert(
    session: AsyncSession,
    *,
    name: str,
    native_api: str = "messages",
    enabled: bool = True,
) -> Upstream:
    u = Upstream(
        name=name,
        native_api=native_api,
        provider="custom",
        base_url="https://example.com",
        api_key="sk-fake",
        enabled=enabled,
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    return u


class TestModelDefault:
    async def test_model_default_missing_returns_none(self, session: AsyncSession) -> None:
        assert await UpstreamRepo(session).default_model_upstream_id("gpt-4o") is None

    async def test_set_model_default(self, session: AsyncSession) -> None:
        upstream = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)

        result = await repo.set_model_default(upstream.id, "gpt-4o")

        assert result.id == upstream.id
        assert await repo.default_model_upstream_id("gpt-4o") == upstream.id
        assert await repo.list_model_defaults() == {"gpt-4o": upstream.id}

    async def test_set_model_default_unknown_raises(self, session: AsyncSession) -> None:
        repo = UpstreamRepo(session)
        with pytest.raises(LookupError):
            await repo.set_model_default("ghost", "gpt-4o")

    async def test_delete_upstream_clears_matching_model_default(
        self, session: AsyncSession
    ) -> None:
        upstream = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        await repo.set_model_default(upstream.id, "gpt-4o")

        await repo.delete(upstream)

        assert await repo.default_model_upstream_id("gpt-4o") is None
        assert await repo.list_model_defaults() == {}

    async def test_delete_upstream_clears_legacy_name_model_default(
        self, session: AsyncSession
    ) -> None:
        from rosetta.server.database.models import Setting

        upstream = await _insert(session, name="legacy", native_api="messages")
        session.add(Setting(key="default_model:gpt-legacy", value="legacy"))
        await session.commit()

        await UpstreamRepo(session).delete(upstream)

        assert await session.get(Setting, "default_model:gpt-legacy") is None


class TestSetupAliases:
    async def test_list_and_delete_setup_aliases(self, session: AsyncSession) -> None:
        upstream = await _insert(session, name="alias-owner")
        session.add_all(
            [
                Setting(key="setup:codex:gpt-5.5", value=upstream.id),
                Setting(key="setup:claude:sonnet", value=upstream.id),
                Setting(key="setup:codex", value="gpt-5.5"),
                Setting(key="setup:codex:other", value="other-upstream"),
            ]
        )
        await session.commit()

        repo = UpstreamRepo(session)
        assert await repo.list_setup_model_aliases(upstream.id) == [
            ("claude", "sonnet"),
            ("codex", "gpt-5.5"),
        ]

        assert await repo.delete_setup_model_alias(upstream.id, "codex", "gpt-5.5") is True
        assert await session.get(Setting, "setup:codex:gpt-5.5") is None
        assert await session.get(Setting, "setup:codex") is None
        assert await repo.delete_setup_model_alias(upstream.id, "codex", "missing") is False

    async def test_delete_upstream_clears_last_setup_alias_pointer(
        self, session: AsyncSession
    ) -> None:
        upstream = await _insert(session, name="alias-owner")
        session.add_all(
            [
                Setting(key="setup:codex:gpt-5.5", value=upstream.id),
                Setting(key="setup:codex", value="gpt-5.5"),
            ]
        )
        await session.commit()

        await UpstreamRepo(session).delete(upstream)

        assert await session.get(Setting, "setup:codex:gpt-5.5") is None
        assert await session.get(Setting, "setup:codex") is None

class TestUpdate:
    async def test_update_single_field(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        result = await repo.update(a.id, base_url="https://new.example.com")
        assert result.base_url == "https://new.example.com"
        assert result.name == "a"  # 其他字段不动

    async def test_update_unknown_id_raises(self, session: AsyncSession) -> None:
        repo = UpstreamRepo(session)
        with pytest.raises(LookupError):
            # mock seed 占了 "0"*32,用 "f"*32 一定不存在
            await repo.update("f" * 32, name="ghost")

    async def test_update_name_conflict(self, session: AsyncSession) -> None:
        await _insert(session, name="a", native_api="messages")
        b = await _insert(session, name="b", native_api="messages")
        repo = UpstreamRepo(session)

        with pytest.raises(IntegrityError):
            await repo.update(b.id, name="a")

    async def test_update_native_api(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        result = await repo.update(a.id, native_api="completions")
        assert result.native_api == "completions"

    async def test_update_clear_api_key(self, session: AsyncSession) -> None:
        """显式传 None 清 api_key;不传字段保持原值。"""
        a = await _insert(session, name="a")
        assert a.api_key == "sk-fake"
        repo = UpstreamRepo(session)
        result = await repo.update(a.id, api_key=None)
        assert result.api_key is None

    async def test_update_omit_api_key_keeps_original(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a")
        repo = UpstreamRepo(session)
        result = await repo.update(a.id, base_url="https://x")
        assert result.api_key == "sk-fake"

    async def test_update_set_model(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a")
        repo = UpstreamRepo(session)
        result = await repo.update(a.id, model="claude-sonnet-4-5")
        assert result.model == "claude-sonnet-4-5"

