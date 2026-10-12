"""Environment-only settings. Never log or serialize settings objects."""
import os
from pathlib import Path
from functools import lru_cache
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    db_host: str = '127.0.0.1'
    db_port: int = Field(default=3307, ge=1, le=65535)
    db_user: str = 'procureflow'
    db_password: SecretStr = Field(default=SecretStr(''), repr=False)
    db_name: str = Field(default='procureflow', pattern=r'^procureflow(?:_[a-z0-9_]+)?$')
    db_pool_size: int = Field(default=8, ge=1, le=32)
    procureflow_data_root: Path = ROOT / '.procureflow-data'
    qwen_model: str = 'qwen-plus-latest'
    qwen_base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    a2a_budget_port: int = 5005
    a2a_supplier_port: int = 5006
    a2a_compliance_port: int = 5007
    a2a_procurement_port: int = 5008
    mcp_budget_port: int = 8001
    mcp_supplier_port: int = 8002
    mcp_compliance_port: int = 8003
    mcp_procurement_port: int = 8004
    workflow_api_port: int = 8010
    workflow_max_retries: int = Field(default=2, ge=0, le=5)
    agent_host: str = '127.0.0.1'
    agent_timeout_seconds: float = Field(default=180, gt=0)
    mcp_timeout_seconds: float = Field(default=20, gt=0)
    llm_timeout_seconds: float = Field(default=60, gt=0)
    agent_max_retries: int = Field(default=1, ge=0, le=3)
    agent_max_candidate_pages: int = Field(default=20, ge=1, le=100)
    score_price_weight: float = 0.35
    score_delivery_weight: float = 0.25
    score_on_time_weight: float = 0.25
    score_quality_weight: float = 0.15

    def agent_url(self, role):
        return f'http://{self.agent_host}:{getattr(self, "a2a_"+role+"_port")}'

    def mcp_url(self, role):
        return f'http://{self.agent_host}:{getattr(self, "mcp_"+role+"_port")}/mcp'

    @field_validator('procureflow_data_root')
    @classmethod
    def resolve_data_storage(cls, value):
        # Relative values are anchored to the repository, so the public example
        # behaves consistently regardless of the caller's working directory.
        destination = value if value.is_absolute() else ROOT / value
        destination = destination.resolve()
        if destination.drive.upper() == 'P:':
            raise ValueError('Mapped P: storage is unsupported; configure a real local path')
        return destination

    @property
    def generated_dir(self):
        return self.procureflow_data_root / 'generated'

    @property
    def logs_dir(self):
        return self.procureflow_data_root / 'logs'

    def require_persistent_path(self, path):
        destination = Path(path).resolve()
        if not destination.is_relative_to(self.procureflow_data_root.resolve()):
            raise ValueError('Persistent output must remain inside PROCUREFLOW_DATA_ROOT')
        return destination

    @property
    def langgraph_dir(self):
        return self.procureflow_data_root / 'langgraph'

    @property
    def checkpoint_path(self):
        return self.langgraph_dir / 'checkpoints.sqlite'

    def connection_kwargs(self):
        return dict(host=self.db_host, port=self.db_port, user=self.db_user,
                    password=self.db_password.get_secret_value(), database=self.db_name,
                    charset='utf8mb4', connection_timeout=10)


@lru_cache
def get_settings():
    return Settings()


def get_dashscope_api_key():
    # Reserved for a future phase; Phase 1 never invokes this function.
    return os.getenv('DASHSCOPE_API_KEY')
