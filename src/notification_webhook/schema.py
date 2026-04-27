from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WebhookItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(default="Webhook", description="名称")
    enabled: bool = Field(default=True, description="启用")
    url: str = Field(default="", description="URL")
    method: Literal["POST", "GET"] = Field(default="POST", description="请求方法")
    headers: str = Field(default="{}", description="Headers JSON")
    template: str = Field(
        default='{"title": "{title}", "content": "{content}"}',
        description="内容模板",
    )


class Config(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=True, description="启用自定义 Webhook")
    webhooks: list[WebhookItem] = Field(
        default_factory=list,
        description="Webhook 列表",
        json_schema_extra={"type": "table", "item_type": "object"},
    )
