"""The personal-assistant policy offers only what the owner's floor allows."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from eneo.governance_policy.application.effective_config_service import (
    EffectiveConfigService,
)
from eneo.governance_policy.domain.governance_policy import (
    GovernancePolicy,
    PolicyCapability,
    PolicyCompletionModel,
    PolicyMcpServer,
    PolicyScope,
)
from eneo.governance_policy.domain.policy_resolver import (
    select_effective_completion_model,
)
from eneo.mcp_servers.domain.entities.mcp_server import capability_permission
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.skills.domain.skill import SkillRuntimeResolution

TENANT_ID = uuid4()


def _classification(level: int, enabled: bool = True) -> SecurityClassification:
    return SecurityClassification(
        id=uuid4(),
        name=f"level {level}",
        tenant_id=TENANT_ID,
        security_level=level,
        security_enabled=enabled,
    )


LOW = _classification(1)
HIGH = _classification(2)


def _model(classification: SecurityClassification | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), provider_id=None, security_classification=classification
    )


def _server(
    classification: SecurityClassification | None, purpose: str = "general"
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        purpose=purpose,
        is_enabled=True,
        tools=[],
        readiness_reason=None,
        audience="everyone",
        effective_security_classification=classification,
        serves_user_groups=lambda group_ids: False,
        is_default_provider=lambda: purpose != "general",
    )


def _policy() -> GovernancePolicy:
    return GovernancePolicy(
        id=uuid4(), tenant_id=TENANT_ID, scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
    )


def _service(policy: GovernancePolicy, *, models=(), servers=()):
    return EffectiveConfigService(
        user=SimpleNamespace(
            tenant_id=TENANT_ID, user_groups_ids=set(), permissions=set()
        ),
        policy_repo=AsyncMock(get_by_tenant=AsyncMock(return_value=policy)),
        prompt_library_repo=AsyncMock(),
        completion_model_crud_service=AsyncMock(
            get_available_completion_models=AsyncMock(return_value=list(models))
        ),
        mcp_server_settings_service=AsyncMock(
            get_available_mcp_servers=AsyncMock(return_value=list(servers))
        ),
        skill_service=AsyncMock(
            resolve_governance_bindings_for_runtime=AsyncMock(
                return_value=SkillRuntimeResolution(eligible=(), blocked=())
            )
        ),
    )


def _models_policy(*models: SimpleNamespace, default: SimpleNamespace | None = None):
    policy = _policy()
    policy.set_models_restriction(
        enabled=True,
        models=[
            PolicyCompletionModel(completion_model_id=m.id, is_default=m is default)
            for m in models
        ],
    )
    return policy


async def test_allowed_models_are_those_the_policy_and_the_floor_both_allow():
    low, high, unclassified, not_in_policy = (
        _model(LOW),
        _model(HIGH),
        _model(None),
        _model(HIGH),
    )
    policy = _models_policy(low, high, unclassified)
    service = _service(policy, models=[low, high, unclassified, not_in_policy])

    cfg = await service.resolve_personal_default(floor=HIGH)

    assert cfg.models_enforced is True
    assert cfg.available_models == [high]


async def test_the_policy_default_is_never_a_model_below_the_floor():
    low, high, higher = _model(LOW), _model(HIGH), _model(HIGH)
    policy = _models_policy(low, high, higher, default=low)
    service = _service(policy, models=[low, high, higher])

    cfg = await service.resolve_personal_default(floor=HIGH)

    assert cfg.policy_default_model is None
    assert select_effective_completion_model(low, cfg) is high


async def test_the_locked_model_is_never_a_model_below_the_floor():
    low, high = _model(LOW), _model(HIGH)

    only_low = await _service(
        _models_policy(low), models=[low, high]
    ).resolve_personal_default(floor=HIGH)
    one_left = await _service(
        _models_policy(low, high), models=[low, high]
    ).resolve_personal_default(floor=HIGH)

    assert only_low.locked_model is None
    assert one_left.locked_model is high


async def test_no_model_in_common_leaves_an_enforced_policy_with_nothing_to_select():
    low = _model(LOW)
    service = _service(_models_policy(low, default=low), models=[low])

    cfg = await service.resolve_personal_default(floor=HIGH)

    assert cfg.models_enforced is True
    assert cfg.available_models == []
    assert select_effective_completion_model(low, cfg) is None


async def test_granted_mcp_servers_below_the_floor_are_left_out():
    low, high, unclassified = _server(LOW), _server(HIGH), _server(None)
    policy = _policy()
    policy.set_mcp_restriction(
        enabled=True,
        servers=[
            PolicyMcpServer(mcp_server_id=low.id, is_default_enabled=False),
            PolicyMcpServer(mcp_server_id=high.id),
            PolicyMcpServer(mcp_server_id=unclassified.id),
        ],
    )
    service = _service(policy, servers=[low, high, unclassified])

    cfg = await service.resolve_personal_default(floor=HIGH)

    assert cfg.mcp_enforced is True
    assert cfg.available_mcp_servers == [high]
    assert cfg.default_disabled_mcp_server_ids == []


async def test_a_capability_provider_below_the_floor_is_reported_as_unavailable():
    """The ask path refuses the provider; the policy must not offer it."""
    provider = _server(LOW, purpose="web_search")
    policy = _policy()
    policy.set_mcp_restriction(
        enabled=True,
        servers=[],
        capabilities=[PolicyCapability(purpose="web_search")],
    )
    service = _service(policy, servers=[provider])
    service.user.permissions = {capability_permission("web_search")}

    cfg = await service.resolve_personal_default(floor=HIGH)

    assert cfg.enabled_capabilities == ["web_search"]
    assert [(c.available, c.reason) for c in cfg.available_capabilities] == [
        (False, "classification")
    ]


async def test_without_a_floor_the_policy_is_unchanged():
    low, high, unclassified = _model(LOW), _model(HIGH), _model(None)
    low_server, open_server = _server(LOW), _server(None)
    policy = _models_policy(low, high, unclassified, default=low)
    policy.set_mcp_restriction(
        enabled=True,
        servers=[
            PolicyMcpServer(mcp_server_id=low_server.id),
            PolicyMcpServer(mcp_server_id=open_server.id),
        ],
    )
    service = _service(
        policy, models=[low, high, unclassified], servers=[low_server, open_server]
    )

    cfg = await service.resolve_personal_default()

    assert cfg.available_models == [low, high, unclassified]
    assert cfg.policy_default_model is low
    assert cfg.available_mcp_servers == [low_server, open_server]


async def test_a_floor_does_nothing_while_classification_is_disabled():
    low = _model(LOW)
    service = _service(_models_policy(low, default=low), models=[low])

    cfg = await service.resolve_personal_default(floor=_classification(2, False))

    assert cfg.available_models == [low]
    assert cfg.policy_default_model is low


async def test_resolve_for_applies_the_floor_it_is_given():
    low, high = _model(LOW), _model(HIGH)
    service = _service(_models_policy(low, high), models=[low, high])

    cfg = await service.resolve_for(
        SimpleNamespace(is_default=True), space_is_personal=True, floor=HIGH
    )

    assert cfg.available_models == [high]
