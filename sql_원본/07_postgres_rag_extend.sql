-- PostgreSQL / ragvectorid 계정으로 mysqlragvectordb0에 접속하여 실행한다. 04 실행 후 적용.
-- reviews, complaints 전용 벡터 테이블. rag_chunks(업로드 문서)와 분리하여
-- 상품·판매자·고객·평점·처리상태 메타데이터로 역할별 검색 범위를 제한한다.
-- embedding_model 컬럼과 현재 OLLAMA_EMBED_MODEL이 일치하는 행만 검색에 사용한다.
-- 아래 샘플 행은 'sample-placeholder' 모델이라 검색에서 제외되며, 백엔드 POST /rag/sync 실행 시
-- 같은 (review_id, chunk_no)/(complaint_id, chunk_no) 행이 실제 임베딩으로 덮어써진다.

-- 1. 상품 후기 청크
CREATE TABLE IF NOT EXISTS public.rag_review_chunks (
    id BIGSERIAL PRIMARY KEY,
    review_id BIGINT NOT NULL,
    chunk_no INTEGER NOT NULL,
    product_id BIGINT NOT NULL,
    seller_id BIGINT NULL,
    customer_id BIGINT NOT NULL,
    category VARCHAR(60) NOT NULL,
    rating SMALLINT NOT NULL,
    content TEXT NOT NULL,
    embedding REAL[] NOT NULL,
    embedding_model VARCHAR(100) NOT NULL,
    source_created_at TIMESTAMP NULL,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_rag_review_chunks_review_chunk UNIQUE (review_id, chunk_no),
    CONSTRAINT ck_rag_review_chunks_rating CHECK (rating BETWEEN 1 AND 5),
    CONSTRAINT ck_rag_review_chunks_embedding_768
        CHECK (array_ndims(embedding) = 1 AND array_length(embedding, 1) = 768)
);
CREATE INDEX IF NOT EXISTS idx_rag_review_chunks_product ON public.rag_review_chunks (product_id);
CREATE INDEX IF NOT EXISTS idx_rag_review_chunks_seller ON public.rag_review_chunks (seller_id);
CREATE INDEX IF NOT EXISTS idx_rag_review_chunks_rating ON public.rag_review_chunks (rating);
CREATE INDEX IF NOT EXISTS idx_rag_review_chunks_model ON public.rag_review_chunks (embedding_model);

-- 2. 고객 불만 청크 (불만 내용 + 처리 결과)
CREATE TABLE IF NOT EXISTS public.rag_complaint_chunks (
    id BIGSERIAL PRIMARY KEY,
    complaint_id BIGINT NOT NULL,
    chunk_no INTEGER NOT NULL,
    customer_id BIGINT NOT NULL,
    order_id BIGINT NULL,
    product_id BIGINT NULL,
    seller_id BIGINT NULL,
    category VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    has_resolution BOOLEAN NOT NULL DEFAULT FALSE,
    content TEXT NOT NULL,
    embedding REAL[] NOT NULL,
    embedding_model VARCHAR(100) NOT NULL,
    source_created_at TIMESTAMP NULL,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_rag_complaint_chunks_complaint_chunk UNIQUE (complaint_id, chunk_no),
    CONSTRAINT ck_rag_complaint_chunks_embedding_768
        CHECK (array_ndims(embedding) = 1 AND array_length(embedding, 1) = 768)
);
CREATE INDEX IF NOT EXISTS idx_rag_complaint_chunks_customer ON public.rag_complaint_chunks (customer_id);
CREATE INDEX IF NOT EXISTS idx_rag_complaint_chunks_seller ON public.rag_complaint_chunks (seller_id);
CREATE INDEX IF NOT EXISTS idx_rag_complaint_chunks_status ON public.rag_complaint_chunks (status, has_resolution);
CREATE INDEX IF NOT EXISTS idx_rag_complaint_chunks_model ON public.rag_complaint_chunks (embedding_model);

-- 3. 후기 샘플 (임베딩 예시값)
INSERT INTO public.rag_review_chunks (
    review_id, chunk_no, product_id, seller_id, customer_id, category, rating,
    content, embedding, embedding_model
)
VALUES
 (1, 0, 1, 1, 1, '전자기기', 5,
  '[상품후기] 상품: 무선 이어폰(전자기기) / 평점: 5점 / 내용: 음질과 착용감이 좋아 전자기기를 선호합니다.',
  ARRAY[1.0::REAL, 0.0::REAL, 0.0::REAL] || array_fill(0.0::REAL, ARRAY[765]), 'sample-placeholder'),
 (2, 0, 6, 1, 1, '전자기기', 2,
  '[상품후기] 상품: 휴대용 충전기(전자기기) / 평점: 2점 / 내용: 충전 속도가 느려서 이 충전기는 다시 구매하고 싶지 않습니다.',
  ARRAY[0.0::REAL, 1.0::REAL, 0.0::REAL] || array_fill(0.0::REAL, ARRAY[765]), 'sample-placeholder'),
 (3, 0, 3, 2, 2, '생활용품', 5,
  '[상품후기] 상품: 보온 텀블러(생활용품) / 평점: 5점 / 내용: 텀블러 보온력이 좋아 만족합니다.',
  ARRAY[0.0::REAL, 0.0::REAL, 1.0::REAL] || array_fill(0.0::REAL, ARRAY[765]), 'sample-placeholder')
ON CONFLICT (review_id, chunk_no) DO NOTHING;

-- 4. 불만 샘플 (임베딩 예시값)
INSERT INTO public.rag_complaint_chunks (
    complaint_id, chunk_no, customer_id, order_id, product_id, seller_id,
    category, status, has_resolution, content, embedding, embedding_model
)
VALUES
 (1, 0, 1, 1, 1, 1, '배송', 'OPEN', FALSE,
  '[고객불만] 분류: 배송 / 상태: OPEN / 상품: 무선 이어폰 / 내용: 배송 완료로 표시되었으나 상품을 받지 못했습니다.',
  ARRAY[1.0::REAL, 0.0::REAL, 0.0::REAL] || array_fill(0.0::REAL, ARRAY[765]), 'sample-placeholder'),
 (104, 0, 4, 109, 9, 2, '배송파손', 'RESOLVED', TRUE,
  '[고객불만] 분류: 배송파손 / 상태: RESOLVED / 상품: 밀폐 유리 용기 세트 / 내용: 유리 용기 세트 중 1개가 깨진 상태로 도착했습니다. / 처리결과: 파손 사진 확인 후 동일 상품 1개 무상 재발송.',
  ARRAY[0.0::REAL, 1.0::REAL, 0.0::REAL] || array_fill(0.0::REAL, ARRAY[765]), 'sample-placeholder'),
 (105, 0, 3, 107, 6, 1, '품질', 'RESOLVED', TRUE,
  '[고객불만] 분류: 품질 / 상태: RESOLVED / 상품: 휴대용 충전기 / 내용: 충전기가 사용 중 뜨거워집니다. / 처리결과: 회수 검사 후 불량 판정, 전액 환불.',
  ARRAY[0.0::REAL, 0.0::REAL, 1.0::REAL] || array_fill(0.0::REAL, ARRAY[765]), 'sample-placeholder')
ON CONFLICT (complaint_id, chunk_no) DO NOTHING;

SELECT 'rag_review_chunks' AS table_name, embedding_model, COUNT(*) AS rows
FROM public.rag_review_chunks GROUP BY embedding_model
UNION ALL
SELECT 'rag_complaint_chunks', embedding_model, COUNT(*)
FROM public.rag_complaint_chunks GROUP BY embedding_model
ORDER BY 1, 2;
