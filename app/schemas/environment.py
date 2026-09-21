"""环境配置相关的请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class EnvironmentBase(BaseModel):
    """环境配置的公共字段。

    Attributes:
        name: 环境名称。
        base_url: 接口基地址。
        headers: 公共请求头。
        variables: 全局变量。
        verify: 是否校验 HTTPS 证书。
        timeout: 超时秒数。
        is_default: 是否为项目默认环境。
        description: 备注。
    """

    name: str = Field(min_length=1, max_length=64, description="环境名称，如 dev / staging")
    base_url: str = Field(default="", max_length=512, description="接口基地址")
    headers: dict[str, Any] = Field(default_factory=dict, description="公共请求头")
    variables: dict[str, Any] = Field(default_factory=dict, description="全局变量")
    verify: bool = Field(default=True, description="是否校验 HTTPS 证书")
    timeout: int = Field(default=15, ge=1, le=600, description="超时秒数")
    is_default: bool = Field(default=False, description="是否项目默认环境")
    description: str | None = Field(default=None, max_length=1000)


class EnvironmentCreateRequest(EnvironmentBase):
    """创建环境请求。"""


class EnvironmentUpdateRequest(BaseModel):
    """更新环境请求（字段可选）。

    Attributes:
        name: 环境名称。
        base_url: 接口基地址。
        headers: 公共请求头。
        variables: 全局变量。
        verify: 是否校验 HTTPS 证书。
        timeout: 超时秒数。
        is_default: 是否为项目默认环境。
        description: 备注。
    """

    name: str | None = Field(default=None, min_length=1, max_length=64)
    base_url: str | None = Field(default=None, max_length=512)
    headers: dict[str, Any] | None = None
    variables: dict[str, Any] | None = None
    verify: bool | None = None
    timeout: int | None = Field(default=None, ge=1, le=600)
    is_default: bool | None = None
    description: str | None = Field(default=None, max_length=1000)


class EnvironmentOut(ORMModel):
    """环境响应。

    Attributes:
        id: 环境 ID。
        project_id: 所属项目。
        name: 环境名称。
        base_url: 接口基地址。
        headers: 公共请求头。
        variables: 全局变量。
        verify: 是否校验 HTTPS 证书。
        timeout: 超时秒数。
        is_default: 是否默认环境。
        description: 备注。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    id: int
    project_id: int
    name: str
    base_url: str = ""
    headers: dict[str, Any] = Field(default_factory=dict)
    variables: dict[str, Any] = Field(default_factory=dict)
    verify: bool = True
    timeout: int = 15
    is_default: bool = False
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
