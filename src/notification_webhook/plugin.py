from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

import httpx

from app.core import Config as AppConfig
from app.utils import ImageUtils

if TYPE_CHECKING:
    from mas.plugins import PluginContext

from .schema import Config, WebhookItem


class WebhookChannel:
    def __init__(self, ctx: "PluginContext", config: Config) -> None:
        self.ctx = ctx
        self.config = config

    async def send(self, payload: dict[str, Any]) -> bool:
        kind = str(payload.get("kind") or "")
        if kind == "legacy_webhook":
            return await self._send_legacy(payload)
        if kind == "webhook_image":
            return await self._send_image(payload)

        webhook = payload.get("webhook")
        if webhook is not None:
            return await self._send_model_webhook(payload, webhook)

        if not self.config.enabled:
            return False

        results = []
        for item in self.config.webhooks:
            if not item.enabled:
                continue
            results.append(await self._send_item(payload, item))
        if not results:
            self.ctx.logger.warning("[notification_webhook] 没有启用的 Webhook")
            return False
        return all(results)

    async def _send_model_webhook(self, payload: dict[str, Any], webhook: Any) -> bool:
        if not webhook.get("Info", "Enabled"):
            return False
        item = WebhookItem(
            name=webhook.get("Info", "Name") or "Webhook",
            enabled=True,
            url=webhook.get("Data", "Url") or "",
            method=webhook.get("Data", "Method") or "POST",
            headers=webhook.get("Data", "Headers") or "{}",
            template=webhook.get("Data", "Template") or '{"title": "{title}", "content": "{content}"}',
        )
        return await self._send_item(payload, item)

    async def _send_item(self, payload: dict[str, Any], item: WebhookItem) -> bool:
        if not item.url:
            raise ValueError("Webhook URL 不能为空")

        data = self._render_template(
            item.template,
            title=str(payload.get("title") or ""),
            content=str(payload.get("text") or ""),
        )
        headers = {"Content-Type": "application/json"}
        headers.update(json.loads(item.headers or "{}"))

        async with httpx.AsyncClient(proxy=AppConfig.proxy, timeout=10) as client:
            if item.method == "POST":
                if isinstance(data, dict):
                    response = await client.post(item.url, json=data, headers=headers)
                else:
                    response = await client.post(item.url, content=str(data), headers=headers)
            else:
                params = self._flatten_params(data)
                response = await client.get(item.url, params=params, headers=headers)

        if response.status_code == 200:
            self.ctx.logger.info(f"[notification_webhook] Webhook 推送成功: {item.name}")
            return True
        raise RuntimeError(f"HTTP {response.status_code}: {response.text}")

    async def _send_legacy(self, payload: dict[str, Any]) -> bool:
        webhook_url = str(payload.get("webhook_url") or "").strip()
        if not webhook_url:
            raise ValueError("Webhook 地址不能为空")

        content = f"{payload.get('title')}\n{payload.get('text')}"
        data = {"msgtype": "text", "text": {"content": content}}
        async with httpx.AsyncClient(proxy=AppConfig.proxy) as client:
            response = await client.post(url=webhook_url, json=data)
            info = response.json()
        if info.get("errcode") == 0:
            self.ctx.logger.info(f"[notification_webhook] 旧版 Webhook 推送成功: {payload.get('title')}")
            return True
        raise RuntimeError(f"Webhook 推送失败: {response.text}")

    async def _send_image(self, payload: dict[str, Any]) -> bool:
        image_path = Path(payload.get("image_path"))
        webhook_url = str(payload.get("webhook_url") or "").strip()
        if not webhook_url:
            raise ValueError("Webhook URL 不能为空")

        ImageUtils.compress_image_if_needed(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"文件未找到: {image_path}")

        image_base64 = ImageUtils.get_base64_from_file(str(image_path))
        image_md5 = ImageUtils.calculate_md5_from_file(str(image_path))
        data = {"msgtype": "image", "image": {"base64": image_base64, "md5": image_md5}}
        async with httpx.AsyncClient(proxy=AppConfig.proxy) as client:
            response = await client.post(url=webhook_url, json=data)
            info = response.json()
        if info.get("errcode") == 0:
            self.ctx.logger.info(f"[notification_webhook] 图片 Webhook 推送成功: {image_path.name}")
            return True
        raise RuntimeError(f"图片 Webhook 推送失败: {response.text}")

    def _render_template(self, template: str, *, title: str, content: str) -> Any:
        vars_map = {
            "title": title,
            "content": content,
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M:%S"),
        }
        try:
            parsed = json.loads(template)
            return self._replace_variables(parsed, vars_map)
        except json.JSONDecodeError:
            rendered = template
            for key, value in vars_map.items():
                rendered = rendered.replace(f"{{{key}}}", str(value).replace('"', '\\"'))
            try:
                return json.loads(rendered)
            except json.JSONDecodeError:
                return rendered

    def _replace_variables(self, value: Any, vars_map: dict[str, str]) -> Any:
        if isinstance(value, dict):
            return {k: self._replace_variables(v, vars_map) for k, v in value.items()}
        if isinstance(value, list):
            return [self._replace_variables(item, vars_map) for item in value]
        if isinstance(value, str):
            result = value
            for key, replacement in vars_map.items():
                result = result.replace(f"{{{key}}}", replacement)
            return result
        return value

    @staticmethod
    def _flatten_params(data: Any) -> dict[str, str]:
        if isinstance(data, dict):
            return {
                str(k): json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
                for k, v in data.items()
            }
        return {"message": str(data)}


class Plugin:
    needs = "notify"

    def __init__(self, ctx: "PluginContext") -> None:
        self.ctx = ctx

    async def on_start(self) -> None:
        raw_config = self.ctx.config.to_dict() if hasattr(self.ctx.config, "to_dict") else dict(self.ctx.config)
        channel = WebhookChannel(self.ctx, Config.model_validate(raw_config))
        self.ctx.get("notify").register_channel("webhook", channel)
        self.ctx.logger.info("[notification_webhook] 通道已启动")

    async def on_stop(self, reason: str) -> None:
        notify = self.ctx.get("notify")
        if notify is not None:
            notify.unregister_channel("webhook")
        self.ctx.logger.info(f"[notification_webhook] 插件停止, reason={reason}")
