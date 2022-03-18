import contextvars
import logging
import sqlite3
from typing import Type, TypeVar

import injector
from injector import Injector, provider, singleton, inject, Module, Provider
from fastapi import FastAPI, APIRouter, Depends
from starlette.requests import Request
import uvicorn


def configure_for_testing(binder):
    configuration = Configuration(':memory:')
    binder.bind(Configuration, to=configuration, scope=singleton)


class Configuration:
    def __init__(self, connection_string):
        self.connection_string = connection_string


logger = logging.getLogger(__name__)

T = TypeVar('T')


class RequestScope(injector.Scope):
    REGISTRY_KEY = "RequestScopeRegistry"
    _none = object()

    def configure(self) -> None:
        # self._locals = threading.local()
        self._registry = contextvars.ContextVar(self.REGISTRY_KEY, default=self._none)

    def enter(self) -> None:
        logger.warning('entering request scope')
        # assert not hasattr(self._locals, self.REGISTRY_KEY)
        # setattr(self._locals, self.REGISTRY_KEY, {})
        assert self._registry.get() is self._none
        self._registry.set({})

    def exit(self) -> None:
        logger.warning('exiting request scope')
        #for key, provider in getattr(self._locals, self.REGISTRY_KEY).items():
            # provider.get(self.injector).close()
            # delattr(self._locals, repr(key))

        # delattr(self._locals, self.REGISTRY_KEY)
        for key, provider in self._registry.get().items():
            provider.get(self.injector).close()
            del self._registry.get()[repr(key)]
        self._registry.set(self._none)

    def __enter__(self) -> None:
        self.enter()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore
        self.exit()

    def get(self, key: Type[T], provider: Provider[T]) -> Provider[T]:
        registry = self._registry.get()
        try:
            return registry[repr(key)]
            # return getattr(self._locals, repr(key))  # type: ignore
        except KeyError:
            provider = injector.InstanceProvider(provider.get(self.injector))
            # setattr(self._locals, repr(key), provider)
            try:
                logger.warning('set provider')
                # registry = getattr(self._locals, self.REGISTRY_KEY)
            except AttributeError:
                raise Exception(
                    f"{key} is request scoped, but no RequestScope entered!")
            registry[repr(key)] = provider
            return provider


request = injector.ScopeDecorator(RequestScope)


class DatabaseModule(Module):
    @request
    @provider
    def provide_sqlite_connection(self, configuration: Configuration) -> sqlite3.Connection:
        conn = sqlite3.connect(configuration.connection_string)
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS data (key PRIMARY KEY, value)')
        cursor.execute('INSERT OR REPLACE INTO data VALUES ("hello", "world")')
        return conn


class RequestHandler:
    @inject
    def __init__(self, db: sqlite3.Connection):
        self._db = db

    def get(self):
        cursor = self._db.cursor()
        cursor.execute('SELECT key, value FROM data ORDER by key')
        return cursor.fetchall()


router = APIRouter()


def do_inject(inject_cls):
    def do_do_inject(request: Request):
        return request.state.injector.get(inject_cls)
    return do_do_inject


@router.get('/all')
def get_all(query: RequestHandler = Depends(do_inject(RequestHandler))):
    return query.get()


def create_app() -> FastAPI:
    di = Injector([configure_for_testing, DatabaseModule()])

    app = FastAPI()

    @app.get('/')
    async def home():
        return {'at': 'home'}

    app.include_router(router)

    @app.middleware('http')
    async def injector_middleware(request: Request, call_next):
        request.state.injector = di
        di.get(RequestScope).enter()
        try:
            response = await call_next(request)
        finally:
            print('request.state.injector.close')
            scope = di.get(RequestScope)
            scope.exit()
        return response

    return app


if __name__ == '__main__':
    app = create_app()
    uvicorn.run(app)
