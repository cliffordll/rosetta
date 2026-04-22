"""数据面 provider 选择测试(DESIGN §8.4 的 7 条 rule · 阶段 3.1)。

覆盖:
- parse_model 的 4 种 body 形态
- rule 2:header 精确匹配(含不存在 / 被禁用的 400)
- rule 3-4:routes 按 (priority ASC, id ASC) 扫 + fnmatch
- rule 5:无 route 命中时兜底第一个 enabled provider
- rule 6:命中 route 但 provider 失效 → 503
- rule 7:无任何 enabled provider → 503
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Provider, Route
from rosetta.server.dataplane.router import parse_model, pick_provider


async def _insert_provider(
    session: AsyncSession, *, name: str, type_: str = "anthropic", enabled: bool = True
) -> Provider:
    p = Provider(name=name, type=type_, api_key="sk-fake", enabled=enabled)
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


async def _insert_route(
    session: AsyncSession, *, provider_id: int, model_glob: str, priority: int = 100
) -> Route:
    r = Route(provider_id=provider_id, model_glob=model_glob, priority=priority)
    session.add(r)
    await session.commit()
    await session.refresh(r)
    return r


# ---------- parse_model ----------


class TestParseModel:
    def test_valid_body(self) -> None:
        assert parse_model(b'{"model": "claude-haiku-4-5"}') == "claude-haiku-4-5"

    def test_missing_model(self) -> None:
        assert parse_model(b'{"messages": []}') is None

    def test_model_non_string(self) -> None:
        assert parse_model(b'{"model": 123}') is None

    def test_invalid_json(self) -> None:
        assert parse_model(b"not json") is None

    def test_non_dict_top_level(self) -> None:
        assert parse_model(b"[]") is None


# ---------- rule 2:header 绕路 ----------


class TestHeaderOverride:
    async def test_header_exact_match(self, session: AsyncSession) -> None:
        p1 = await _insert_provider(session, name="ant-a")
        _ = await _insert_provider(session, name="ant-b")
        picked = await pick_provider(session, model=None, header_provider="ant-a")
        assert picked.id == p1.id

    async def test_header_not_found_400(self, session: AsyncSession) -> None:
        await _insert_provider(session, name="ant-a")
        with pytest.raises(HTTPException) as exc:
            await pick_provider(session, model=None, header_provider="ghost")
        assert exc.value.status_code == 400
        assert exc.value.detail["error"]["code"] == "provider_not_found"

    async def test_header_disabled_400(self, session: AsyncSession) -> None:
        await _insert_provider(session, name="ant-a", enabled=False)
        with pytest.raises(HTTPException) as exc:
            await pick_provider(session, model=None, header_provider="ant-a")
        assert exc.value.status_code == 400
        assert exc.value.detail["error"]["code"] == "provider_disabled"

    async def test_header_bypasses_routes(self, session: AsyncSession) -> None:
        """header 存在时不应看 routes(即使 model 明显匹配另一条)。"""
        p_ant = await _insert_provider(session, name="ant")
        p_oai = await _insert_provider(session, name="oai", type_="openai")
        await _insert_route(session, provider_id=p_ant.id, model_glob="claude-*", priority=1)
        # model 匹配 claude-*,正常会选 ant;但 header 指定 oai
        picked = await pick_provider(
            session, model="claude-haiku-4-5", header_provider="oai"
        )
        assert picked.id == p_oai.id


# ---------- rule 3-4:routes 匹配 ----------


class TestRouteMatch:
    async def test_glob_match_picks_provider(self, session: AsyncSession) -> None:
        p_ant = await _insert_provider(session, name="ant")
        _ = await _insert_provider(session, name="oai", type_="openai")
        await _insert_route(session, provider_id=p_ant.id, model_glob="claude-*")
        picked = await pick_provider(
            session, model="claude-haiku-4-5", header_provider=None
        )
        assert picked.id == p_ant.id

    async def test_priority_asc_order(self, session: AsyncSession) -> None:
        """priority 小的先命中(DESIGN §8.4 rule 3)。"""
        p_a = await _insert_provider(session, name="a")
        p_b = await _insert_provider(session, name="b")
        # 两条 route 同样匹配 claude-*,priority 更小的 b 先扫到
        await _insert_route(session, provider_id=p_a.id, model_glob="claude-*", priority=5)
        await _insert_route(session, provider_id=p_b.id, model_glob="claude-*", priority=1)
        picked = await pick_provider(
            session, model="claude-haiku-4-5", header_provider=None
        )
        assert picked.id == p_b.id

    async def test_id_asc_when_priority_tie(self, session: AsyncSession) -> None:
        """priority 相同时按 id ASC(插入顺序),稳定排序。"""
        p_first = await _insert_provider(session, name="first")
        p_second = await _insert_provider(session, name="second")
        await _insert_route(session, provider_id=p_first.id, model_glob="gpt-*", priority=10)
        await _insert_route(session, provider_id=p_second.id, model_glob="gpt-*", priority=10)
        picked = await pick_provider(session, model="gpt-4o-mini", header_provider=None)
        assert picked.id == p_first.id


# ---------- rule 5:兜底 ----------


class TestFallback:
    async def test_no_route_match_picks_first_enabled(self, session: AsyncSession) -> None:
        _ = await _insert_provider(session, name="ant", enabled=False)  # 禁用跳过
        p_oai = await _insert_provider(session, name="oai", type_="openai")
        _ = await _insert_provider(session, name="foo", type_="custom")
        # 无 route;model 任意
        picked = await pick_provider(session, model="unknown-model", header_provider=None)
        assert picked.id == p_oai.id

    async def test_routes_exist_but_none_match(self, session: AsyncSession) -> None:
        """routes 有但都不 match → 走兜底。"""
        p_ant = await _insert_provider(session, name="ant")
        _ = await _insert_route(session, provider_id=p_ant.id, model_glob="claude-*")
        p_oai = await _insert_provider(session, name="oai", type_="openai")
        # gpt-xxx 不匹配 claude-*;兜底选第一个 enabled = ant(id 小)
        picked = await pick_provider(session, model="gpt-4o-mini", header_provider=None)
        assert picked.id == p_ant.id
        # 仅保证 oai 也存在(避免 test 被误判为只能选唯一 provider)
        assert p_oai.id > p_ant.id


# ---------- rule 6:命中 route 但 provider 失效 ----------


class TestRouteUnavailable:
    async def test_matched_provider_disabled_503(self, session: AsyncSession) -> None:
        p_ant = await _insert_provider(session, name="ant", enabled=False)
        await _insert_route(session, provider_id=p_ant.id, model_glob="claude-*")
        with pytest.raises(HTTPException) as exc:
            await pick_provider(
                session, model="claude-haiku-4-5", header_provider=None
            )
        assert exc.value.status_code == 503
        assert exc.value.detail["error"]["code"] == "provider_disabled"


# ---------- rule 7:无任何 enabled provider ----------


class TestNoProviderAvailable:
    async def test_empty_db_503(self, session: AsyncSession) -> None:
        with pytest.raises(HTTPException) as exc:
            await pick_provider(session, model="claude-haiku-4-5", header_provider=None)
        assert exc.value.status_code == 503
        assert exc.value.detail["error"]["code"] == "no_provider_available"

    async def test_all_disabled_503(self, session: AsyncSession) -> None:
        await _insert_provider(session, name="ant", enabled=False)
        await _insert_provider(session, name="oai", type_="openai", enabled=False)
        with pytest.raises(HTTPException) as exc:
            await pick_provider(session, model="gpt-4o", header_provider=None)
        assert exc.value.status_code == 503
