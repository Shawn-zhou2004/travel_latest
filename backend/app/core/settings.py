from pathlib import Path
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parents[3] / ".env",
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    # Fixed backoffice account seeded on startup; the env values are the
    # single source of truth and are re-synced on every boot.
    admin_username: str = "admin"
    admin_password: str = "admin123456"
    mysql_dsn: str | None = None
    redis_url: str | None = None
    rabbitmq_url: str | None = None
    elasticsearch_url: str | None = None
    jwt_secret: str | None = None
    amap_js_api_key: str | None = None
    amap_security_js_code: str | None = None
    amap_web_service_key: str | None = None
    dashscope_api_key: str | None = None
    ai_enabled: bool = False
    ai_postgres_dsn: str | None = None
    milvus_uri: str | None = None
    milvus_token: str | None = None
    # The legacy shared collection remains configured during the staged cutover.
    milvus_collection_travel_knowledge: str = "travel_knowledge_v1"
    milvus_collection_official_knowledge: str = "travel_official_knowledge_v1"
    milvus_collection_community_knowledge: str = "travel_community_knowledge_v1"
    milvus_collection_user_memory: str = "user_memory_v1"
    elasticsearch_index_travel_knowledge: str = "travel_knowledge_v1"
    elasticsearch_index_official_knowledge: str = "travel_official_knowledge_v1"
    elasticsearch_index_community_knowledge: str = "travel_community_knowledge_v1"
    elasticsearch_index_user_memory: str = "user_memory_v1"
    embedding_provider: str | None = None
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int = 1024
    embedding_timeout_seconds: int = 15
    rag_top_k_dense: int = 20
    rag_top_k_bm25: int = 20
    rag_top_k_final: int = 8
    rag_cache_ttl_seconds: int = 300
    rag_min_score: float = 0.35
    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 2
    # "agent" runs the planning node as a tool-calling agent loop (default);
    # "single" pins the legacy single-shot LLM call for degraded environments.
    planning_agent_mode: str = "agent"
    neo4j_enabled: bool = False
    deepagents_enabled: bool = False
    cosyvoice_model: str | None = None
    aliyun_oss_endpoint: str | None = None
    aliyun_oss_bucket: str | None = None
    aliyun_oss_access_key_id: str | None = None
    aliyun_oss_access_key_secret: str | None = None
    object_storage_provider: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket_private: str | None = None
    s3_bucket_exports: str | None = None
    s3_bucket_audio: str | None = None
    s3_use_path_style: bool = False
    aliyun_sms_access_key_id: str | None = None
    aliyun_sms_access_key_secret: str | None = None
    aliyun_sms_sign_name: str | None = None
    aliyun_sms_template_code: str | None = None
    aliyun_sms_template_param: str | None = None
    alipay_app_id: str | None = None
    alipay_app_private_key: str | None = None
    alipay_public_key: str | None = None
    alipay_gateway_url: str | None = None
    alipay_notify_base_url: str | None = None
    alipay_return_base_url: str | None = None
    wechat_app_id: str | None = None
    wechat_app_secret: str | None = None
    supplier_integration_enabled: bool = False
    magic_mcp_websearch_url: str | None = None
    magic_mcp_websearch_tool: str | None = None
    magic_mcp_fetch_url: str | None = None
    magic_mcp_fetch_tool: str | None = None
    magic_mcp_fetch_api_key: str | None = None
    magic_mcp_fetch_timeout_seconds: int = 60
    magic_mcp_train_url: str | None = None
    magic_mcp_train_tool: str | None = None
    magic_mcp_flight_url: str | None = None
    magic_mcp_flight_tool: str | None = None
    magic_mcp_api_key: str | None = None
    magic_mcp_timeout_seconds: int = 15
    cors_origins: str = "http://localhost:5173,http://localhost:5174"

    @model_validator(mode="after")
    def require_platform_configuration_outside_test(self) -> "Settings":
        if self.app_env != "test":
            missing = [
                name
                for name in (
                    "mysql_dsn",
                    "redis_url",
                    "rabbitmq_url",
                    "elasticsearch_url",
                    "jwt_secret",
                )
                if not getattr(self, name)
            ]
            if missing:
                raise ValueError(f"Missing required configuration: {', '.join(missing)}")
        return self

    @model_validator(mode="after")
    def require_ai_configuration_when_enabled(self) -> "Settings":
        if not self.ai_enabled:
            return self
        missing = [
            name
            for name in (
                "ai_postgres_dsn",
                "milvus_uri",
                "milvus_token",
                "embedding_provider",
                "embedding_base_url",
                "embedding_model",
                "llm_provider",
                "llm_base_url",
                "llm_model",
                "dashscope_api_key",
            )
            if not getattr(self, name)
        ]
        if missing:
            raise ValueError(f"Missing AI configuration: {', '.join(missing)}")
        if (self.rag_top_k_dense, self.rag_top_k_bm25, self.rag_top_k_final) != (20, 20, 8):
            raise ValueError("Phase-one RAG requires dense=20, bm25=20, and final=8")
        if self.embedding_dimensions < 1:
            raise ValueError("embedding_dimensions must be positive")
        if not 0 <= self.rag_min_score <= 1:
            raise ValueError("rag_min_score must be between zero and one")
        if self.neo4j_enabled:
            raise ValueError("Neo4j is not part of the phase-one AI architecture")
        if self.deepagents_enabled:
            raise ValueError("DeepAgents is not part of the phase-one AI architecture")
        return self

    @model_validator(mode="after")
    def validate_magic_mcp_configuration(self) -> "Settings":
        for name in (
            "magic_mcp_websearch_url",
            "magic_mcp_fetch_url",
            "magic_mcp_train_url",
            "magic_mcp_flight_url",
        ):
            url = getattr(self, name)
            if url:
                parsed_url = urlparse(url)
                if parsed_url.scheme != "https" or not parsed_url.hostname:
                    raise ValueError(f"{name} must be an HTTPS URL with a hostname")
        if self.magic_mcp_timeout_seconds <= 0:
            raise ValueError("magic_mcp_timeout_seconds must be positive")
        if self.magic_mcp_fetch_timeout_seconds <= 0:
            raise ValueError("magic_mcp_fetch_timeout_seconds must be positive")
        return self
