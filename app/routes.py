import json
from datetime import datetime, timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from .db import mysql
from .ai import embed, complete, embed_model
from .auth import User, current_user, roles, mask_name, assert_product_scope, assert_complaint_scope
from .rag import search_chunks, search_documents, context_block, public_hits, save_report, index_one, sync_all, status_summary, source_text

router=APIRouter()
Provider=Literal['local','gemini']
Source=Literal['document','review','complaint']

ROLE_GUIDE={
    'BUYER':'독자는 구매자다. 친절하게 답하고 다른 고객의 개인정보나 내부 처리 메모를 노출하지 않는다. 환불·교환 확정 여부는 고객센터 확인이 필요하다고 안내한다.',
    'SELLER':'독자는 판매자다. 본인 상품의 후기·불만 근거로 원인과 개선 조치를 실무적으로 제시한다.',
    'ADMIN':'독자는 쇼핑몰 운영 관리자다. 정책 문서와 처리 사례를 근거로 처리 기준과 운영 개선안을 제시한다.',
}

class RagAskIn(BaseModel):
    question:str=Field(min_length=2,max_length=2000)
    sources:list[Source]=Field(default_factory=lambda:['document','review','complaint'],min_length=1)
    product_id:int|None=None
    provider:Provider='local'

class ProductAiIn(BaseModel):
    product_id:int
    provider:Provider='local'

class ProviderIn(BaseModel):
    provider:Provider='local'

class InsightIn(BaseModel):
    provider:Provider='local'
    days:int=Field(90,ge=7,le=365)

class SyncIn(BaseModel):
    targets:list[Literal['review','complaint']]=Field(default_factory=lambda:['review','complaint'],min_length=1)
    force:bool=False

class ReviewIn(BaseModel):
    product_id:int
    rating:int=Field(ge=1,le=5)
    content:str=Field(min_length=5,max_length=2000)

class ReviewReplyIn(BaseModel):
    review_id:int
    content:str=Field(min_length=3,max_length=2000)
    status:Literal['DRAFT','PUBLISHED']='DRAFT'

class ComplaintUpdateIn(BaseModel):
    status:Literal['OPEN','IN_PROGRESS','RESOLVED']
    resolution:str|None=Field(default=None,max_length=4000)

def review_scope(user:User):
    return {'seller_id':user.seller_id} if user.role=='SELLER' else {}

def complaint_scope(user:User):
    if user.role=='SELLER':return {'seller_id':user.seller_id}
    if user.role=='BUYER':return {'customer_id':user.customer_id}
    return {}

def sql_scope(user:User,alias_product='p',alias_customer=None):
    """MySQL 조회용 범위 조건과 파라미터"""
    if user.role=='SELLER':return f' AND {alias_product}.seller_id=%s',[user.seller_id]
    if user.role=='BUYER' and alias_customer:return f' AND {alias_customer}.customer_id=%s',[user.customer_id]
    return '',[]

def get_product(product_id):
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT p.id,p.name,p.category,p.price,p.seller_id,s.name AS seller_name FROM products p LEFT JOIN sellers s ON s.id=p.seller_id WHERE p.id=%s',(product_id,));return cur.fetchone()

def get_complaint(complaint_id):
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT c.*,p.name AS product_name,p.seller_id,u.name AS customer_name FROM complaints c LEFT JOIN products p ON p.id=c.product_id JOIN customers u ON u.id=c.customer_id WHERE c.id=%s',(complaint_id,));return cur.fetchone()

def split_draft(answer,marker='### 고객 응대 초안'):
    return answer.split(marker,1)[1].strip() if marker in answer else answer

# ---------------------------------------------------------------- 사용자·기초 데이터

@router.get('/users')
def users():
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT u.id,u.username,u.display_name,u.role,u.customer_id,u.seller_id,s.name AS seller_name FROM app_users u LEFT JOIN sellers s ON s.id=u.seller_id WHERE u.active=1 ORDER BY FIELD(u.role,'ADMIN','SELLER','BUYER'),u.id")
            return cur.fetchall()

@router.get('/me')
def me(user:User=Depends(current_user)):
    return user

@router.get('/products')
def products(user:User=Depends(current_user)):
    scope,params=sql_scope(user)
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute(f'''SELECT p.id,p.name,p.category,p.price,p.seller_id,s.name AS seller_name,
                ROUND(AVG(r.rating),2) AS avg_rating,COUNT(r.id) AS review_count,SUM(r.rating<=2) AS low_reviews
                FROM products p LEFT JOIN sellers s ON s.id=p.seller_id LEFT JOIN reviews r ON r.product_id=p.id
                WHERE p.active=1{scope} GROUP BY p.id,p.name,p.category,p.price,p.seller_id,s.name ORDER BY p.id''',params)
            return cur.fetchall()

@router.get('/orders')
def orders(user:User=Depends(roles('BUYER'))):
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('''SELECT o.id,o.ordered_at,o.status,oi.product_id,p.name AS product_name,oi.quantity,
                EXISTS(SELECT 1 FROM reviews r WHERE r.customer_id=o.customer_id AND r.product_id=oi.product_id) AS reviewed
                FROM orders o JOIN order_items oi ON oi.order_id=o.id JOIN products p ON p.id=oi.product_id
                WHERE o.customer_id=%s ORDER BY o.ordered_at DESC,oi.id''',(user.customer_id,));rows=cur.fetchall()
    grouped={}
    for r in rows:
        order=grouped.setdefault(r['id'],{'id':r['id'],'ordered_at':r['ordered_at'],'status':r['status'],'items':[]})
        order['items'].append({'product_id':r['product_id'],'product_name':r['product_name'],'quantity':r['quantity'],'reviewed':bool(r['reviewed'])})
    return list(grouped.values())

# ---------------------------------------------------------------- 후기

@router.get('/reviews')
def reviews(product_id:int|None=None,max_rating:int|None=Query(None,ge=1,le=5),limit:int=Query(50,ge=1,le=200),user:User=Depends(current_user)):
    scope,params=sql_scope(user)
    where='WHERE 1=1'+scope
    if product_id:where+=' AND r.product_id=%s';params.append(product_id)
    if max_rating:where+=' AND r.rating<=%s';params.append(max_rating)
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute(f'''SELECT r.id,r.product_id,p.name AS product_name,p.category,p.seller_id,r.customer_id,c.name AS customer_name,r.rating,r.content,r.created_at,s.status AS rag_status
                FROM reviews r JOIN products p ON p.id=r.product_id JOIN customers c ON c.id=r.customer_id
                LEFT JOIN rag_sync_state s ON s.source_type='REVIEW' AND s.source_id=r.id
                {where} ORDER BY r.created_at DESC LIMIT %s''',params+[limit]);rows=cur.fetchall()
            replies={}
            if rows:
                ids=[r['id'] for r in rows]
                cur.execute(f"SELECT id,review_id,content,status,created_at FROM review_replies WHERE review_id IN ({','.join(['%s']*len(ids))}) ORDER BY id",ids)
                for rp in cur.fetchall():
                    if user.role=='BUYER' and rp['status']!='PUBLISHED':continue
                    replies.setdefault(rp['review_id'],[]).append(rp)
    for r in rows:
        r['replies']=replies.get(r['id'],[])
        r['mine']=user.role=='BUYER' and r['customer_id']==user.customer_id
        if user.role!='ADMIN':r['customer_name']=mask_name(r['customer_name']);r.pop('customer_id')
    return rows

@router.post('/reviews')
async def create_review(data:ReviewIn,user:User=Depends(roles('BUYER'))):
    if not get_product(data.product_id):raise HTTPException(404,'상품 없음')
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM orders o JOIN order_items oi ON oi.order_id=o.id WHERE o.customer_id=%s AND oi.product_id=%s AND o.status='DELIVERED'",(user.customer_id,data.product_id))
            if not cur.fetchone()['n']:raise HTTPException(403,'배송 완료된 구매 상품만 후기를 작성할 수 있다')
            cur.execute('INSERT INTO reviews (customer_id,product_id,rating,content) VALUES (%s,%s,%s,%s)',(user.customer_id,data.product_id,data.rating,data.content));review_id=cur.lastrowid
    return {'id':review_id,'rag_status':await index_one('review',review_id)}

@router.post('/review-replies')
def save_review_reply(data:ReviewReplyIn,user:User=Depends(roles('ADMIN','SELLER'))):
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT r.id,p.seller_id FROM reviews r JOIN products p ON p.id=r.product_id WHERE r.id=%s',(data.review_id,));review=cur.fetchone()
            if not review:raise HTTPException(404,'후기 없음')
            if user.role=='SELLER' and review['seller_id']!=user.seller_id:raise HTTPException(403,'본인 상품 후기에만 답글을 작성할 수 있다')
            cur.execute('INSERT INTO review_replies (review_id,seller_id,author_user_id,content,status) VALUES (%s,%s,%s,%s,%s)',(data.review_id,review['seller_id'],user.id,data.content,data.status))
            return {'id':cur.lastrowid,'status':data.status}

# ---------------------------------------------------------------- 불만 처리

@router.patch('/complaints/{complaint_id}')
async def update_complaint(complaint_id:int,data:ComplaintUpdateIn,user:User=Depends(roles('ADMIN','SELLER'))):
    assert_complaint_scope(user,get_complaint(complaint_id))
    resolution=(data.resolution or '').strip() or None
    if data.status=='RESOLVED' and not resolution:raise HTTPException(400,'RESOLVED 처리 시 처리 결과(resolution)를 입력해야 한다. 유사 사례 RAG의 근거가 된다.')
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE complaints SET status=%s,resolution=%s,resolved_at=IF(%s='RESOLVED',COALESCE(resolved_at,NOW()),NULL) WHERE id=%s",(data.status,resolution,data.status,complaint_id))
    return {'id':complaint_id,'status':data.status,'rag_status':await index_one('complaint',complaint_id)}

# ---------------------------------------------------------------- RAG 색인 관리 (관리자)

@router.get('/rag/status')
def rag_status(user:User=Depends(roles('ADMIN'))):
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT index_status,COUNT(*) AS n FROM source_documents GROUP BY index_status');documents={r['index_status']:r['n'] for r in cur.fetchall()}
            cur.execute("SELECT source_type,source_id,error_message,indexed_at FROM rag_sync_state WHERE status='FAILED' ORDER BY indexed_at DESC LIMIT 10");failures=cur.fetchall()
    return {'embedding_model':embed_model(),'documents':documents,'sources':[status_summary('review'),status_summary('complaint')],'recent_failures':failures}

@router.post('/rag/sync')
async def rag_sync(data:SyncIn,user:User=Depends(roles('ADMIN'))):
    return {'results':[await sync_all(kind,data.force) for kind in data.targets]}

# ---------------------------------------------------------------- 통합 RAG 상담 (역할별 범위)

@router.post('/rag/ask')
async def rag_ask(data:RagAskIn,user:User=Depends(current_user)):
    if data.product_id:assert_product_scope(user,get_product(data.product_id))
    vector=await embed(data.question);hits=[]
    if 'document' in data.sources:hits+=search_documents(vector,4)
    if 'review' in data.sources:hits+=search_chunks('review',vector,{**review_scope(user),'product_id':data.product_id},6)
    if 'complaint' in data.sources:hits+=search_chunks('complaint',vector,{**complaint_scope(user),'product_id':data.product_id},5)
    hits=[h for h in hits if h['score']>0.2]
    if not hits:return {'answer':'검색된 근거가 없어 답변할 수 없다. 관리자에게 RAG 색인 상태(/rag/status) 확인을 요청한다.','sources':[]}
    prompt=(f"{ROLE_GUIDE[user.role]}\n질문: {data.question}\n검색된 근거:\n{context_block(hits)}\n\n"
            "근거에 있는 내용만 사용하고 인용한 근거를 [후기 ID]/[불만 ID]/[문서 ID] 형태로 표시하라. 후기는 개인 의견이므로 '일부 구매자는' 처럼 표현하라. 근거가 부족하면 확인 필요라고 말하라.")
    answer=await complete(prompt,data.provider)
    sources=public_hits(hits,user)
    save_report(user,'RAG_ASK',answer,data.provider,{'sources':sources},data.question,'product' if data.product_id else None,data.product_id)
    return {'answer':answer,'sources':sources}

# ---------------------------------------------------------------- 후기 RAG

@router.post('/rag/reviews/summary')
async def review_summary(data:ProductAiIn,user:User=Depends(current_user)):
    product=get_product(data.product_id);assert_product_scope(user,product)
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS reviews,ROUND(AVG(rating),2) AS avg_rating,SUM(rating>=4) AS positive,SUM(rating=3) AS neutral,SUM(rating<=2) AS negative FROM reviews WHERE product_id=%s',(data.product_id,));stats=cur.fetchone()
    if not stats['reviews']:return {'answer':'등록된 후기가 없어 요약할 수 없다.','stats':stats,'sources':[]}
    positive=search_chunks('review',await embed(f"{product['name']} 만족 장점 좋은 점 추천"),{'product_id':data.product_id,'min_rating':4},5)
    negative=search_chunks('review',await embed(f"{product['name']} 불만 단점 문제 고장 개선 필요"),{'product_id':data.product_id,'max_rating':3},5)
    complaints=[] if user.role=='BUYER' else search_chunks('complaint',await embed(f"{product['name']} 품질 배송 불만"),{'product_id':data.product_id},4)
    hits=positive+negative+complaints
    if not hits:return {'answer':'후기가 아직 벡터 색인되지 않았다. 관리자에게 RAG 동기화를 요청한다.','stats':stats,'sources':[]}
    tail=('4) 구매 전 확인할 점과 이런 분께 추천' if user.role=='BUYER' else '4) 판매자 개선 액션 (상품 상세페이지·품질·포장·CS 구분)\n5) 불만과 후기의 공통 원인')
    prompt=(f"{ROLE_GUIDE[user.role]}\n상품: {product['name']} ({product['category']}, {product['price']}원)\n후기 통계: {json.dumps(stats,ensure_ascii=False,default=str)}\n"
            f"긍정 후기 근거:\n{context_block(positive)}\n부정·보통 후기 근거:\n{context_block(negative)}\n"+(f"관련 불만 근거:\n{context_block(complaints)}\n" if complaints else '')+
            f"\n다음 형식으로 작성하라. 각 항목에 근거 ID를 표시하고, 해당 근거가 없는 항목은 추측하지 말고 '근거 없음'이라고 적는다.\n1) 한 줄 요약\n2) 장점\n3) 단점·주의점\n{tail}")
    answer=await complete(prompt,data.provider);sources=public_hits(hits,user)
    save_report(user,'REVIEW_SUMMARY',answer,data.provider,{'stats':stats,'sources':sources},None,'product',data.product_id)
    return {'answer':answer,'stats':stats,'product':product,'sources':sources}

@router.post('/rag/reviews/{review_id}/draft-reply')
async def review_reply_draft(review_id:int,data:ProviderIn,user:User=Depends(roles('ADMIN','SELLER'))):
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT r.id,r.rating,r.content,r.created_at,r.customer_id,r.product_id,p.name AS product_name,p.category,p.seller_id FROM reviews r JOIN products p ON p.id=r.product_id WHERE r.id=%s',(review_id,));review=cur.fetchone()
    if not review:raise HTTPException(404,'후기 없음')
    assert_product_scope(user,review)
    vector=await embed(source_text('review',review))
    cases=search_chunks('complaint',vector,{**review_scope(user),'has_resolution':True},3)
    docs=search_documents(vector,2)
    prompt=(f"{ROLE_GUIDE['SELLER']}\n고객 후기 [후기 {review_id}] {review['rating']}점: {review['content']}\n상품: {review['product_name']}\n"
            f"참고할 처리 사례·정책:\n{context_block(cases+docs)}\n\n"
            "쇼핑몰 후기 게시판에 올릴 판매자 답글을 3~5문장으로 작성하라. 긍정 후기는 감사와 사용 팁, 부정 후기는 사과·원인 확인·구체 조치 안내를 포함한다. "
            "근거에 없는 보상이나 약속은 쓰지 말고 필요한 경우 '고객센터로 문의 주시면 확인하겠습니다'로 안내한다. 고객 이름과 개인정보는 쓰지 않는다. 답글 본문만 출력한다.")
    answer=await complete(prompt,data.provider)
    return {'review_id':review_id,'draft':answer.strip(),'sources':public_hits(cases+docs,user)}

# ---------------------------------------------------------------- 불만 RAG

async def complaint_assist_core(complaint_id:int,provider:str,user:User):
    complaint=get_complaint(complaint_id);assert_complaint_scope(user,complaint)
    vector=await embed(source_text('complaint',complaint))
    cases=search_chunks('complaint',vector,{**complaint_scope(user),'has_resolution':True},4,exclude_id=complaint_id)
    reviews=search_chunks('review',vector,{'product_id':complaint['product_id']} if complaint['product_id'] else review_scope(user),3)
    docs=search_documents(vector,3)
    hits=cases+reviews+docs
    prompt=(f"{ROLE_GUIDE[user.role]}\n처리 대상 [불만 {complaint_id}] 분류: {complaint['category']} / 상태: {complaint['status']} / 상품: {complaint.get('product_name') or '미지정'} / 주문: {complaint.get('order_id') or '미지정'}\n내용: {complaint['content']}\n\n"
            f"유사 처리 사례(처리 결과 포함):\n{context_block(cases)}\n같은 상품 후기:\n{context_block(reviews)}\n정책·매뉴얼 문서:\n{context_block(docs)}\n\n"
            "다음 형식으로 작성하라. 근거 ID를 표시하고 근거에 없는 보상·환불 확정은 '담당자 확인 필요'로 적는다.\n"
            "### 상황 요약\n### 유사 사례 처리 방식\n### 권장 처리 절차 (체크리스트)\n### 고객 응대 초안\n(고객에게 보낼 정중한 답변 본문, 고객 이름 대신 '고객님')")
    answer=await complete(prompt,provider);sources=public_hits(hits,user)
    save_report(user,'COMPLAINT_ASSIST',answer,provider,{'sources':sources},None,'complaint',complaint_id)
    return {'complaint_id':complaint_id,'analysis':answer,'draft':split_draft(answer),'sources':sources}

@router.post('/rag/complaints/{complaint_id}/assist')
async def complaint_assist(complaint_id:int,data:ProviderIn,user:User=Depends(roles('ADMIN','SELLER'))):
    return await complaint_assist_core(complaint_id,data.provider,user)

# ---------------------------------------------------------------- 운영 인사이트 (관리자·판매자)

@router.post('/rag/insights')
async def insights(data:InsightIn,user:User=Depends(roles('ADMIN','SELLER'))):
    since=datetime.now()-timedelta(days=data.days)
    scope,params=sql_scope(user)
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT c.category,c.status,COUNT(*) AS n FROM complaints c LEFT JOIN products p ON p.id=c.product_id WHERE c.created_at>=%s{scope} GROUP BY c.category,c.status ORDER BY n DESC',[since,*params]);complaint_stats=cur.fetchall()
            cur.execute(f'''SELECT p.id,p.name,COUNT(r.id) AS reviews,ROUND(AVG(r.rating),2) AS avg_rating,SUM(r.rating<=2) AS negative
                FROM products p JOIN reviews r ON r.product_id=p.id WHERE r.created_at>=%s{scope} GROUP BY p.id,p.name ORDER BY avg_rating ASC LIMIT 10''',[since,*params]);review_stats=cur.fetchall()
    base={**review_scope(user),'since':since}
    hits,seen=[],set()
    for query in ('반복되는 품질 불량 고장 발열','배송 지연 파손 포장 문제','환불 교환 처리 지연 불만','상품 설명과 다름 사이즈 불일치'):
        vector=await embed(query)
        for h in search_chunks('review',vector,{**base,'max_rating':3},3)+search_chunks('complaint',vector,{**complaint_scope(user),'since':since},3):
            if (h['kind'],h['id']) not in seen and h['score']>0.2:seen.add((h['kind'],h['id']));hits.append(h)
    if not complaint_stats and not review_stats:return {'answer':f'최근 {data.days}일 동안 분석할 후기·불만이 없다.','stats':{},'sources':[]}
    stats={'complaints':complaint_stats,'reviews':review_stats}
    prompt=(f"{ROLE_GUIDE[user.role]}\n최근 {data.days}일 운영 통계: {json.dumps(stats,ensure_ascii=False,default=str)}\n검색된 부정 후기·불만 근거:\n{context_block(hits)}\n\n"
            "운영 리포트를 작성하라. 수치는 통계에 있는 값만 사용하고 근거 ID를 표시하라.\n1) 핵심 이슈 Top 3 (영향 범위·근거)\n2) 상품별 위험 신호\n3) 이번 주 즉시 조치\n4) 정책·매뉴얼·상세페이지 개선 제안\n5) 추적할 지표")
    answer=await complete(prompt,data.provider);sources=public_hits(hits,user)
    save_report(user,'INSIGHT',answer,data.provider,{'stats':stats,'sources':sources},f'최근 {data.days}일')
    return {'answer':answer,'stats':stats,'sources':sources}

# ---------------------------------------------------------------- 대시보드·이력

@router.get('/dashboard')
def dashboard(user:User=Depends(current_user)):
    with mysql() as conn:
        with conn.cursor() as cur:
            if user.role=='BUYER':
                cid=user.customer_id
                cur.execute('SELECT COUNT(*) AS n FROM orders WHERE customer_id=%s',(cid,));orders_n=cur.fetchone()['n']
                cur.execute('SELECT COUNT(*) AS n FROM reviews WHERE customer_id=%s',(cid,));reviews_n=cur.fetchone()['n']
                cur.execute('SELECT status,COUNT(*) AS n FROM complaints WHERE customer_id=%s GROUP BY status',(cid,));cs=cur.fetchall()
                cur.execute('''SELECT DISTINCT p.id,p.name FROM orders o JOIN order_items oi ON oi.order_id=o.id JOIN products p ON p.id=oi.product_id
                    WHERE o.customer_id=%s AND o.status='DELIVERED' AND NOT EXISTS(SELECT 1 FROM reviews r WHERE r.customer_id=o.customer_id AND r.product_id=p.id)''',(cid,));reviewable=cur.fetchall()
                open_n=sum(r['n'] for r in cs if r['status']!='RESOLVED')
                return {'role':user.role,'cards':[{'label':'주문','value':orders_n},{'label':'작성한 후기','value':reviews_n},{'label':'처리 중 문의','value':open_n},{'label':'후기 작성 가능','value':len(reviewable)}],'complaint_status':cs,'reviewable':reviewable}
            scope,params=sql_scope(user)
            cur.execute(f'SELECT c.status,COUNT(*) AS n FROM complaints c LEFT JOIN products p ON p.id=c.product_id WHERE 1=1{scope} GROUP BY c.status',params);cs=cur.fetchall()
            cur.execute(f'SELECT c.category,COUNT(*) AS n FROM complaints c LEFT JOIN products p ON p.id=c.product_id WHERE 1=1{scope} GROUP BY c.category ORDER BY n DESC',params);cc=cur.fetchall()
            cur.execute(f'''SELECT p.id,p.name,COUNT(r.id) AS reviews,ROUND(AVG(r.rating),2) AS avg_rating,COALESCE(SUM(r.rating<=2),0) AS negative,
                (SELECT COUNT(*) FROM complaints c WHERE c.product_id=p.id AND c.status<>'RESOLVED') AS open_complaints
                FROM products p LEFT JOIN reviews r ON r.product_id=p.id WHERE p.active=1{scope} GROUP BY p.id,p.name ORDER BY negative DESC,open_complaints DESC,p.id''',params);products_=cur.fetchall()
            cur.execute(f"SELECT COUNT(*) AS n FROM complaints c LEFT JOIN products p ON p.id=c.product_id WHERE c.status<>'RESOLVED' AND c.created_at<DATE_SUB(NOW(),INTERVAL 3 DAY){scope}",params);overdue=cur.fetchone()['n']
            cur.execute(f'SELECT COUNT(*) AS n FROM reviews r JOIN products p ON p.id=r.product_id WHERE r.rating<=2 AND NOT EXISTS(SELECT 1 FROM review_replies rr WHERE rr.review_id=r.id){scope}',params);unanswered=cur.fetchone()['n']
    open_n=sum(r['n'] for r in cs if r['status']!='RESOLVED')
    total_reviews=sum(int(p['reviews']) for p in products_)
    avg=round(sum(float(p['avg_rating'] or 0)*int(p['reviews']) for p in products_)/total_reviews,2) if total_reviews else None
    return {'role':user.role,'cards':[{'label':'미처리 불만','value':open_n},{'label':'3일 초과 미처리','value':overdue},{'label':'평균 평점','value':avg},{'label':'미답변 부정 후기','value':unanswered}],
            'complaint_status':cs,'complaint_category':cc,'products':products_}

@router.get('/ai-reports')
def ai_reports(limit:int=Query(30,ge=1,le=100),user:User=Depends(current_user)):
    where,params=('',[]) if user.role=='ADMIN' else ('WHERE a.user_id=%s',[user.id])
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT a.id,a.report_type,a.target_type,a.target_id,a.question,a.answer,a.provider,a.created_at,u.display_name FROM ai_reports a LEFT JOIN app_users u ON u.id=a.user_id {where} ORDER BY a.id DESC LIMIT %s',params+[limit])
            return cur.fetchall()
