from typing import Literal

from mas.plugin_config import PluginField
from pydantic import BaseModel, ConfigDict


class WebhookItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = PluginField(default="Webhook", description="名称")
    enabled: bool = PluginField(default=True, description="启用")
    url: str = PluginField(default="", description="URL")
    method: Literal["POST", "GET"] = PluginField(default="POST", description="请求方法")
    headers: str = PluginField(default="{}", description="Headers JSON")
    template: str = PluginField(
        default='{"title": "{title}", "content": "{content}"}',
        description="内容模板",
    )


class Config(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = PluginField(default=True, description="启用自定义 Webhook")
    webhooks: list[WebhookItem] = PluginField(
        default_factory=list,
        description="Webhook 列表",
        ui_type="table",
        item_type="object",
    )
