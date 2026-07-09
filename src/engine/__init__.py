"""Engine — turn controller, response parser, message builder, and context manager."""

from src.engine.response_parser import (
    extract_code_blocks,
    extract_intent_clarify_options,
    extract_roleplay_state_block,
    is_system_generated_user_message,
    is_valid_python_code,
    output_has_error,
    parse_think_steps,
    redact_prompt_content,
    sanitize_assistant_response,
    strip_code_fences,
    strip_think_block,
    truncate_tool_output,
    summarize_tool_failure,
)
from src.engine.message_builder import (
    build_llm_messages,
    build_reinforcement_messages,
    format_tool_output_message,
)
from src.engine.turn_controller import (
    TurnAction,
    TurnController,
    TurnResult,
)
from src.engine.context_manager import (
    auto_compact_messages,
    estimate_tokens,
    estimate_messages_tokens,
    limits_for_model,
    CompactResult,
    ContextLimits,
)
from src.engine.prompt_blocks import (
    PromptBlock,
    assemble_as_string,
    assemble_for_anthropic,
    summarize_blocks,
)
