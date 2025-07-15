from typing import List, TypedDict, TypeVar, Generic, cast, Literal
from aiohttp import web
from aiohttp.helpers import reify
from aiohttp.client import ClientResponse


class SpawnProcessRequest(TypedDict):
    cmd: str
    args: list[str]
    env: dict[str, str]


class StopProcessRequest(TypedDict):
    pid: int


# Define a type variable for generic typing
J = TypeVar("J")
Q = TypeVar("Q", bound=dict[str, str])


# Create a generic "dummy" subclass of web.Response for typing purposes
class TypedJSONResponse(web.Response, Generic[J]):
    """A dummy subclass for typing JSON responses."""


class TypedClientResponse(ClientResponse, Generic[J]):
    """A dummy subclass for typing JSON responses."""

    async def json(self, *args, **kwargs) -> J:
        # Get the raw JSON data
        raw_data = await super().json(*args, **kwargs)

        # For now, we'll add validation based on the expected type
        # This is a temporary solution - ideally we'd have a registry of validators
        # based on the generic type parameter, but that's complex to implement
        # For now, we'll just return the raw data and let the calling code validate
        return cast(J, raw_data)


class TypedRequest(web.Request, Generic[J, Q]):
    """A dummy subclass for typing JSON requests."""

    async def json(self, *args, **kwargs) -> J:
        return cast(J, await super().json(*args, **kwargs))

    @reify
    def query(self) -> Q:
        return cast(Q, super().query)


class SpawnRequestSuccessResponse(TypedDict):
    status: Literal["success"]
    pid: int


class SpawnRequestFailureResponse(TypedDict):
    status: Literal["failure"]
    error: str


SpawnRequestResponse = SpawnRequestSuccessResponse | SpawnRequestFailureResponse

SubProcessIndexResponse = List[int]  # list of pids


class StopRequestSuccessResponse(TypedDict):
    status: Literal["success"]


class StopRequestFailureResponse(TypedDict):
    status: Literal["failure"]
    error: str


StopRequestResponse = StopRequestSuccessResponse | StopRequestFailureResponse


class SubscribeRequests(TypedDict):
    pid: str


class StreamingLineOutput(TypedDict):
    stream: str
    pid: int
    data: str
