from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, TypeAdapter


class PreparedQuery(BaseModel):
    sql: str
    params: Union[list[Union[str, int]], dict[str, Union[str, int]]]


class TimeQueryRequest(BaseModel):
    type: Literal["time_query"] = "time_query"
    query: list[Union[str, PreparedQuery]]
    timeout_secs: float
    db_schema: Literal["JOB", "SQLStorm", "JOB-Complex", "Stack"] = "JOB"
    return_result: bool = False


class QueryCompleteResponse(BaseModel):
    result: Literal["complete"] = "complete"
    elapsed_secs: float
    query_result: Optional[str] = None


class QueryTimeoutResponse(BaseModel):
    result: Literal["timeout"] = "timeout"
    elapsed_secs: float


class QueryErrorResponse(BaseModel):
    result: Literal["error"] = "error"
    error: str


TimeQueryResult = Union[QueryCompleteResponse, QueryTimeoutResponse, QueryErrorResponse]


class TimeQueryResponse(BaseModel):
    type: Literal["time_query"] = "time_query"
    result: TimeQueryResult = Field(discriminator="result")


class RunSQLRequest(BaseModel):
    type: Literal["run_sql"] = "run_sql"
    query: list[Union[str, PreparedQuery]]
    db_schema: Literal["JOB", "SQLStorm", "JOB-Complex", "Stack"] = "JOB"


class RunSQLCompleteResponse(BaseModel):
    result: Literal["complete"] = "complete"
    df_json: str


class RunSQLErrorResponse(BaseModel):
    result: Literal["error"] = "error"
    error: str


class RunSQLResponse(BaseModel):
    type: Literal["run_sql"] = "run_sql"
    result: Union[RunSQLCompleteResponse, RunSQLErrorResponse] = Field(
        discriminator="result"
    )


RequestType = Union[TimeQueryRequest, RunSQLRequest]
ResponseType = Union[TimeQueryResponse, RunSQLResponse]
Request: TypeAdapter[RequestType] = TypeAdapter(RequestType)
Response: TypeAdapter[ResponseType] = TypeAdapter(ResponseType)
