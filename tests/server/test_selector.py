"""数据面 upstream 选择测试。"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Upstream
from rosetta.server.repository.upstream import UpstreamRepo
from rosetta.server.service.exceptions import ServiceError
from rosetta.server.service.selector import select_upstream


async def _insert_upstream(
    session: AsyncSession,
    *,
    name: str,
    model: str = "test-model",
    native_api: str = "messages",
    enabled: bool = True,
    alias: str | None = None,
    is_default: bool = True,
) -> Upstream:
    repo = UpstreamRepo(session)
    upstream = await repo.create(
        name=name,
        native_api=native_api,
        provider="custom",
        base_url="https://example.com",
        api_key="sk-fake",
        model=model,
        enabled=enabled,
    )
    model_id = await repo.get_or_create_model(model, alias=alias)
    await repo.set_upstream_model(upstream.id, model_id, is_default=is_default)
    if alias is not None:
        await repo.set_model_alias(model, alias)
    return upstream


class TestHeaderUpstream:
    async def test_header_id_exact_match(self, session: AsyncSession) -> None:
        picked_expected = await _insert_upstream(session, name="ant-a", model="claude")
        await _insert_upstream(session, name="ant-b", model="gpt")

        selection = await select_upstream(
            session, header_upstream=picked_expected.id, model="gpt"
        )

        assert selection.upstream.id == picked_expected.id
        assert selection.rewrite_model_to is None

    async def test_header_name_is_not_accepted(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="ant-a", model="claude")

        with pytest.raises(ServiceError) as exc:
            await select_upstream(session, header_upstream="ant-a", model="claude")

        assert exc.value.status == 400
        assert exc.value.code == "upstream_not_found"

    async def test_header_not_found_400(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="ant-a")

        with pytest.raises(ServiceError) as exc:
            await select_upstream(session, header_upstream="ghost", model="claude")

        assert exc.value.status == 400
        assert exc.value.code == "upstream_not_found"

    async def test_header_disabled_400(self, session: AsyncSession) -> None:
        upstream = await _insert_upstream(session, name="ant-a", enabled=False)

        with pytest.raises(ServiceError) as exc:
            await select_upstream(session, header_upstream=upstream.id, model="claude")

        assert exc.value.status == 400
        assert exc.value.code == "upstream_disabled"


class TestModelUpstream:
    async def test_model_exact_match(self, session: AsyncSession) -> None:
        picked_expected = await _insert_upstream(session, name="oai", model="gpt-4o")
        await _insert_upstream(session, name="ant", model="claude-sonnet")

        selection = await select_upstream(session, header_upstream=None, model="gpt-4o")

        assert selection.upstream.id == picked_expected.id
        assert selection.rewrite_model_to is None

    async def test_disabled_upstream_match_is_ignored(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="disabled", model="gpt-4o", enabled=False)
        picked_expected = await _insert_upstream(session, name="enabled", model="gpt-4o")

        selection = await select_upstream(session, header_upstream=None, model="gpt-4o")

        assert selection.upstream.id == picked_expected.id

    async def test_multiple_model_matches_use_upstream_model_default(
        self, session: AsyncSession
    ) -> None:
        await _insert_upstream(session, name="a", model="gpt-4o", is_default=False)
        picked_expected = await _insert_upstream(
            session, name="b", model="gpt-4o", is_default=True
        )

        selection = await select_upstream(session, header_upstream=None, model="gpt-4o")

        assert selection.upstream.id == picked_expected.id

    async def test_model_alias_selects_model_and_rewrites_to_upstream_model(
        self, session: AsyncSession
    ) -> None:
        picked_expected = await _insert_upstream(
            session,
            name="deepseek",
            model="deepseek-v4-flash",
            alias="gpt-5-codex",
        )

        selection = await select_upstream(
            session, header_upstream=None, model="gpt-5-codex"
        )

        assert selection.upstream.id == picked_expected.id
        assert selection.alias == "gpt-5-codex"
        assert selection.rewrite_model_to == "deepseek-v4-flash"

    async def test_model_not_found_400(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="oai", model="gpt-4o")

        with pytest.raises(ServiceError) as exc:
            await select_upstream(session, header_upstream=None, model="missing")

        assert exc.value.status == 400
        assert exc.value.code == "no_upstream_for_model"


class TestMissingRoutingInfo:
    async def test_no_header_no_model_400(self, session: AsyncSession) -> None:
        with pytest.raises(ServiceError) as exc:
            await select_upstream(session, header_upstream=None, model=None)

        assert exc.value.status == 400
        assert exc.value.code == "missing_routing_info"