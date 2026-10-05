"""Claude API 호출 래퍼. anthropic SDK 는 Extension 에 번들된 wheel 에서 지연 로드한다."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AgentError(RuntimeError):
    """사용자에게 그대로 보여 줄 수 있는 에이전트 오류."""


@dataclass
class AgentSettings:
    # repr 에 키가 찍히지 않게 한다
    api_key: str = field(default="", repr=False)
    model: str = DEFAULT_MODEL
    effort: str = "medium"
    timeout: float = 300.0


def _sdk():
    try:
        import anthropic
    except ImportError as exc:
        raise AgentError("anthropic SDK 를 불러오지 못했습니다. Extension 을 플랫폼별 빌드로 설치했는지 확인하세요.") from exc
    return anthropic


def make_client(settings: AgentSettings):
    anthropic = _sdk()
    # 키를 비워 두면 SDK 기본 해석(ANTHROPIC_API_KEY, ant 로그인 프로필)을 따른다
    kwargs = {"timeout": settings.timeout}
    if settings.api_key:
        kwargs["api_key"] = settings.api_key
    return anthropic.Anthropic(**kwargs)


def image_block(png_bytes: bytes) -> dict:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(png_bytes).decode()},
    }


def _call(client, params):
    """스트리밍 호출 후 (최종 메시지, request id). SDK 오류는 AgentError 로 바꾼다."""
    anthropic = _sdk()
    try:
        with client.beta.messages.stream(**params) as stream:
            message = stream.get_final_message()
            return message, getattr(stream, "request_id", "") or ""
    except ValueError as exc:
        raise AgentError(f"응답 해석 실패: {exc}") from exc
    except anthropic.AuthenticationError as exc:
        raise AgentError("API 키 인증에 실패했습니다. Preferences 의 API 키를 확인하세요.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise AgentError("API 키에 이 모델 사용 권한이 없습니다.") from exc
    except anthropic.NotFoundError as exc:
        raise AgentError(f"모델을 찾을 수 없습니다: {params['model']}") from exc
    except anthropic.RateLimitError as exc:
        raise AgentError("요청 한도를 초과했습니다. 잠시 후 다시 시도하세요.") from exc
    except anthropic.BadRequestError as exc:
        raise AgentError(f"잘못된 요청: {exc.message}") from exc
    except anthropic.APIStatusError as exc:
        raise AgentError(f"API 오류 ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise AgentError("네트워크 연결에 실패했습니다.") from exc


def _base_params(settings: AgentSettings, system: str, messages: list, max_tokens: int) -> dict:
    return dict(
        model=settings.model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        thinking={"type": "adaptive"},
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )


def request_json(client, settings: AgentSettings, system: str, content: list, schema: dict, max_tokens: int = 64000):
    """구조화 출력 요청을 보내고 (JSON 텍스트, 메시지)를 반환한다."""
    params = _base_params(settings, system, [{"role": "user", "content": content}], max_tokens)
    params["output_config"] = {"effort": settings.effort, "format": {"type": "json_schema", "schema": schema}}
    message, request_id = _call(client, params)
    message.airig_request_id = request_id
    if message.stop_reason == "refusal":
        raise AgentError("모델이 요청을 거절했습니다.")
    if message.stop_reason == "max_tokens":
        raise AgentError("응답이 길이 제한에 걸려 잘렸습니다.")
    text = next((b.text for b in message.content if b.type == "text"), None)
    if text is None:
        raise AgentError("응답에 텍스트가 없습니다.")
    return text, message
