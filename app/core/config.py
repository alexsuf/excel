from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    llm_api_base: str = "https://bothub.chat/api/v2/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4.1-nano"
    llm_timeout: int = 300
    app_mode: str = "auto"

    llm_max_tokens: int = 8192
    llm_max_output_tokens: int = 8192
    llm_context_tokens: int = 131072
    llm_chars_per_token: float = 2.0
    llm_vision_fallback: bool = False
    llm_vision_max_pages: int = 20
    llm_vision_zoom: float = 1.6

    ocr_enabled: bool = True
    ocr_langs: str = "rus+eng"
    ocr_zoom: float = 2.5
    
    flask_host: str = "0.0.0.0"
    flask_port: int = 8001
    flask_debug: bool = False
    
    upload_max_size: int = 50 * 1024 * 1024
    allowed_extensions: set = {'.xlsx', '.xls', '.pdf', '.docx', '.txt', '.csv', '.json'}
    
    data_dir: str = "/app/data"
    templates_dir: str = "/app/data/templates"
    dictionaries_dir: str = "/app/data/dictionaries"
    input_dir: str = "/app/data/input"
    output_dir: str = "/app/data/output"
    log_dir: str = "/app/data/output"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()