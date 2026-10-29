# 쇼핑몰 MySQL RAG 백엔드

Python 3.12, MySQL 8, PostgreSQL (REAL[768] 배열; pgvector 설치 불필요), Ollama가 필요하다. 교육용 예시 데이터는 가명이며 실제 고객 데이터가 아니다.

## 설치

1. MySQL root에서 `sql/01_mysql_init.sql`, 이어 `sql/02_mysql_seed.sql` 실행.
2. PostgreSQL 관리자에서 `sql/03_postgres_admin.sql` 실행. `CREATE DATABASE`를 별도의 자동 커밋 실행으로 처리한다. 새 DB에 ragvectorid로 접속하여 `sql/04_postgres_schema.sql` 전체를 실행한다. 이 SQL의 샘플 3건은 임베딩 예시이며 실제 검색에는 READY 상태로 적재된 MySQL 문서만 사용한다. CREATE ROLE 중복 시 건너뛴다.
3. **후기·불만 RAG 확장** (여러 번 실행해도 안전)
   - MySQL: `sql/05_mysql_rag_extend.sql` → `sql/06_mysql_rag_seed.sql`
   - PostgreSQL(ragvectorid, mysqlragvectordb0): `sql/07_postgres_rag_extend.sql`
4. `ollama pull qwen2.5:3b` 및 `ollama pull nomic-embed-text` 실행. 후자는 768차원 임베딩이다.
5. `.env.example`을 `.env`로 복사하고 접속값을 설정. PDF 생성용 한글 TTF를 준비해 `KOREAN_FONT_PATH` 환경변수로 경로 지정.
6. `uv sync --python 3.12` 후 실행:

```powershell
uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Windows 앱 제어 정책에서 uvicorn.exe가 차단되면 `python -m uvicorn` 형태를 사용한다.

7. 최초 1회 후기·불만 벡터 색인: 관리자(X-User-Id: 1)로 `POST /rag/sync` 호출, 또는 프론트 **관리자 → RAG 색인 관리 → 증분 동기화**.

## 추가 테이블

| DB | 테이블 | 용도 |
|---|---|---|
| MySQL | `sellers` | 판매자. `products.seller_id`로 상품과 연결 |
| MySQL | `app_users` | 관리자·판매자·구매자 역할과 고객/판매자 매핑 |
| MySQL | `review_replies` | 판매자 후기 답글 (AI 초안 → DRAFT/PUBLISHED) |
| MySQL | `rag_sync_state` | 후기·불만 행별 색인 해시·상태. 변경된 행만 재임베딩 |
| MySQL | `ai_reports` | 통합 상담·후기 요약·불만 처리 지원·인사이트 결과 이력 |
| MySQL | `complaints` 컬럼 추가 | `product_id`, `resolution`(처리 결과), `resolved_at`, `updated_at` |
| PostgreSQL | `rag_review_chunks` | 후기 임베딩 + 상품·판매자·고객·평점 메타 |
| PostgreSQL | `rag_complaint_chunks` | 불만(내용+처리 결과) 임베딩 + 고객·상품·판매자·상태 메타 |

기존 `rag_chunks`(업로드 문서)는 그대로 두고 후기·불만은 별도 테이블로 분리했다. 메타 컬럼으로 역할별 검색 범위(판매자는 본인 상품, 구매자는 본인 불만)를 SQL WHERE에서 제한한다. `embedding_model`이 현재 `OLLAMA_EMBED_MODEL`과 같은 행만 검색하므로, 07 SQL의 `sample-placeholder` 샘플은 검색에서 제외되고 `/rag/sync` 시 실제 임베딩으로 덮어써진다.

## 색인 흐름

- 후기 작성(`POST /reviews`), 불만 접수(`POST /complaints`), 처리 상태·결과 저장(`PATCH /complaints/{id}`) 직후 해당 행을 자동 색인한다. 색인에 실패해도 원본 저장은 유지되고 `rag_sync_state`에 FAILED로 남는다.
- `POST /rag/sync {"targets":["review","complaint"],"force":false}`는 원문+모델 해시가 바뀐 행만 재임베딩하고, 원본에서 삭제된 행의 벡터를 정리한다. 임베딩 모델을 바꾸면 해시가 달라져 전체가 다시 색인된다.
- `GET /rag/status`는 원본 행 수, 색인됨, 변경 대기, 실패, 모델별 벡터 청크 수를 보여 준다.

## 역할과 인증

데모에서는 `X-User-Id` 헤더로 `app_users`를 조회하고, 역할과 범위는 서버 DB 값만 신뢰한다. 운영 환경에서는 JWT/세션 검증 결과의 사용자 ID로 같은 조회를 하도록 `app/auth.py`의 `current_user`만 교체한다. `GET /users`는 데모용 사용자 선택 목록이다.

| 기능 | API | 관리자 | 판매자 | 구매자 |
|---|---|---|---|---|
| 대시보드 | `GET /dashboard` | 전체 | 본인 상품 | 본인 주문·문의 |
| 통합 RAG 상담 | `POST /rag/ask` | 문서+전체 후기+전체 불만 | 문서+본인 상품 후기·불만 | 문서+전체 후기+본인 불만 |
| 후기 AI 요약 | `POST /rag/reviews/summary` | 개선 액션 포함 | 본인 상품만 | 구매 판단용 요약 |
| 후기 답글 초안 | `POST /rag/reviews/{id}/draft-reply`, `POST /review-replies` | O | 본인 상품 | - |
| 불만 처리 지원 | `POST /rag/complaints/{id}/assist` | O | 본인 상품 | - |
| 불만 상태·처리 결과 | `PATCH /complaints/{id}` | O | 본인 상품 | - |
| 답변 저장·승인·발송 | `POST /replies`, `PATCH /replies/{id}` | O | 본인 상품 | 발송(SENT)만 조회 |
| 운영 인사이트 | `POST /rag/insights` | 전체 | 본인 상품 | - |
| 후기 작성 | `POST /reviews` | - | - | 배송 완료 구매 상품만 |
| 문의·불만 접수 | `POST /complaints` | 대리 접수 | - | 본인 주문 검증 |
| 맞춤 추천 | `POST /recommendations` | O | - | 본인 |
| 색인 관리·문서 적재 | `/rag/status`, `/rag/sync`, `/documents/*`, `/manual.pdf` | O | - | - |
| AI 결과 이력 | `GET /ai-reports` | 전체 | 본인 | 본인 |

## RAG 활용 방식

- **불만 처리 지원**: 대상 불만을 임베딩해 처리 결과가 있는(`has_resolution`) 유사 불만, 같은 상품 후기, 정책 문서를 검색하고 상황 요약·유사 사례 처리 방식·권장 절차·고객 응대 초안을 생성한다. `/complaints/draft-reply`도 같은 로직을 사용한다. 불만을 RESOLVED로 닫을 때는 처리 결과 입력이 필수이며, 이 결과가 다음 유사 사례 검색의 근거가 된다.
- **후기 요약**: MySQL 평점 통계와, 상품 범위 안의 긍정(4점 이상)·부정(3점 이하) 후기 벡터 검색 결과를 결합한다. 판매자·관리자에게는 관련 불만과 개선 액션까지 제공한다.
- **운영 인사이트**: 기간별 불만·평점 통계와 품질/배송/환불/상품 설명 주제의 부정 후기·불만 검색 결과로 핵심 이슈 Top 3, 즉시 조치, 정책 개선안을 만든다.
- **맞춤 추천**: 기존 최근 3개월 구매·후기 근거에 더해, 고객의 긍정 후기와 비슷한 다른 구매자의 긍정 후기(후기 RAG)를 추천 이유로 사용한다.
- 응답의 근거 목록에서 원문 전체와 다른 고객의 `customer_id`는 관리자에게만 제공하고, 후기 작성자 이름은 관리자 외에는 마스킹한다.

## 기타

`/documents/image`는 비전 지원 Ollama 모델을 OLLAMA_VISION_MODEL로 지정해야 한다. 이미지 글자 전사 결과는 원본과 대조한다. `/manual.pdf`는 처리 완료 불만의 처리 결과를 "처리 사례"로 포함하며, 다운로드 후 `/documents/pdf`에 다시 올리면 문서 RAG에 포함된다. 생성 답변은 자동으로 고객에게 발송하지 않으며 담당자가 DRAFT → APPROVED → SENT로 상태를 바꾼다.

프론트의 모델 선택으로 로컬 Ollama 또는 Gemini 답변을 고른다. Gemini 사용 시 백엔드 `.env`의 `GEMINI_API_KEY`를 설정한다. 임베딩은 두 모드 모두 로컬 Ollama를 사용한다. `.env`는 제출하지 않는다.

백업 예: `mysqldump -u ragid -p --default-character-set=utf8mb4 mysqlragdb0 > dbbackupfile_YYYYMMDD_HHMM.sql`. PostgreSQL 벡터 백업은 `pg_dump -U ragvectorid mysqlragvectordb0 > pgvector_backup.sql`. REAL[] 코사인 검색은 PostgreSQL에서 필터 후 전수 계산한다. 후기·불만이 수만 건 이상으로 늘면 pgvector 설치 후 스키마와 `app/rag.py`의 검색 SQL을 함께 변경한다.
