from dataclasses import dataclass
from fastapi import Depends, Header, HTTPException
from .db import mysql

# 교육용 데모 인증: X-User-Id 헤더로 app_users를 조회하고 역할·범위는 서버 DB 값만 신뢰한다.
# 운영 환경에서는 JWT/세션 검증 결과의 사용자 ID로 같은 조회를 수행하도록 교체한다.

@dataclass
class User:
    id:int
    username:str
    display_name:str
    role:str
    customer_id:int|None
    seller_id:int|None

def current_user(x_user_id:int|None=Header(default=None)) -> User:
    if not x_user_id:raise HTTPException(401,'X-User-Id 헤더가 필요하다. 프론트에서 사용자를 선택한다.')
    with mysql() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT id,username,display_name,role,customer_id,seller_id FROM app_users WHERE id=%s AND active=1',(x_user_id,));row=cur.fetchone()
    if not row:raise HTTPException(401,'등록되지 않았거나 비활성화된 사용자')
    return User(**row)

def roles(*allowed:str):
    def check(user:User=Depends(current_user)) -> User:
        if user.role not in allowed:raise HTTPException(403,f'{"/".join(allowed)} 권한이 필요하다')
        return user
    return check

def mask_name(name:str|None) -> str:
    return (name[0]+'*'*(len(name)-1)) if name else '익명'

def assert_product_scope(user:User,product:dict|None):
    if not product:raise HTTPException(404,'상품 없음')
    if user.role=='SELLER' and product.get('seller_id')!=user.seller_id:raise HTTPException(403,'본인 판매 상품만 조회할 수 있다')

def assert_complaint_scope(user:User,complaint:dict|None):
    if not complaint:raise HTTPException(404,'불만 없음')
    if user.role=='SELLER' and complaint.get('seller_id')!=user.seller_id:raise HTTPException(403,'본인 판매 상품의 불만만 처리할 수 있다')
    if user.role=='BUYER' and complaint.get('customer_id')!=user.customer_id:raise HTTPException(403,'본인 불만만 조회할 수 있다')
