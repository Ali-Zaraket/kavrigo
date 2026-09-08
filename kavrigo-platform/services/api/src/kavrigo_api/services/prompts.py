"""Default runtime prompt artifact for newly created immutable agent versions (ADR 0024)."""

from kavrigo_domain.prompts import DEFAULT_PROMPT_TEMPLATE, DEFAULT_PROMPT_VERSION
from kavrigo_model_gateway import prompt_text_hash

__all__ = ["DEFAULT_PROMPT_TEMPLATE", "DEFAULT_PROMPT_VERSION", "default_prompt_hash"]


def default_prompt_hash() -> str:
    return prompt_text_hash(DEFAULT_PROMPT_TEMPLATE)
