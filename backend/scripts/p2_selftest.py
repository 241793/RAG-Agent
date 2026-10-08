"""P2 自测：技能系统 + 行为模式。

验证：
1. 创建 prompt_pack 技能（带提示词模板）
2. 给 Agent 挂技能 → 运行后 system prompt 含技能内容（通过 model 回显观察难度大，改为直接校验 build_effective）
3. 创建两个行为模式 → 切换 mode 运行，验证模式提示词叠加
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from app.core.db import AsyncSessionLocal, init_models
from app.models import Agent, AgentMode, Skill, Conversation
from app.agents.runner import build_effective
from app.services.permission import PrincipalSet


async def main() -> None:
    await init_models()
    async with AsyncSessionLocal() as db:
        # 1. 建一个 prompt_pack 技能
        sk = Skill(
            tenant_id=1, owner_id=1, name="合规审查", slug="compliance",
            kind="prompt_pack",
            prompt_template="回答时必须严格遵守合规要求，不得提供违法建议。{extra}",
            params_schema={"type": "object", "properties": {"extra": {"type": "string"}}},
        )
        db.add(sk)
        await db.flush()
        print(f"[1] 技能 id={sk.id} kind={sk.kind}")

        # 2. 建 Agent 挂该技能
        a = Agent(
            tenant_id=1, owner_id=1, name="p2_agent", slug="p2-agent",
            system_prompt="你是企业助手。", skill_ids=[sk.id],
            config={"extra": "（来自 params 的注入）"},
        )
        db.add(a)
        await db.flush()

        # 3. 建两个行为模式
        m1 = AgentMode(tenant_id=1, agent_id=a.id, name="写作模式", system_prompt="现在进入写作模式：文风要正式。")
        m2 = AgentMode(tenant_id=1, agent_id=a.id, name="审核模式", system_prompt="现在进入审核模式：严格挑错。")
        db.add_all([m1, m2])
        await db.flush()
        await db.commit()

        # 4. 验证 build_effective
        eff0 = await build_effective(db, a, None)
        print(f"[2] 无模式 system_prompt 含技能注入: {'合规审查' in eff0.system_prompt}")
        print(f"    含 params 渲染: {'来自 params 的注入' in eff0.system_prompt}")

        eff1 = await build_effective(db, a, m1)
        print(f"[3] 写作模式 system 含写作提示: {'写作模式' in eff1.system_prompt}")
        print(f"    仍含技能注入: {'合规审查' in eff1.system_prompt}")

        eff2 = await build_effective(db, a, m2)
        print(f"[4] 审核模式 system 含审核提示: {'审核模式' in eff2.system_prompt}")
        print(f"    与写作模式不同: {eff1.system_prompt != eff2.system_prompt}")

        assert "合规审查" in eff0.system_prompt
        assert "来自 params 的注入" in eff0.system_prompt
        assert "写作模式" in eff1.system_prompt
        assert "审核模式" in eff2.system_prompt
        assert eff1.system_prompt != eff2.system_prompt
        print("\n✅ P2 技能注入 + 模式切换 通过")

        # 清理
        await db.delete(m1); await db.delete(m2); await db.delete(a); await db.delete(sk)
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
