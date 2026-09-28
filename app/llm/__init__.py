"""模型基建（自 token-burner 复制的自有代码，import 已适配为独立包）。

- model_client: litellm 统一网关 + 超时换腿/瞬态退避/json_mode 降级/截断续写
- budget:      单任务 token 总闸 + 活动护栏槽
- rate_limiter: 按供应商令牌桶全局限流
- connections: 按模型名/前缀解析 api_key/base_url（config.json）
- yaml_robust: 缩进自愈 YAML 加载
"""
