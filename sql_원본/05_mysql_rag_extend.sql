-- MySQL 8.0 / ragid 또는 root 실행. 01, 02 실행 후 적용한다.
-- reviews·complaints RAG 확장과 관리자·판매자·구매자 역할 구분을 위한 스키마.
-- 여러 번 실행해도 안전하도록 컬럼 추가는 information_schema 확인 후 동적 SQL로 처리한다.
USE mysqlragdb0;

-- 1. 판매자
CREATE TABLE IF NOT EXISTS sellers (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. 서비스 사용자(역할). 교육용 데모이므로 비밀번호 없이 X-User-Id 헤더로 식별한다.
--    운영 환경에서는 JWT/세션 인증으로 교체하고 이 테이블은 권한 매핑 용도로 사용한다.
CREATE TABLE IF NOT EXISTS app_users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    role ENUM('ADMIN','SELLER','BUYER') NOT NULL,
    customer_id BIGINT NULL,
    seller_id BIGINT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (seller_id) REFERENCES sellers(id),
    CHECK ((role='ADMIN') OR (role='SELLER' AND seller_id IS NOT NULL) OR (role='BUYER' AND customer_id IS NOT NULL))
);

-- 3. products.seller_id : 판매자별 후기·불만 범위 제한에 사용
SET @ddl := IF((SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='products' AND COLUMN_NAME='seller_id')=0,
    'ALTER TABLE products ADD COLUMN seller_id BIGINT NULL AFTER category, ADD INDEX idx_products_seller (seller_id), ADD CONSTRAINT fk_products_seller FOREIGN KEY (seller_id) REFERENCES sellers(id)',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4. complaints 확장 : 대상 상품, 처리 결과(유사 사례 RAG의 핵심 근거), 처리 일시
SET @ddl := IF((SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='complaints' AND COLUMN_NAME='product_id')=0,
    'ALTER TABLE complaints ADD COLUMN product_id BIGINT NULL AFTER order_id, ADD INDEX idx_complaints_product (product_id), ADD CONSTRAINT fk_complaints_product FOREIGN KEY (product_id) REFERENCES products(id)',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := IF((SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='complaints' AND COLUMN_NAME='resolution')=0,
    'ALTER TABLE complaints ADD COLUMN resolution TEXT NULL AFTER status',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := IF((SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='complaints' AND COLUMN_NAME='resolved_at')=0,
    'ALTER TABLE complaints ADD COLUMN resolved_at DATETIME NULL AFTER resolution',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := IF((SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='complaints' AND COLUMN_NAME='updated_at')=0,
    'ALTER TABLE complaints ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := IF((SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='complaints' AND INDEX_NAME='idx_complaints_status')=0,
    'ALTER TABLE complaints ADD INDEX idx_complaints_status (status, created_at)',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 5. complaint_replies 작성자 기록
SET @ddl := IF((SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='complaint_replies' AND COLUMN_NAME='author_user_id')=0,
    'ALTER TABLE complaint_replies ADD COLUMN author_user_id BIGINT NULL AFTER manual_document_id, ADD CONSTRAINT fk_complaint_replies_author FOREIGN KEY (author_user_id) REFERENCES app_users(id)',
    'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 6. 판매자 후기 답글 (AI 초안 → 판매자 검토 → 게시)
CREATE TABLE IF NOT EXISTS review_replies (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    review_id BIGINT NOT NULL,
    seller_id BIGINT NULL,
    author_user_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    status ENUM('DRAFT','PUBLISHED') NOT NULL DEFAULT 'DRAFT',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (review_id) REFERENCES reviews(id),
    FOREIGN KEY (seller_id) REFERENCES sellers(id),
    FOREIGN KEY (author_user_id) REFERENCES app_users(id),
    INDEX idx_review_replies_review (review_id, created_at)
);

-- 7. RAG 증분 색인 상태 : 원문+임베딩모델 해시가 바뀐 행만 다시 임베딩한다.
CREATE TABLE IF NOT EXISTS rag_sync_state (
    source_type ENUM('REVIEW','COMPLAINT') NOT NULL,
    source_id BIGINT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    chunk_count INT NOT NULL DEFAULT 0,
    status ENUM('READY','FAILED') NOT NULL,
    error_message VARCHAR(500) NULL,
    indexed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (source_type, source_id),
    INDEX idx_rag_sync_status (status)
);

-- 8. AI 결과 이력 (후기 요약, 불만 처리 지원, 운영 인사이트, 통합 상담)
CREATE TABLE IF NOT EXISTS ai_reports (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NULL,
    role VARCHAR(10) NOT NULL,
    report_type VARCHAR(40) NOT NULL,
    target_type VARCHAR(20) NULL,
    target_id BIGINT NULL,
    question TEXT NULL,
    answer LONGTEXT NOT NULL,
    evidence_json JSON NULL,
    provider VARCHAR(20) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES app_users(id),
    INDEX idx_ai_reports_user (user_id, created_at),
    INDEX idx_ai_reports_type (report_type, created_at)
);
