import hashlib
import json
from psycopg.rows import dict_row
from .db import mysql, pg
from .ai import embed, embed_model

# 검색 대상
#  - document  : source_documents → public.rag_chunks (기존 PDF/JSON/IMAGE 업로드 문서)
#  - review    : reviews           → public.rag_review_chunks
#  - complaint : complaints        → public.rag_complaint_chunks (불만 내용 + 처리 결과)

COSINE='''SUM(x.a::double precision*x.b::double precision) /
    NULLIF(SQRT(SUM(x.a::double precision*x.a::double precision)) *
           SQRT(SUM(x.b::double precision*x.b::double precision)),0)'''

SOURCES={
    'review':{
        'state':'REVIEW','table':'public.rag_review_chunks','key':'review_id','id_col':'r.id',
        'meta':('product_id','seller_id','customer_id','category','rating'),
        'select':'SELECT r.id,r.customer_id,r.product_id,r.rating,r.content,r.created_at,p.name AS product_name,p.category,p.seller_id FROM reviews r JOIN products p ON p.id=r.product_id',
    },
    'complaint':{
        'state':'COMPLAINT','table':'public.rag_complaint_chunks','key':'complaint_id','id_col':'c.id',
        'meta':('customer_id','order_id','product_id','seller_id','category','status','has_resolution'),
        'select':'SELECT c.id,c.customer_id,c.order_id,c.product_id,c.category,c.content,c.status,c.resolution,c.created_at,p.name AS product_name,p.seller_id FROM complaints c LEFT JOIN products p ON p.id=c.product_id',
    },
}

# 검색 필터 화이트리스트 (컬럼명은 코드 상수만 사용하고 값은 파라미터 바인딩)
FILTERS={
    'product_id':'c.product_id=%s','seller_id':'c.seller_id=%s','customer_id':'c.customer_id=%s',
    'category':'c.category=%s','status':'c.status=%s','has_resolution':'c.has_resolution=%s',
    'min_rating':'c.rating>=%s','max_rating':'c.rating<=%s','since':'c.source_created_at>=%s',
    'exclude_customer':'c.customer_id<>%s',
}

def chunks(text, size=700, overlap=100):
    text=' '.join(text.split())
    if not text:return []
    result=[];start=0
    while start<len(text):
        result.append(text[start:start+size])
        if start+size>=len(text):break
        start+=size-overlap
    return result

def source_text(kind,row):
    if kind=='review':
        return f"[상품후기] 상품: {row['product_name']}({row['category']}) / 평점: {row['rating']}점 / 내용: {row['content']}"
    text=f"[고객불만] 분류: {row['category']} / 상태: {row['status']} / 상품: {row.get('product_name') or '미지정'} / 내용: {row['content']}"
    if row.get('resolution'):text+=f" / 처리결과: {row['resolution']}"
    return text

def meta_values(kind,row):
    if kind=='review':return (row['product_id'],row['seller_id'],row['customer_id'],row['category'],row['rating'])
    return (row['customer_id'],row['order_id'],row['product_id'],row['seller_id'],row['category'],row['status'],bool(row.get('resolution')))

def content_hash(text):
    return hashlib.sha256(f'{embed_model()}\n{text}'.encode()).hexdigest()

def fetch_sources(kind,ids=None):
    cfg=SOURCES[kind];sql=cfg['select'];params=()
    if ids is not None:
        if not ids:return []
        sql+=f" WHERE {cfg['id_col']} IN ({','.join(['%s']*len(ids))})";params=tuple(ids)
    with mysql() as conn:
        with conn.cursor() as cur:cur.execute(sql+f" ORDER BY {cfg['id_col']}",params);return cur.fetchall()

def sync_states(kind):
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT source_id,content_hash,status,chunk_count,error_message,indexed_at FROM rag_sync_state WHERE source_type=%s',(SOURCES[kind]['state'],))
            return {r['source_id']:r for r in cur.fetchall()}

async def index_rows(kind,rows,force=False):
    cfg=SOURCES[kind];model=embed_model();table,key,meta=cfg['table'],cfg['key'],cfg['meta']
    updates=meta+('content','embedding','embedding_model','source_created_at')
    upsert=(f"INSERT INTO {table} ({key},chunk_no,{','.join(meta)},content,embedding,embedding_model,source_created_at) "
            f"VALUES (%s,%s,{','.join(['%s']*len(meta))},%s,%s::real[],%s,%s) "
            f"ON CONFLICT ({key},chunk_no) DO UPDATE SET {','.join(f'{c}=EXCLUDED.{c}' for c in updates)},indexed_at=now()")
    states=sync_states(kind)
    stats={'kind':kind,'total':len(rows),'indexed':0,'skipped':0,'failed':0,'errors':[]}
    results=[]
    try:
        for row in rows:
            text=source_text(kind,row);digest=content_hash(text);prev=states.get(row['id'])
            if not force and prev and prev['content_hash']==digest and prev['status']=='READY':
                stats['skipped']+=1;continue
            try:
                pieces=chunks(text);vectors=[await embed(p) for p in pieces]
                with pg() as conn:
                    with conn.cursor() as cur:
                        for i,(piece,vector) in enumerate(zip(pieces,vectors)):
                            cur.execute(upsert,(row['id'],i,*meta_values(kind,row),piece,vector,model,row['created_at']))
                        cur.execute(f'DELETE FROM {table} WHERE {key}=%s AND chunk_no>=%s',(row['id'],len(pieces)))
                results.append((row['id'],digest,len(pieces),'READY',None));stats['indexed']+=1
            except Exception as exc:
                detail=str(getattr(exc,'detail',None) or exc)[:500]
                results.append((row['id'],digest,0,'FAILED',detail));stats['failed']+=1
                if len(stats['errors'])<5:stats['errors'].append({'id':row['id'],'error':detail[:200]})
    finally:
        if results:
            with mysql() as conn:
                with conn.cursor() as cur:
                    cur.executemany('INSERT INTO rag_sync_state (source_type,source_id,content_hash,chunk_count,status,error_message) VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE content_hash=VALUES(content_hash),chunk_count=VALUES(chunk_count),status=VALUES(status),error_message=VALUES(error_message),indexed_at=NOW()',
                                    [(cfg['state'],*r) for r in results])
    return stats

async def sync_all(kind,force=False):
    rows=fetch_sources(kind);stats=await index_rows(kind,rows,force)
    cfg=SOURCES[kind];ids=[r['id'] for r in rows]
    # 원본에서 삭제된 행의 벡터·상태 정리
    with pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {cfg['table']} WHERE NOT ({cfg['key']} = ANY(%s::bigint[]))",(ids,));stats['removed']=cur.rowcount
    with mysql() as conn:
        with conn.cursor() as cur:
            if ids:cur.execute(f"DELETE FROM rag_sync_state WHERE source_type=%s AND source_id NOT IN ({','.join(['%s']*len(ids))})",(cfg['state'],*ids))
            else:cur.execute('DELETE FROM rag_sync_state WHERE source_type=%s',(cfg['state'],))
    return stats

async def index_one(kind,source_id):
    """등록·수정 직후 호출. 색인 실패가 원본 저장을 막지 않도록 상태만 반환한다."""
    try:
        stats=await index_rows(kind,fetch_sources(kind,[source_id]),force=True)
        return 'READY' if stats['indexed'] else 'FAILED'
    except Exception:
        return 'FAILED'

def status_summary(kind):
    rows=fetch_sources(kind);states=sync_states(kind)
    ready=failed=pending=0
    for row in rows:
        state=states.get(row['id'])
        if not state or state['content_hash']!=content_hash(source_text(kind,row)):pending+=1
        elif state['status']=='READY':ready+=1
        else:failed+=1
    with pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FILTER (WHERE embedding_model=%s),COUNT(*) FROM {SOURCES[kind]['table']}",(embed_model(),));current,total=cur.fetchone()
    return {'kind':kind,'source_rows':len(rows),'ready':ready,'failed':failed,'pending':pending,'vector_chunks':current,'vector_chunks_other_model':total-current}

def search_chunks(kind,vector,filters=None,limit=5,exclude_id=None):
    cfg=SOURCES[kind];key=cfg['key']
    where=['c.embedding_model=%s'];params=[embed_model()]
    for name,value in (filters or {}).items():
        if value is None:continue
        where.append(FILTERS[name]);params.append(value)
    if exclude_id is not None:where.append(f'c.{key}<>%s');params.append(exclude_id)
    cols=','.join(f'c.{c}' for c in (key,)+cfg['meta']+('content','source_created_at'))
    sql=(f'SELECT {cols},{COSINE} AS score FROM {cfg["table"]} c '
         'CROSS JOIN LATERAL unnest(c.embedding,%s::real[]) AS x(a,b) '
         f'WHERE {" AND ".join(where)} GROUP BY c.id ORDER BY score DESC NULLS LAST LIMIT %s')
    with pg() as conn:
        with conn.cursor(row_factory=dict_row) as cur:cur.execute(sql,[vector,*params,limit*3]);rows=cur.fetchall()
    best={}
    for row in rows:
        if row[key] not in best:best[row[key]]=row
    hits=[]
    for row in list(best.values())[:limit]:
        row['kind']=kind;row['id']=row.pop(key);row['score']=round(float(row['score'] or 0),3);row['excerpt']=row['content'][:300]
        hits.append(row)
    return hits

def search_documents(vector,limit=4):
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM source_documents WHERE index_status='READY'");ready_ids=[r['id'] for r in cur.fetchall()]
    if not ready_ids:return []
    with pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f'''SELECT c.mysql_document_id,c.source_title,c.content,{COSINE} AS score
                FROM public.rag_chunks c
                CROSS JOIN LATERAL unnest(c.embedding,%s::real[]) AS x(a,b)
                WHERE c.mysql_document_id = ANY(%s::bigint[])
                GROUP BY c.id,c.mysql_document_id,c.source_title,c.content
                ORDER BY score DESC NULLS LAST LIMIT %s''',(vector,ready_ids,limit))
            hits=cur.fetchall()
    return [{'kind':'document','id':h[0],'document_id':h[0],'title':h[1],'content':h[2],'excerpt':h[2][:300],'score':round(float(h[3] or 0),3)} for h in hits]

def context_block(hits):
    label={'document':'문서','review':'후기','complaint':'불만'}
    return '\n'.join(f"[{label[h['kind']]} {h['id']}{' · '+h['title'] if h.get('title') else ''}] {h['content']}" for h in hits) or '(검색된 근거 없음)'

def public_hits(hits,user):
    """응답용 근거. 원문 전체와 다른 고객 식별자는 관리자에게만 제공한다."""
    result=[]
    for h in hits:
        item={k:v for k,v in h.items() if k!='content'}
        if user.role!='ADMIN':item.pop('customer_id',None)
        result.append(item)
    return result

def save_report(user,report_type,answer,provider,evidence=None,question=None,target_type=None,target_id=None):
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('INSERT INTO ai_reports (user_id,role,report_type,target_type,target_id,question,answer,evidence_json,provider) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                        (user.id,user.role,report_type,target_type,target_id,question,answer,json.dumps(evidence or {},ensure_ascii=False,default=str),provider))
            return cur.lastrowid
