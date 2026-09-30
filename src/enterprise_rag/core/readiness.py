from pathlib import Path

from pydantic import BaseModel

from enterprise_rag.storage.sqlite import CORE_TABLES, SQLiteDatabase, coerce_sqlite_database


class ReadinessCheck(BaseModel):
    ready: bool
    components: dict[str, str]


class ReadinessService:
    def __init__(self, database_path: Path | SQLiteDatabase, provider_name: str) -> None:
        self.database = coerce_sqlite_database(database_path)
        self.provider_name = provider_name

    def check(self) -> ReadinessCheck:
        components = {"model_provider": f"configured:{self.provider_name}"}
        check = self.database.verify(CORE_TABLES)
        if check.integrity != "ok":
            components["database"] = check.integrity
            return ReadinessCheck(ready=False, components=components)
        if check.missing_tables:
            components["database"] = f"missing_tables:{','.join(check.missing_tables)}"
            return ReadinessCheck(ready=False, components=components)
        if check.schema_version != check.expected_schema_version:
            components["database"] = (
                f"schema_version:{check.schema_version},expected:{check.expected_schema_version}"
            )
            return ReadinessCheck(ready=False, components=components)
        components["database"] = "ready"
        return ReadinessCheck(ready=True, components=components)
