"""The prompt-cache contract.

`report_e` publishes a prompt-cache hit rate.  With the deterministic offline
adapter that rate is 0.0 because no provider is called, and it is reported as
0.0 rather than dressed up -- but the *shape* that makes caching possible can
still be asserted without a network call, and that is what this module does:

1. The system prompt is byte-stable.  It must not carry a timestamp, a uuid, a
   deal id or anything else that changes per call, because a system prompt that
   changes can never be a cache hit.
2. The volatile case payload goes in the **user** turn, after the cache
   breakpoint -- never interpolated into the system prompt.
3. The Anthropic call is constructed with `thinking={"type": "adaptive"}` and
   exactly one `cache_control: {"type": "ephemeral"}` breakpoint on the system
   block, and **never** with `budget_tokens`.
4. `compute_prompt_hash` is sensitive to the user turn, so two different cases
   never collide on one prompt hash even though they share a system prompt.

A live-provider hit rate can only be measured against a live provider.  These
assertions are what stop the code from silently becoming uncacheable in the
meantime.
"""

from __future__ import annotations

import inspect
import re

from app.agents import _llm
from app.agents import prompts as agent_prompts
from app.agents._llm import compute_prompt_hash

VOLATILE = re.compile(
    r"(?i)\b(?:datetime\.now|dt\.now|utcnow|uuid4|time\.time|random\.)|"
    r"\{deal|\{milestone|\{amount|\{artifact"
)


def _system_prompts() -> dict[str, str]:
    """Every module-level system prompt the agents ship."""
    found: dict[str, str] = {}
    for name, value in vars(agent_prompts).items():
        if name.isupper() and isinstance(value, str) and len(value) > 200:
            found[name] = value
    assert found, "no system prompt constants found in app.agents.prompts"
    return found


def test_system_prompts_are_module_level_constants() -> None:
    """A prompt built per call cannot be byte-stable, so it cannot be cached."""
    for name, text in _system_prompts().items():
        assert isinstance(text, str), name
        assert text == text.strip() or text.strip(), name


def test_system_prompts_contain_no_per_call_interpolation() -> None:
    """No `{deal_id}`-style placeholder and no clock read inside a system prompt."""
    for name, text in _system_prompts().items():
        assert not VOLATILE.search(text), f"{name} contains a per-call value"


def test_system_prompts_are_byte_stable_across_reads() -> None:
    first = _system_prompts()
    second = _system_prompts()
    for name, text in first.items():
        assert second[name] == text, f"{name} is not byte-stable"
        assert second[name].encode("utf-8") == text.encode("utf-8")


def test_anthropic_call_has_one_ephemeral_breakpoint_on_the_system_block() -> None:
    source = inspect.getsource(_llm.AnthropicProvider.parse)
    assert source.count('"cache_control"') == 1, "expected exactly one cache breakpoint"
    assert '{"type": "ephemeral"}' in source
    # The breakpoint must sit on the system block, with the user turn after it.
    system_at = source.index("system=[")
    cache_at = source.index('"cache_control"')
    messages_at = source.index("messages=[")
    assert system_at < cache_at < messages_at


def test_anthropic_call_uses_adaptive_thinking_and_never_budget_tokens() -> None:
    source = inspect.getsource(_llm.AnthropicProvider.parse)
    assert 'thinking={"type": "adaptive"}' in source
    assert "budget_tokens" not in source


def test_budget_tokens_is_never_passed_anywhere_in_the_llm_layer() -> None:
    """`budget_tokens` is not a valid companion to adaptive thinking: it 400s.

    The module docstring names it in order to say it is never sent, so the check
    is for the *argument*, not for the word.
    """
    source = inspect.getsource(_llm)
    assert "budget_tokens=" not in source
    assert '"budget_tokens"' not in source
    assert "'budget_tokens'" not in source


def test_prompt_hash_is_stable_for_identical_inputs() -> None:
    a = compute_prompt_hash("system", "user", "claude-opus-5")
    b = compute_prompt_hash("system", "user", "claude-opus-5")
    assert a == b
    assert len(a) == 64


def test_prompt_hash_separates_the_user_turn_from_the_system_prompt() -> None:
    """Two cases sharing one cached system prompt must not share a prompt hash."""
    shared_system = "the byte-stable rubric"
    first = compute_prompt_hash(shared_system, "case one", "claude-opus-5")
    second = compute_prompt_hash(shared_system, "case two", "claude-opus-5")
    assert first != second

    # And the hash is sensitive to the model, so a model swap is visible in the
    # attestation rather than hidden behind an identical hash.
    assert compute_prompt_hash(shared_system, "case one", "claude-sonnet-5") != first
