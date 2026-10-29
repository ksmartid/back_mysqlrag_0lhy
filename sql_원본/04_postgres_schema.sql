-- 1. 테이블 생성

CREATE TABLE IF NOT EXISTS public.rag_chunks (
    id BIGSERIAL PRIMARY KEY,
    mysql_document_id BIGINT NOT NULL,
    chunk_no INTEGER NOT NULL,
    source_title TEXT NOT NULL,
    source_type VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    embedding REAL[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_rag_chunks_document_chunk
        UNIQUE (mysql_document_id, chunk_no),

    CONSTRAINT ck_rag_chunks_embedding_768
        CHECK (
            array_ndims(embedding) = 1
            AND array_length(embedding, 1) = 768
        )
);

-- 2. 배송 문서
INSERT INTO public.rag_chunks (
    mysql_document_id, chunk_no, source_title,
    source_type, content, embedding
)
VALUES (
    1, 0, '배송 미수령 대응 매뉴얼',
    'PDF',
    '배송 완료로 표시되었지만 고객이 받지 못한 경우 운송장과 배송 사진을 확인하고 택배사에 조사를 요청한다.',
    ARRAY[1.0::REAL, 0.0::REAL, 0.0::REAL]
        || array_fill(0.0::REAL, ARRAY[765])
)
ON CONFLICT (mysql_document_id, chunk_no) DO NOTHING;

-- 3. 상품 교환 문서
INSERT INTO public.rag_chunks (
    mysql_document_id, chunk_no, source_title,
    source_type, content, embedding
)
VALUES (
    2, 0, '상품 하자 교환 매뉴얼',
    'PDF',
    '상품 하자가 접수되면 주문 내역과 고객이 제공한 사진을 확인한 뒤 교환 가능 여부를 안내한다.',
    ARRAY[0.0::REAL, 1.0::REAL, 0.0::REAL]
        || array_fill(0.0::REAL, ARRAY[765])
)
ON CONFLICT (mysql_document_id, chunk_no) DO NOTHING;

-- 4. 환불 문서
INSERT INTO public.rag_chunks (
    mysql_document_id, chunk_no, source_title,
    source_type, content, embedding
)
VALUES (
    3, 0, '결제 취소 및 환불 안내',
    'JSON',
    '환불 요청을 접수하면 결제 상태와 배송 시작 여부를 확인하고 적용 가능한 환불 절차를 안내한다.',
    ARRAY[0.0::REAL, 0.0::REAL, 1.0::REAL]
        || array_fill(0.0::REAL, ARRAY[765])
)
ON CONFLICT (mysql_document_id, chunk_no) DO NOTHING;

SELECT
    id,
    mysql_document_id,
    chunk_no,
    source_title,
    source_type,
    array_length (embedding, 1) AS embedding_dimensions
FROM public.rag_chunks
ORDER BY id;