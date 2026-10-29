import os
from contextlib import contextmanager
import pymysql
import psycopg
from dotenv import load_dotenv

load_dotenv()

@contextmanager
def mysql():
    connection = pymysql.connect(host=os.getenv('MYSQL_HOST','127.0.0.1'),port=int(os.getenv('MYSQL_PORT','3306')),user=os.getenv('MYSQL_USER','ragid'),password=os.getenv('MYSQL_PASSWORD','ragpw'),database=os.getenv('MYSQL_DATABASE','mysqlragdb0'),charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

@contextmanager
def pg():
    with psycopg.connect(os.environ['PG_DSN']) as connection:
        yield connection
