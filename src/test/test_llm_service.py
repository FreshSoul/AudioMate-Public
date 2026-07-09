from src.llm.service import _convert_messages_for_anthropic, _friendly_llm_error


def test_anthropic_conversion_translates_openai_image_url_blocks():
    messages = [
        {"role": "system", "content": "system rules"},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc123"}},
                {"type": "text", "text": "请描述图片"},
            ],
        },
    ]

    system_prompt, converted_messages = _convert_messages_for_anthropic(messages)

    assert system_prompt == "system rules"
    assert converted_messages == [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": "abc123",
                    },
                },
                {"type": "text", "text": "请描述图片"},
            ],
        }
    ]


def test_anthropic_conversion_merges_consecutive_user_multimodal_messages():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "第一句"}]},
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,xyz"}}]},
    ]

    _system_prompt, converted_messages = _convert_messages_for_anthropic(messages)

    assert len(converted_messages) == 1
    assert converted_messages[0]["role"] == "user"
    assert converted_messages[0]["content"] == [
        {"type": "text", "text": "第一句"},
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "xyz"},
        },
    ]


def test_friendly_llm_error_explains_rate_limit_for_images():
    error_text = _friendly_llm_error(Exception("Error code: 429 - Limit Exceed"))

    assert "429" in error_text
    assert "图片请求" in error_text
    assert "切换" in error_text