from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    database_url: str = Field(alias="DATABASE_URL")
    liquipedia_api_key: str = Field(alias="LIQUIPEDIA_API_KEY")
    liquipedia_user_agent: str = Field(alias="LIQUIPEDIA_USER_AGENT")

    liquipedia_base_url: str = Field(
        default="https://api.liquipedia.net/api/v3",
        alias="LIQUIPEDIA_BASE_URL",
    )
    liquipedia_wiki: str = Field(default="trackmania", alias="LIQUIPEDIA_WIKI")
    liquipedia_timeout_seconds: float = Field(default=30.0, alias="LIQUIPEDIA_TIMEOUT_SECONDS")
    liquipedia_page_size: int = Field(default=50, alias="LIQUIPEDIA_PAGE_SIZE")
    liquipedia_max_retries: int = Field(default=3, alias="LIQUIPEDIA_MAX_RETRIES")
    liquipedia_tournament_table: str = Field(default="tournament", alias="LIQUIPEDIA_TOURNAMENT_TABLE")
    liquipedia_tournament_conditions: str = Field(
        default="[[liquipediatier::1]] OR [[liquipediatier::2]]",
        alias="LIQUIPEDIA_TOURNAMENT_CONDITIONS",
    )
    liquipedia_tournament_query_fields: str = Field(
        default=(
            "pageid,pagename,name,shortname,seriespage,mode,type,startdate,enddate,"
            "sortdate,prizepool,participantsnumber,liquipediatier"
        ),
        alias="LIQUIPEDIA_TOURNAMENT_QUERY_FIELDS",
    )
    liquipedia_results_table: str = Field(default="placement", alias="LIQUIPEDIA_RESULTS_TABLE")
    liquipedia_results_conditions_template: str = Field(
        default="[[parent::{source_event_id}]]",
        alias="LIQUIPEDIA_RESULTS_CONDITIONS_TEMPLATE",
    )
    liquipedia_results_query_fields: str = Field(
        default=(
            "pageid,pagename,objectname,tournament,series,parent,date,placement,prizemoney,"
            "weight,mode,type,liquipediatier,opponentname,opponenttemplate,opponenttype,"
            "opponentplayers,qualifier,qualifierpage,qualifierurl,extradata"
        ),
        alias="LIQUIPEDIA_RESULTS_QUERY_FIELDS",
    )
    liquipedia_request_sleep_seconds: float = Field(
        default=61.0,
        alias="LIQUIPEDIA_REQUEST_SLEEP_SECONDS",
    )
    liquipedia_results_discovery_mode: bool = Field(
        default=False,
        alias="LIQUIPEDIA_RESULTS_DISCOVERY_MODE",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
