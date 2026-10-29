-- DROP SCHEMA public;

-- CREATE SCHEMA public AUTHORIZATION pg_database_owner;

COMMENT ON SCHEMA public IS 'standard public schema';

-- DROP SEQUENCE public.rag_chunks_id_seq;

CREATE SEQUENCE public.rag_chunks_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.rag_chunks_id_seq OWNER TO ragvectorid;
GRANT ALL ON SEQUENCE public.rag_chunks_id_seq TO ragvectorid;

-- DROP SEQUENCE public.rag_complaint_chunks_id_seq;

CREATE SEQUENCE public.rag_complaint_chunks_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.rag_complaint_chunks_id_seq OWNER TO ragvectorid;
GRANT ALL ON SEQUENCE public.rag_complaint_chunks_id_seq TO ragvectorid;

-- DROP SEQUENCE public.rag_review_chunks_id_seq;

CREATE SEQUENCE public.rag_review_chunks_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

-- Permissions

ALTER SEQUENCE public.rag_review_chunks_id_seq OWNER TO ragvectorid;
GRANT ALL ON SEQUENCE public.rag_review_chunks_id_seq TO ragvectorid;
-- public.rag_chunks definition

-- Drop table

-- DROP TABLE public.rag_chunks;

CREATE TABLE public.rag_chunks ( id bigserial NOT NULL, mysql_document_id int8 NOT NULL, chunk_no int4 NOT NULL, source_title text NOT NULL, source_type varchar(20) NOT NULL, "content" text NOT NULL, embedding _float4 NOT NULL, created_at timestamptz DEFAULT now() NOT NULL, CONSTRAINT ck_rag_chunks_embedding_768 CHECK (((array_ndims(embedding) = 1) AND (array_length(embedding, 1) = 768))), CONSTRAINT rag_chunks_chunk_no_not_null NOT NULL chunk_no, CONSTRAINT rag_chunks_content_not_null NOT NULL content, CONSTRAINT rag_chunks_created_at_not_null NOT NULL created_at, CONSTRAINT rag_chunks_embedding_not_null NOT NULL embedding, CONSTRAINT rag_chunks_id_not_null NOT NULL id, CONSTRAINT rag_chunks_mysql_document_id_not_null NOT NULL mysql_document_id, CONSTRAINT rag_chunks_pkey PRIMARY KEY (id), CONSTRAINT rag_chunks_source_title_not_null NOT NULL source_title, CONSTRAINT rag_chunks_source_type_not_null NOT NULL source_type, CONSTRAINT uq_rag_chunks_document_chunk UNIQUE (mysql_document_id, chunk_no));

-- Permissions

ALTER TABLE public.rag_chunks OWNER TO ragvectorid;
GRANT ALL ON TABLE public.rag_chunks TO ragvectorid;


-- public.rag_complaint_chunks definition

-- Drop table

-- DROP TABLE public.rag_complaint_chunks;

CREATE TABLE public.rag_complaint_chunks ( id bigserial NOT NULL, complaint_id int8 NOT NULL, chunk_no int4 NOT NULL, customer_id int8 NOT NULL, order_id int8 NULL, product_id int8 NULL, seller_id int8 NULL, category varchar(50) NOT NULL, status varchar(20) NOT NULL, has_resolution bool DEFAULT false NOT NULL, "content" text NOT NULL, embedding _float4 NOT NULL, embedding_model varchar(100) NOT NULL, source_created_at timestamp NULL, indexed_at timestamptz DEFAULT now() NOT NULL, CONSTRAINT ck_rag_complaint_chunks_embedding_768 CHECK (((array_ndims(embedding) = 1) AND (array_length(embedding, 1) = 768))), CONSTRAINT rag_complaint_chunks_category_not_null NOT NULL category, CONSTRAINT rag_complaint_chunks_chunk_no_not_null NOT NULL chunk_no, CONSTRAINT rag_complaint_chunks_complaint_id_not_null NOT NULL complaint_id, CONSTRAINT rag_complaint_chunks_content_not_null NOT NULL content, CONSTRAINT rag_complaint_chunks_customer_id_not_null NOT NULL customer_id, CONSTRAINT rag_complaint_chunks_embedding_model_not_null NOT NULL embedding_model, CONSTRAINT rag_complaint_chunks_embedding_not_null NOT NULL embedding, CONSTRAINT rag_complaint_chunks_has_resolution_not_null NOT NULL has_resolution, CONSTRAINT rag_complaint_chunks_id_not_null NOT NULL id, CONSTRAINT rag_complaint_chunks_indexed_at_not_null NOT NULL indexed_at, CONSTRAINT rag_complaint_chunks_pkey PRIMARY KEY (id), CONSTRAINT rag_complaint_chunks_status_not_null NOT NULL status, CONSTRAINT uq_rag_complaint_chunks_complaint_chunk UNIQUE (complaint_id, chunk_no));
CREATE INDEX idx_rag_complaint_chunks_customer ON public.rag_complaint_chunks USING btree (customer_id);
CREATE INDEX idx_rag_complaint_chunks_model ON public.rag_complaint_chunks USING btree (embedding_model);
CREATE INDEX idx_rag_complaint_chunks_seller ON public.rag_complaint_chunks USING btree (seller_id);
CREATE INDEX idx_rag_complaint_chunks_status ON public.rag_complaint_chunks USING btree (status, has_resolution);

-- Permissions

ALTER TABLE public.rag_complaint_chunks OWNER TO ragvectorid;
GRANT ALL ON TABLE public.rag_complaint_chunks TO ragvectorid;


-- public.rag_review_chunks definition

-- Drop table

-- DROP TABLE public.rag_review_chunks;

CREATE TABLE public.rag_review_chunks ( id bigserial NOT NULL, review_id int8 NOT NULL, chunk_no int4 NOT NULL, product_id int8 NOT NULL, seller_id int8 NULL, customer_id int8 NOT NULL, category varchar(60) NOT NULL, rating int2 NOT NULL, "content" text NOT NULL, embedding _float4 NOT NULL, embedding_model varchar(100) NOT NULL, source_created_at timestamp NULL, indexed_at timestamptz DEFAULT now() NOT NULL, CONSTRAINT ck_rag_review_chunks_embedding_768 CHECK (((array_ndims(embedding) = 1) AND (array_length(embedding, 1) = 768))), CONSTRAINT ck_rag_review_chunks_rating CHECK (((rating >= 1) AND (rating <= 5))), CONSTRAINT rag_review_chunks_category_not_null NOT NULL category, CONSTRAINT rag_review_chunks_chunk_no_not_null NOT NULL chunk_no, CONSTRAINT rag_review_chunks_content_not_null NOT NULL content, CONSTRAINT rag_review_chunks_customer_id_not_null NOT NULL customer_id, CONSTRAINT rag_review_chunks_embedding_model_not_null NOT NULL embedding_model, CONSTRAINT rag_review_chunks_embedding_not_null NOT NULL embedding, CONSTRAINT rag_review_chunks_id_not_null NOT NULL id, CONSTRAINT rag_review_chunks_indexed_at_not_null NOT NULL indexed_at, CONSTRAINT rag_review_chunks_pkey PRIMARY KEY (id), CONSTRAINT rag_review_chunks_product_id_not_null NOT NULL product_id, CONSTRAINT rag_review_chunks_rating_not_null NOT NULL rating, CONSTRAINT rag_review_chunks_review_id_not_null NOT NULL review_id, CONSTRAINT uq_rag_review_chunks_review_chunk UNIQUE (review_id, chunk_no));
CREATE INDEX idx_rag_review_chunks_model ON public.rag_review_chunks USING btree (embedding_model);
CREATE INDEX idx_rag_review_chunks_product ON public.rag_review_chunks USING btree (product_id);
CREATE INDEX idx_rag_review_chunks_rating ON public.rag_review_chunks USING btree (rating);
CREATE INDEX idx_rag_review_chunks_seller ON public.rag_review_chunks USING btree (seller_id);

-- Permissions

ALTER TABLE public.rag_review_chunks OWNER TO ragvectorid;
GRANT ALL ON TABLE public.rag_review_chunks TO ragvectorid;




-- Permissions

GRANT ALL ON SCHEMA public TO pg_database_owner;
GRANT USAGE ON SCHEMA public TO public;