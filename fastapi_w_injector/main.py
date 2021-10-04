import sqlite3

from injector import Injector, provider, singleton, inject, Module
from fastapi import FastAPI, APIRouter, Depends
from starlette.requests import Request
import uvicorn


def configure_for_testing(binder):
    configuration = Configuration(':memory:')
    binder.bind(Configuration, to=configuration, scope=singleton)


class Configuration:
    def __init__(self, connection_string):
        self.connection_string = connection_string


class DatabaseModule(Module):
    @singleton
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
        response = await call_next(request)
        print('request.state.injector.close')
        return response

    return app


if __name__ == '__main__':
    app = create_app()
    uvicorn.run(app)
