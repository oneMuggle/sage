"""reviewer 角色 + profile（P0-2）。"""

from backend.agents.profiles import create_default_agents


def test_create_default_agents_includes_reviewer():
    profiles = create_default_agents()
    ids = {p.id for p in profiles}
    assert "reviewer" in ids


def test_reviewer_profile_is_structured_for_assertions():
    reviewer = next(p for p in create_default_agents() if p.id == "reviewer")
    assert "FACT" in reviewer.system_prompt
    assert "HYPOTHESIS" in reviewer.system_prompt
    assert "NEGATIVE_EVIDENCE" in reviewer.system_prompt
    assert "confidence" in reviewer.system_prompt


def test_valid_agent_roles_include_reviewer():
    from backend.api.legacy_routes import _VALID_AGENT_ROLES

    assert "reviewer" in _VALID_AGENT_ROLES
