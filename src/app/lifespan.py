
'''Опеределяет что происходит перед, и после, работы FastAPI приложения'''
from fastapi import FastAPI
from src.db.initialize import setup_database, engine
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    #Выполняется перед включением приложения
    await setup_database()

    yield

    #Выполняется после выключения приложения
    await engine.dispose()
    
