import io
import base64
import httpx
import json
import os
from datetime import date
from pathlib import Path
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Literal
from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from xml.sax.saxutils import escape
from .db import mysql, pg
from .ai import embed, complete
from .auth import User, current_user, roles, mask_name, assert_complaint_scope
from .rag import chunks, search_documents, search_chunks, index_one, public_hits
from .routes import router, complaint_assist_core, get_complaint

app=FastAPI(title='쇼핑몰 MySQL RAG 고객 응대 API')
app.add_middleware(CORSMiddleware,allow_origins=os.getenv('CORS_ORIGINS','http://localhost:5173').split(','),allow_methods=['*'],allow_headers=['*'])
app.include_router(router)

class ComplaintIn(BaseModel):
    customer_id:int|None=None
    order_id:int|None=None
    product_id:int|None=None
    category:str=Field(min_length=1,max_length=50)
    content:str=Field(min_length=5,max_length=4000)

class ReplyIn(BaseModel):
    complaint_id:int
    content:str=Field(min_length=3,max_length=5000)
    manual_document_id:int|None=None

class ReplyStatusIn(BaseModel):
    status:Literal['DRAFT','APPROVED','SENT']

class AskIn(BaseModel):
    question:str=Field(min_length=2,max_length=2000)
    customer_id:int|None=None
    provider:Literal['local','gemini']='local'

class RecommendationIn(BaseModel):
    customer_id:int|None=None
    provider:Literal['local','gemini']='local'

class DraftIn(BaseModel):
    complaint_id:int
    provider:Literal['local','gemini']='local'


async def index_document(title,source_type,content,meta=None):
    pieces=chunks(content)
    if not pieces:raise HTTPException(400,'추출할 텍스트가 없다. 이미지 PDF라면 OCR 후 업로드해야 한다.')
    vectors=[await embed(piece) for piece in pieces]
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('INSERT INTO source_documents (title,source_type,content,metadata_json) VALUES (%s,%s,%s,%s)',(title,source_type,content,json.dumps(meta or {},ensure_ascii=False)))
            doc_id=cur.lastrowid
            for i,piece in enumerate(pieces):cur.execute('INSERT INTO document_chunks (document_id,chunk_no,content) VALUES (%s,%s,%s)',(doc_id,i,piece))
    try:
        with pg() as conn:
            with conn.cursor() as cur:
                for i,(piece,vector) in enumerate(zip(pieces,vectors)):
                    cur.execute('INSERT INTO public.rag_chunks (mysql_document_id,chunk_no,source_title,source_type,content,embedding) VALUES (%s,%s,%s,%s,%s,%s::real[]) ON CONFLICT (mysql_document_id,chunk_no) DO UPDATE SET source_title=EXCLUDED.source_title,source_type=EXCLUDED.source_type,content=EXCLUDED.content,embedding=EXCLUDED.embedding',(doc_id,i,title,source_type,piece,vector))
    except Exception as exc:
        with mysql() as conn:
            with conn.cursor() as cur:cur.execute('UPDATE source_documents SET index_status=%s WHERE id=%s',('FAILED',doc_id))
        raise HTTPException(503,f'MySQL 문서 {doc_id} 저장됨, 벡터 색인 실패. 재색인 필요: {exc}') from exc
    with mysql() as conn:
        with conn.cursor() as cur:cur.execute('UPDATE source_documents SET index_status=%s WHERE id=%s',('READY',doc_id))
    return {'document_id':doc_id,'chunks':len(pieces),'title':title}

@app.get('/health')
def health():
    return {'status':'ok','model':os.getenv('OLLAMA_CHAT_MODEL','qwen2.5:3b'),'embedding':os.getenv('OLLAMA_EMBED_MODEL','nomic-embed-text'),'vector_storage':'PostgreSQL REAL[768] (rag_chunks, rag_review_chunks, rag_complaint_chunks)','gemini_configured':bool(os.getenv('GEMINI_API_KEY'))}

@app.get('/customers')
def customers(user:User=Depends(roles('ADMIN'))):
    with mysql() as conn:
        with conn.cursor() as cur:cur.execute('SELECT id,name FROM customers ORDER BY id');return cur.fetchall()

@app.get('/complaints')
def complaints(status:Literal['OPEN','IN_PROGRESS','RESOLVED']|None=None,user:User=Depends(current_user)):
    where,params='WHERE 1=1',[]
    if user.role=='SELLER':where+=' AND p.seller_id=%s';params.append(user.seller_id)
    if user.role=='BUYER':where+=' AND c.customer_id=%s';params.append(user.customer_id)
    if status:where+=' AND c.status=%s';params.append(status)
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute(f'''SELECT c.id,c.customer_id,u.name AS customer_name,c.order_id,c.product_id,p.name AS product_name,c.category,c.content,c.status,c.resolution,c.resolved_at,c.created_at,s.status AS rag_status
                FROM complaints c JOIN customers u ON u.id=c.customer_id LEFT JOIN products p ON p.id=c.product_id
                LEFT JOIN rag_sync_state s ON s.source_type='COMPLAINT' AND s.source_id=c.id
                {where} ORDER BY c.id DESC LIMIT 100''',params)
            rows=cur.fetchall()
    if user.role=='SELLER':
        for r in rows:r['customer_name']=mask_name(r['customer_name']);r.pop('customer_id')
    return rows

@app.post('/complaints')
async def create_complaint(data:ComplaintIn,user:User=Depends(roles('ADMIN','BUYER'))):
    customer_id=user.customer_id if user.role=='BUYER' else data.customer_id
    if not customer_id:raise HTTPException(400,'관리자 대리 접수 시 customer_id가 필요하다')
    product_id=data.product_id
    with mysql() as conn:
        with conn.cursor() as cur:
            if data.order_id:
                cur.execute('SELECT oi.product_id FROM orders o JOIN order_items oi ON oi.order_id=o.id WHERE o.id=%s AND o.customer_id=%s',(data.order_id,customer_id));items=[r['product_id'] for r in cur.fetchall()]
                if not items:raise HTTPException(400,'해당 고객의 주문이 아니다')
                if product_id and product_id not in items:raise HTTPException(400,'주문에 포함되지 않은 상품이다')
                if not product_id and len(items)==1:product_id=items[0]
            try:cur.execute('INSERT INTO complaints (customer_id,order_id,product_id,category,content) VALUES (%s,%s,%s,%s,%s)',(customer_id,data.order_id,product_id,data.category,data.content))
            except Exception as exc:raise HTTPException(400,f'고객·주문·상품 ID 확인 필요: {exc}') from exc
            complaint_id=cur.lastrowid
    # 접수 즉시 불만 RAG에 색인 (실패해도 접수는 유지, /rag/sync로 재시도)
    return {'id':complaint_id,'status':'OPEN','rag_status':await index_one('complaint',complaint_id)}

@app.get('/manual.pdf')
def manual_pdf(user:User=Depends(roles('ADMIN'))):
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT category,content,resolution FROM complaints ORDER BY id DESC');records=cur.fetchall()
    if not records:raise HTTPException(404,'불만 데이터가 없다')
    font_path=os.getenv('KOREAN_FONT_PATH','')
    if not font_path or not Path(font_path).is_file():raise HTTPException(503,'한글 PDF용 KOREAN_FONT_PATH에 NanumGothic.ttf 등 실제 TTF 경로를 설정해야 한다')
    try:pdfmetrics.registerFont(TTFont('Korean',font_path))
    except Exception as exc:raise HTTPException(503,f'폰트 로딩 실패: {exc}') from exc
    grouped={}
    for row in records:grouped.setdefault(row['category'],[]).append(row)
    buf=io.BytesIO();doc=SimpleDocTemplate(buf)
    style=ParagraphStyle('Korean',fontName='Korean',fontSize=10,leading=16,spaceAfter=10,alignment=TA_LEFT)
    story=[Paragraph('고객 불만 대응 매뉴얼 초안',style),Paragraph('생성일 '+date.today().isoformat()+' / 담당자 검토 후 고객에게 제공',style)]
    for category,items in grouped.items():
        story.append(Paragraph('분류: '+escape(category),style))
        for complaint in items:
            story.append(Paragraph('접수 내용: '+escape(complaint['content'][:500]),style))
            if complaint.get('resolution'):story.append(Paragraph('처리 사례: '+escape(complaint['resolution'][:500]),style))
            else:story.append(Paragraph('처리 기준: 주문·결제·배송 내역을 확인하고 관련 정책에 따라 담당자가 답변을 승인한다.',style))
    doc.build(story);buf.seek(0)
    return StreamingResponse(buf,media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="complaint_manual.pdf"'})

@app.post('/documents/pdf')
async def import_pdf(file:UploadFile=File(...),user:User=Depends(roles('ADMIN'))):
    if not (file.filename or '').lower().endswith('.pdf'):raise HTTPException(400,'PDF만 허용')
    data=await file.read(10_000_001)
    if len(data)>10_000_000:raise HTTPException(413,'10MB 초과')
    try:text='\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(data)).pages)
    except Exception as exc:raise HTTPException(400,f'PDF 추출 오류: {exc}') from exc
    return await index_document(Path(file.filename).name,'PDF',text)

@app.post('/documents/image')
async def import_image(file:UploadFile=File(...),user:User=Depends(roles('ADMIN'))):
    if file.content_type not in ('image/png','image/jpeg','image/webp'):
        raise HTTPException(400,'PNG, JPEG, WebP 이미지 파일만 허용')
    data=await file.read(5_000_001)
    if len(data)>5_000_000:raise HTTPException(413,'5MB 초과')
    model=os.getenv('OLLAMA_VISION_MODEL','').strip()
    if not model:raise HTTPException(503,'이미지 분석용 OLLAMA_VISION_MODEL을 .env에 설정하고 해당 모델을 받아야 한다')
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response=await client.post(os.getenv('OLLAMA_URL','http://127.0.0.1:11434').rstrip('/')+'/api/chat',json={'model':model,'stream':False,'messages':[{'role':'user','content':'이미지에서 읽을 수 있는 글자를 가능한 정확히 전사하고, 글자와 시각적 특징을 구분하여 한국어로 설명하라. 불확실한 부분은 명시하라.','images':[base64.b64encode(data).decode()]}]})
            response.raise_for_status(); description=response.json()['message']['content']
    except (httpx.HTTPError,KeyError) as exc:raise HTTPException(503,f'이미지 분석 실패: {exc}') from exc
    return await index_document(Path(file.filename or 'image').name,'IMAGE',description,{'content_type':file.content_type,'vision_model':model})

@app.post('/documents/json')
async def import_json(file:UploadFile=File(...),user:User=Depends(roles('ADMIN'))):
    data=await file.read(2_000_001)
    if len(data)>2_000_000:raise HTTPException(413,'2MB 초과')
    try:payload=json.loads(data)
    except Exception as exc:raise HTTPException(400,f'JSON 형식 오류: {exc}') from exc
    records=payload if isinstance(payload,list) else payload.get('items',[]) if isinstance(payload,dict) else []
    if not isinstance(records,list) or len(records)>100:raise HTTPException(400,'JSON 배열 또는 items 배열 100건 이하')
    inserted=[]
    with mysql() as conn:
        with conn.cursor() as cur:
            for item in records:
                if not isinstance(item,dict):continue
                source_id=str(item.get('id',''))[:100];title=str(item.get('title',''))[:200];body=str(item.get('content',''))[:5000]
                if not source_id or not title or not body:continue
                cur.execute('INSERT INTO external_articles (source_id,title,content,raw_json) VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE title=VALUES(title),content=VALUES(content),raw_json=VALUES(raw_json)',(source_id,title,body,json.dumps(item,ensure_ascii=False)))
                inserted.append((source_id,title,body))
    indexed=[]
    for source_id,title,body in inserted:indexed.append(await index_document(title,'JSON',body,{'source_id':source_id}))
    return {'imported':len(inserted),'indexed':indexed}

@app.post('/ask')
async def ask(data:AskIn,user:User=Depends(current_user)):
    # 기존 문서+불만 상담 API (호환 유지). 후기·불만 벡터 검색을 포함한 신규 화면은 /rag/ask 사용.
    if user.role=='BUYER':data.customer_id=user.customer_id
    vector=await embed(data.question)
    with mysql() as conn:
        with conn.cursor() as cur:
            if user.role=='SELLER':
                cur.execute('SELECT c.id,c.category,c.content,c.status FROM complaints c JOIN products p ON p.id=c.product_id WHERE p.seller_id=%s ORDER BY c.id DESC LIMIT 5',(user.seller_id,));rows=cur.fetchall()
            elif data.customer_id:
                cur.execute('SELECT id,category,content,status FROM complaints WHERE customer_id=%s ORDER BY id DESC LIMIT 5',(data.customer_id,));rows=cur.fetchall()
            else:
                cur.execute('SELECT id,category,content,status FROM complaints ORDER BY id DESC LIMIT 5');rows=cur.fetchall()
    hits=search_documents(vector,4)
    sources=[{k:h[k] for k in ('document_id','title','score','excerpt')} for h in hits]
    context='\n'.join(f"[문서 {h['id']}: {h['title']}] {h['content']}" for h in hits)
    prompt=f'질문: {data.question}\nMySQL 불만 데이터: {json.dumps(rows,ensure_ascii=False,default=str)}\n검색된 매뉴얼: {context}\n검색된 근거만으로 답하고 문서 ID와 불만 ID를 명시하라. 근거가 부족하면 확인 필요라고 말하라.'
    answer=await complete(prompt,data.provider)
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('INSERT INTO answer_logs (customer_id,question,answer,source_json) VALUES (%s,%s,%s,%s)',(data.customer_id,data.question,answer,json.dumps(sources,ensure_ascii=False)))
    return {'answer':answer,'sources':sources,'complaints':rows}

@app.post('/complaints/draft-reply')
async def draft_reply(data:DraftIn,user:User=Depends(roles('ADMIN','SELLER'))):
    # 유사 처리 사례(불만 RAG) + 같은 상품 후기 + 매뉴얼 문서를 근거로 초안 생성
    result=await complaint_assist_core(data.complaint_id,data.provider,user)
    return {'complaint_id':data.complaint_id,'draft':result['draft'],'analysis':result['analysis'],'sources':result['sources'],'note':'담당자 검토 후 replies에 저장'}

@app.get('/complaints/{complaint_id}/replies')
def list_replies(complaint_id:int,user:User=Depends(current_user)):
    assert_complaint_scope(user,get_complaint(complaint_id))
    only_sent=" AND status='SENT'" if user.role=='BUYER' else ''
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT id,content,status,created_at FROM complaint_replies WHERE complaint_id=%s{only_sent} ORDER BY id',(complaint_id,));return cur.fetchall()

@app.post('/replies')
def save_reply(data:ReplyIn,user:User=Depends(roles('ADMIN','SELLER'))):
    assert_complaint_scope(user,get_complaint(data.complaint_id))
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('INSERT INTO complaint_replies (complaint_id,manual_document_id,author_user_id,content,status) VALUES (%s,%s,%s,%s,%s)',(data.complaint_id,data.manual_document_id,user.id,data.content,'DRAFT'))
            return {'id':cur.lastrowid,'status':'DRAFT'}

@app.patch('/replies/{reply_id}')
def update_reply(reply_id:int,data:ReplyStatusIn,user:User=Depends(roles('ADMIN','SELLER'))):
    # DRAFT → APPROVED → SENT. 실제 메일·알림톡 발송은 운영 시스템에서 SENT 전환 시 연동한다.
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT complaint_id FROM complaint_replies WHERE id=%s',(reply_id,));row=cur.fetchone()
    if not row:raise HTTPException(404,'답변 없음')
    assert_complaint_scope(user,get_complaint(row['complaint_id']))
    with mysql() as conn:
        with conn.cursor() as cur:cur.execute('UPDATE complaint_replies SET status=%s WHERE id=%s',(data.status,reply_id))
    return {'id':reply_id,'status':data.status}

@app.post('/recommendations')
async def recommend(data:RecommendationIn,user:User=Depends(roles('ADMIN','BUYER'))):
    if user.role=='BUYER':data.customer_id=user.customer_id
    if not data.customer_id:raise HTTPException(400,'customer_id 필요')
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT p.category,COUNT(*) AS purchases,SUM(oi.quantity) AS quantity FROM orders o JOIN order_items oi ON oi.order_id=o.id JOIN products p ON p.id=oi.product_id WHERE o.customer_id=%s AND o.ordered_at>=DATE_SUB(NOW(),INTERVAL 3 MONTH) AND o.status IN (\'PAID\',\'DELIVERED\') GROUP BY p.category ORDER BY quantity DESC',(data.customer_id,));purchases=cur.fetchall()
            cur.execute('SELECT r.product_id,p.category,r.rating,r.content FROM reviews r JOIN products p ON p.id=r.product_id WHERE r.customer_id=%s ORDER BY r.created_at DESC LIMIT 20',(data.customer_id,));reviews=cur.fetchall()
            cur.execute('SELECT id,name,category,price FROM products WHERE active=1 ORDER BY id LIMIT 100');catalog=cur.fetchall()
            cur.execute("SELECT DISTINCT oi.product_id FROM orders o JOIN order_items oi ON oi.order_id=o.id WHERE o.customer_id=%s AND o.status IN ('PAID','DELIVERED')",(data.customer_id,));purchased=[r['product_id'] for r in cur.fetchall()]
    excluded={int(r['product_id']) for r in reviews if int(r['rating'])<=2}
    catalog=[p for p in catalog if int(p['id']) not in excluded]
    if not purchases and not reviews:return {'answer':'최근 3개월 구매 또는 후기 데이터가 없어 추천 근거를 확인할 수 없다.','purchases':[],'reviews':[],'products':[],'peer_reviews':[]}
    # 후기 RAG: 고객의 긍정 후기(없으면 선호 카테고리)와 유사한 다른 구매자의 긍정 후기를 추천 근거로 추가
    peer_reviews=[]
    liked=' '.join(r['content'] for r in reviews if int(r['rating'])>=4) or ' '.join(p['category'] for p in purchases)
    if liked:
        try:
            catalog_ids={int(p['id']) for p in catalog}
            peer_reviews=[h for h in search_chunks('review',await embed(liked),{'min_rating':4,'exclude_customer':data.customer_id},8) if int(h['product_id']) in catalog_ids][:5]
        except HTTPException:peer_reviews=[]
    evidence={'purchases':purchases,'purchased_product_ids':purchased,'reviews':reviews,'catalog':catalog,'peer_reviews':[{'review_id':h['id'],'product_id':h['product_id'],'rating':h['rating'],'content':h['content']} for h in peer_reviews]}
    prompt=('구매 이력과 후기 텍스트에 근거하여 선호 카테고리와 추천 상품 ID를 최대 3개 제시하라. 부정 후기 상품은 추천하지 말라. 이미 구매한 상품(purchased_product_ids)보다 아직 구매하지 않은 상품을 우선한다. 가격은 주어진 값만 사용하라. '
            '다른 구매자 후기(peer_reviews)를 추천 이유로 인용할 때는 [후기 ID]를 표시하라.\n'+json.dumps(evidence,ensure_ascii=False,default=str))
    answer=await complete(prompt,data.provider)
    with mysql() as conn:
        with conn.cursor() as cur:cur.execute('INSERT INTO recommendation_logs (customer_id,answer,evidence_json) VALUES (%s,%s,%s)',(data.customer_id,answer,json.dumps({'purchases':purchases,'reviews':reviews,'peer_reviews':evidence['peer_reviews']},ensure_ascii=False,default=str)))
    return {'answer':answer,'purchases':purchases,'reviews':reviews,'products':catalog,'peer_reviews':public_hits(peer_reviews,user)}
