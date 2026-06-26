"""数据面 upstream 选择测试。

pick_upstream 三阶段策略:
- header 有值 -> 按 id 精确匹配
- header 缺失 -> 按 model 匹配
- header/model 都缺失 -> 400
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Setting, Upstream
from rosetta.server.service.exceptions import ServiceError
from rosetta.server.service.selector import pick_upstream


async def _insert_upstream(
    session: AsyncSession,
    *,
    name: str,
    model: str | None = None,
    native_api: str = "messages",
    enabled: bool = True,
) -> Upstream:
    upstream = Upstream(
        name=name,
        native_api=native_api,
        provider="custom",
        base_url="https://example.com",
        api_key="sk-fake",
        model=model,
        enabled=enabled,
    )
    session.add(upstream)
    await session.commit()
    await session.refresh(upstream)
    return upstream


class TestHeaderUpstream:
    async def test_header_id_exact_match(self, session: AsyncSession) -> None:
        picked_expected = await _insert_upstream(session, name="ant-a", model="claude")
        await _insert_upstream(session, name="ant-b", model="gpt")

        picked = await pick_upstream(session, header_upstream=picked_expected.id, model="gpt")

        assert picked.id == picked_expected.id

    async def test_header_name_is_not_accepted(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="ant-a", model="claude")

        with pytest.raises(ServiceError) as exc:
            await pick_upstream(session, header_upstream="ant-a", model="claude")

        assert exc.value.status == 400
        assert exc.value.code == "upstream_not_found"

    async def test_header_not_found_400(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="ant-a")

        with pytest.raises(ServiceError) as exc:
            await pick_upstream(session, header_upstream="ghost", model="claude")

        assert exc.value.status == 400
        assert exc.value.code == "upstream_not_found"

    async def test_header_disabled_400(self, session: AsyncSession) -> None:
        upstream = await _insert_upstream(session, name="ant-a", enabled=False)

        with pytest.raises(ServiceError) as exc:
            await pick_upstream(session, header_upstream=upstream.id, model="claude")

        assert exc.value.status == 400
        assert exc.value.code == "upstream_disabled"


class TestModelUpstream:
    async def test_model_exact_match(self, session: AsyncSession) -> None:
        picked_expected = await _insert_upstream(session, name="oai", model="gpt-4o")
        await _insert_upstream(session, name="ant", model="claude-sonnet")

        picked = await pick_upstream(session, header_upstream=None, model="gpt-4o")

        assert picked.id == picked_expected.id

    async def test_disabled_model_match_is_ignored(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="disabled", model="gpt-4o", enabled=False)
        picked_expected = await _insert_upstream(session, name="enabled", model="gpt-4o")

        picked = await pick_upstream(session, header_upstream=None, model="gpt-4o")

        assert picked.id == picked_expected.id

    async def test_multiple_model_matches_use_settings_default(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="a", model="gpt-4o")
        picked_expected = await _insert_upstream(session, name="b", model="gpt-4o")
        session.add(Setting(key="default_model:gpt-4o", value=picked_expected.id))
        await session.commit()

        picked = await pick_upstream(session, header_upstream=None, model="gpt-4o")

        assert picked.id == picked_expected.id

    async def test_multiple_model_matches_without_default_400(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="a", model="gpt-4o")
        await _insert_upstream(session, name="b", model="gpt-4o")

        with pytest.raises(ServiceError) as exc:
            await pick_upstream(session, header_upstream=None, model="gpt-4o")

        assert exc.value.status == 400
        assert exc.value.code == "model_ambiguous"

    async def test_model_not_found_400(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="oai", model="gpt-4o")

        with pytest.raises(ServiceError) as exc:
            await pick_upstream(session, header_upstream=None, model="missing")

        assert exc.value.status == 400
        assert exc.value.code == "no_upstream_for_model"


class TestMissingRoutingInfo:
    async def test_no_header_no_model_400(self, session: AsyncSession) -> None:
        with pytest.raises(ServiceError) as exc:
            await pick_upstream(session, header_upstream=None, model=None)

        assert exc.value.status == 400
        assert exc.value.code == "missing_routing_info"
