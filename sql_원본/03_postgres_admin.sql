-- PostgreSQL 관리자 계정으로 실행. CREATE DATABASE는 트랜잭션 블록 밖에서 실행.
-- 최초 1회; 기존 역할/DB가 있으면 해당 문장을 건너뛴다.
CREATE ROLE ragvectorid LOGIN PASSWORD 'ragvectorpw';
CREATE DATABASE mysqlragvectordb0 OWNER ragvectorid;
-- 새 DB mysqlragvectordb0에 관리자로 접속한 후:
-- REAL[] 배열 스키마에서는 vector 확장이 필요하지 않다.
-- GRANT USAGE, CREATE ON SCHEMA public TO ragvectorid;
-- 이후 ragvectorid 계정으로 접속하여 04_postgres_schema.sql 실행.
