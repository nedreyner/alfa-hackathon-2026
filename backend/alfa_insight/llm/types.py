"""Типы LLM-слоя (docs/04-llm.md §4) и модели `config/models.yaml` (§2.1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Priority = Literal["interactive", "precompute", "background"]
TaskName = Literal[
    "tagging",
    "tagging_interactive",
    "research_extract",
    "vision",
    "ocr",
    "rerank",
    "agent",
    "draft",
    "revise",
    "verify",
    "chat",
]
Strategy = Literal["auto", "tool_call", "json_schema", "json_object", "prompt_only"]
BaseUrlKind = Literal["primary", "fallback"]
STRATEGY_ORDER: tuple[Strategy, ...] = ("tool_call", "json_schema", "json_object", "prompt_only")


# ── сообщения ──
class ImagePart(BaseModel):
    type: Literal["image_url"] = "image_url"
    image_url: dict[str, str]


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]  # при невалидном JSON: {"__raw__": "<строка>"}


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[TextPart | ImagePart] | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            return "\n".join(p.text for p in self.content if isinstance(p, TextPart))
        return ""


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class Usage(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    cost_rub: float = 0.0


class LLMRequest(BaseModel):
    task: TaskName
    messages: list[Message]
    prompt_version: str
    tools: list[ToolSpec] | None = None
    tool_choice: Literal["auto", "required", "none"] | dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    priority: Priority | None = None
    run_id: str | None = None
    cache: bool = True
    exclude_families: list[str] = Field(default_factory=list)
    only_model: str | None = None  # внутреннее: вызов конкретной модели цепочки (structured)
    schema_hint: dict[str, Any] | None = None  # внутреннее: схема для FakeBackend, в ключ кеша не входит


class LLMResult(BaseModel):
    model_key: str
    model_id: str
    family: str
    content: str | None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage = Field(default_factory=Usage)
    cached: bool = False
    latency_ms: int = 0
    base_url_kind: BaseUrlKind | None = None
    fallback_model_used: bool = False
    cache_key: str | None = None  # запись кеша с этим ответом (удаляется, если ответ не прошёл схему)


class StructuredResult[T: BaseModel](BaseModel):
    value: T
    raw: LLMResult
    strategy_used: Strategy
    repaired: bool


class LLMCallRecord(BaseModel):
    ts: str
    budget_day: str
    task: str
    model: str
    priority: Priority
    run_id: str | None
    cached: bool
    status: Literal["ok", "error", "budget_blocked", "invalid_output"]
    tokens_in: int = 0
    tokens_out: int = 0
    cost_rub: float = 0.0
    latency_ms: int | None = None
    base_url_kind: BaseUrlKind | None = None
    error: str | None = None
    fallback_model_used: bool = False
    cache_key: str | None = None


# ── config/models.yaml ──
class Price(BaseModel):
    input: float | None = None
    output: float | None = None


class ModelCapabilities(BaseModel):
    tools: bool | None = None
    json_schema: bool | None = None
    json_object: bool | None = None
    vision: bool | None = None
    usage: bool | None = None
    reasoning_toggle: bool | None = None  # шлюз принимает reasoning: {enabled: false}


class ModelConfig(BaseModel):
    key: str = ""
    id: str
    family: str
    context_tokens: int = 128_000
    price_rub_per_1m: Price = Field(default_factory=Price)
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    token_param: Literal["max_tokens", "max_completion_tokens"] | None = None


class TaskConfig(BaseModel):
    chain: list[str]
    temperature: float = 0.0
    max_tokens: int = 1000
    priority: Priority = "background"
    strategy: Strategy = "auto"
    timeout_s: float = 30.0
    exclude_drafter_family: bool = False
    cache: bool = True
    # None — поведение модели по умолчанию; False — отключить рассуждения (дешевле и быстрее в разы)
    reasoning: bool | None = None
    # Хедж (только structured): если первая модель цепочки молчит дольше, параллельно спрашиваем вторую
    hedge_after_s: float | None = None


class GatewayConfig(BaseModel):
    timeout_s: float = 60.0
    connect_timeout_s: float = 10.0
    max_concurrency_interactive: int = 4
    max_concurrency_background: int = 2
    retries: int = 2
    retry_delays_s: list[float] = Field(default_factory=lambda: [1.0, 3.0])
    token_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"


class ModelsConfig(BaseModel):
    version: int = 1
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    default_price_rub_per_1m: Price = Field(default_factory=lambda: Price(input=50, output=200))
    models: dict[str, ModelConfig]
    tasks: dict[str, TaskConfig]

    def model_post_init(self, __context: Any) -> None:
        for key, model in self.models.items():
            model.key = key
        for name, task in self.tasks.items():
            missing = [m for m in task.chain if m not in self.models]
            if missing:
                raise ValueError(f"tasks.{name}.chain: неизвестные модели {missing}")
            if not task.chain:
                raise ValueError(f"tasks.{name}.chain пуст")

    def price(self, model: ModelConfig) -> tuple[float, float]:
        p_in = model.price_rub_per_1m.input
        p_out = model.price_rub_per_1m.output
        d = self.default_price_rub_per_1m
        return (
            p_in if p_in is not None else float(d.input or 0.0),
            p_out if p_out is not None else float(d.output or 0.0),
        )
