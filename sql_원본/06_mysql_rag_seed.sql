-- MySQL 8.0 / 05_mysql_rag_extend.sql 실행 후 적용한다. 여러 번 실행해도 중복되지 않는다.
-- 교육용 가명 데이터이며 실제 고객·판매자 정보가 아니다.
-- 화면에서 직접 등록한 주문·후기·불만과 ID가 겹치지 않도록 추가 시드는 101번부터 사용한다.
USE mysqlragdb0;

-- 판매자
INSERT INTO sellers (id,name,email) VALUES
 (1,'스마트전자','seller1@example.invalid'),
 (2,'리빙하우스','seller2@example.invalid'),
 (3,'액티브스포츠','seller3@example.invalid')
ON DUPLICATE KEY UPDATE name=VALUES(name);

-- 고객 추가
INSERT INTO customers (id,name,email) VALUES
 (4,'최고객','customer4@example.invalid'),
 (5,'정고객','customer5@example.invalid')
ON DUPLICATE KEY UPDATE name=VALUES(name);

-- 상품 추가 및 판매자 연결
INSERT INTO products (id,name,category,price) VALUES
 (7,'노이즈캔슬링 헤드폰','전자기기',129000),
 (8,'스마트 워치','전자기기',189000),
 (9,'밀폐 유리 용기 세트','생활용품',32000),
 (10,'폼롤러','운동용품',22000)
ON DUPLICATE KEY UPDATE name=VALUES(name),price=VALUES(price);
UPDATE products SET seller_id=1 WHERE id IN (1,2,6,7,8);
UPDATE products SET seller_id=2 WHERE id IN (3,4,9);
UPDATE products SET seller_id=3 WHERE id IN (5,10);

-- 서비스 사용자 (관리자 1, 판매자 3, 구매자 5)
INSERT INTO app_users (id,username,display_name,role,customer_id,seller_id) VALUES
 (1,'admin','운영 관리자','ADMIN',NULL,NULL),
 (2,'seller_smart','스마트전자 판매자','SELLER',NULL,1),
 (3,'seller_living','리빙하우스 판매자','SELLER',NULL,2),
 (4,'seller_active','액티브스포츠 판매자','SELLER',NULL,3),
 (5,'buyer_kim','김고객','BUYER',1,NULL),
 (6,'buyer_lee','이고객','BUYER',2,NULL),
 (7,'buyer_park','박고객','BUYER',3,NULL),
 (8,'buyer_choi','최고객','BUYER',4,NULL),
 (9,'buyer_jung','정고객','BUYER',5,NULL)
ON DUPLICATE KEY UPDATE display_name=VALUES(display_name),role=VALUES(role),customer_id=VALUES(customer_id),seller_id=VALUES(seller_id);

-- 주문 추가 (후기는 배송 완료 주문 기준의 구매 확인 후기)
INSERT INTO orders (id,customer_id,ordered_at,status) VALUES
 (105,2,DATE_SUB(NOW(),INTERVAL 40 DAY),'DELIVERED'),
 (106,3,DATE_SUB(NOW(),INTERVAL 20 DAY),'DELIVERED'),
 (107,3,DATE_SUB(NOW(),INTERVAL 15 DAY),'DELIVERED'),
 (108,4,DATE_SUB(NOW(),INTERVAL 25 DAY),'DELIVERED'),
 (109,4,DATE_SUB(NOW(),INTERVAL 6 DAY),'DELIVERED'),
 (110,5,DATE_SUB(NOW(),INTERVAL 30 DAY),'DELIVERED'),
 (111,5,DATE_SUB(NOW(),INTERVAL 4 DAY),'DELIVERED'),
 (112,2,DATE_SUB(NOW(),INTERVAL 18 DAY),'DELIVERED'),
 (113,1,DATE_SUB(NOW(),INTERVAL 50 DAY),'DELIVERED'),
 (114,4,DATE_SUB(NOW(),INTERVAL 5 DAY),'PAID'),
 (115,5,DATE_SUB(NOW(),INTERVAL 60 DAY),'REFUNDED')
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO order_items (id,order_id,product_id,quantity,unit_price) VALUES
 (105,105,1,1,59000),(106,105,4,1,35000),
 (107,106,2,1,79000),
 (108,107,6,1,39000),(109,107,10,1,22000),
 (110,108,7,1,129000),
 (111,109,3,1,19000),(112,109,9,1,32000),
 (113,110,5,1,28000),(114,110,10,1,22000),
 (115,111,8,1,189000),
 (116,112,6,1,39000),
 (117,113,4,1,35000),
 (118,114,2,1,79000),
 (119,115,1,1,59000)
ON DUPLICATE KEY UPDATE id=id;

-- 후기 추가
INSERT INTO reviews (id,customer_id,product_id,rating,content,created_at) VALUES
 (104,2,1,4,'통화 품질이 깔끔하고 가볍습니다. 다만 충전 케이스 힌지가 약간 헐거워요.',DATE_SUB(NOW(),INTERVAL 35 DAY)),
 (105,2,4,5,'밝기 단계가 세밀하고 눈부심이 적어 야간 작업용으로 좋습니다.',DATE_SUB(NOW(),INTERVAL 36 DAY)),
 (106,3,2,3,'음량은 충분하지만 저음이 약하고 블루투스 연결이 가끔 끊깁니다.',DATE_SUB(NOW(),INTERVAL 17 DAY)),
 (107,3,6,1,'완충까지 5시간 이상 걸리고 사용 중 뜨거워집니다. 발열이 걱정됩니다.',DATE_SUB(NOW(),INTERVAL 12 DAY)),
 (108,3,10,5,'단단해서 근막 이완에 효과적이고 크기도 적당합니다.',DATE_SUB(NOW(),INTERVAL 12 DAY)),
 (109,4,7,5,'노이즈캔슬링 성능이 뛰어나 지하철에서도 조용합니다. 배터리도 오래갑니다.',DATE_SUB(NOW(),INTERVAL 20 DAY)),
 (110,4,3,4,'보온은 6시간 정도 유지됩니다. 뚜껑 패킹 세척이 조금 번거롭습니다.',DATE_SUB(NOW(),INTERVAL 4 DAY)),
 (111,4,9,2,'배송 중 유리 용기 하나가 깨져서 왔습니다. 포장 완충재가 부족했습니다.',DATE_SUB(NOW(),INTERVAL 4 DAY)),
 (112,5,5,4,'미끄럼 방지는 좋은데 처음에 고무 냄새가 강했습니다. 며칠 환기하니 괜찮아요.',DATE_SUB(NOW(),INTERVAL 26 DAY)),
 (113,5,10,3,'표면이 딱딱해서 초보자에게는 통증이 있습니다. 부드러운 버전이 있으면 좋겠어요.',DATE_SUB(NOW(),INTERVAL 26 DAY)),
 (114,5,8,4,'심박 측정이 정확하고 디자인이 좋습니다. 배터리는 이틀 정도 갑니다.',DATE_SUB(NOW(),INTERVAL 2 DAY)),
 (115,2,6,2,'케이블 단자가 헐거워 충전이 자주 끊깁니다. 충전 속도도 광고보다 느립니다.',DATE_SUB(NOW(),INTERVAL 14 DAY)),
 (116,1,4,5,'각도 조절이 자유롭고 USB 포트가 있어 편리합니다.',DATE_SUB(NOW(),INTERVAL 45 DAY)),
 (117,3,5,5,'두께가 적당하고 무릎이 아프지 않습니다. 휴대용 스트랩이 유용해요.',DATE_SUB(NOW(),INTERVAL 100 DAY))
ON DUPLICATE KEY UPDATE id=id;

-- 기존 불만 1~3에 대상 상품 연결
UPDATE complaints SET product_id=1 WHERE id=1 AND product_id IS NULL;
UPDATE complaints SET product_id=6 WHERE id=2 AND product_id IS NULL;
UPDATE complaints SET product_id=3 WHERE id=3 AND product_id IS NULL;

-- 불만 추가 (RESOLVED 건의 resolution이 유사 사례 검색의 처리 근거가 된다)
INSERT INTO complaints (id,customer_id,order_id,product_id,category,content,status,resolution,resolved_at,created_at) VALUES
 (104,4,109,9,'배송파손','유리 용기 세트 중 1개가 깨진 상태로 도착했습니다. 사진 첨부 가능합니다.','RESOLVED','파손 사진 확인 후 동일 상품 1개 무상 재발송. 택배사 파손 접수 및 포장 완충재 2중 적용 기준으로 변경.',DATE_SUB(NOW(),INTERVAL 2 DAY),DATE_SUB(NOW(),INTERVAL 4 DAY)),
 (105,3,107,6,'품질','충전기가 사용 중 뜨거워지고 완충까지 너무 오래 걸립니다. 안전한지 확인 부탁드립니다.','RESOLVED','발열 기준 초과 여부 확인을 위해 회수 검사 진행. 불량 판정되어 전액 환불 처리. 동일 로트 제품 품질 점검 요청.',DATE_SUB(NOW(),INTERVAL 7 DAY),DATE_SUB(NOW(),INTERVAL 11 DAY)),
 (106,2,112,6,'품질','충전 케이블 단자가 헐거워 충전이 자주 끊깁니다.','IN_PROGRESS',NULL,NULL,DATE_SUB(NOW(),INTERVAL 13 DAY)),
 (107,3,106,2,'품질','블루투스 스피커 연결이 자주 끊깁니다.','RESOLVED','펌웨어 최신 버전 업데이트 방법 안내 후 증상 해소. 해소되지 않으면 교환 가능함을 안내.',DATE_SUB(NOW(),INTERVAL 14 DAY),DATE_SUB(NOW(),INTERVAL 16 DAY)),
 (108,5,115,1,'환불','이어폰 한쪽 소리가 작아서 환불 요청했는데 환불 금액이 아직 입금되지 않았습니다.','RESOLVED','카드사 환불 처리 기간 3~5영업일 안내 및 카드 취소 승인번호 전달. 이후 입금 확인.',DATE_SUB(NOW(),INTERVAL 50 DAY),DATE_SUB(NOW(),INTERVAL 55 DAY)),
 (109,4,114,2,'배송','결제 후 5일이 지났는데 아직 출고되지 않았습니다.','OPEN',NULL,NULL,DATE_SUB(NOW(),INTERVAL 1 DAY)),
 (110,5,110,5,'품질','요가 매트에서 고무 냄새가 심하게 납니다.','RESOLVED','초기 냄새는 천연고무 특성으로 2~3일 환기 시 감소함을 안내. 반품 가능 여부 안내 후 고객이 사용 유지를 선택.',DATE_SUB(NOW(),INTERVAL 25 DAY),DATE_SUB(NOW(),INTERVAL 27 DAY)),
 (111,1,113,4,'배송','데스크 조명 박스가 찌그러져 도착했습니다. 제품은 정상 작동합니다.','RESOLVED','제품 정상 작동 확인. 사과와 함께 적립금 2,000원 지급. 판매자에게 포장 개선 요청 전달.',DATE_SUB(NOW(),INTERVAL 46 DAY),DATE_SUB(NOW(),INTERVAL 48 DAY)),
 (112,5,111,8,'교환','스마트 워치 스트랩 사이즈가 맞지 않아 교환하고 싶습니다.','OPEN',NULL,NULL,DATE_SUB(NOW(),INTERVAL 1 DAY)),
 (113,3,107,10,'문의','폼롤러 더 부드러운 제품이 있나요?','RESOLVED','소프트 타입 재입고 예정일 안내 및 재입고 알림 신청 등록.',DATE_SUB(NOW(),INTERVAL 9 DAY),DATE_SUB(NOW(),INTERVAL 10 DAY))
ON DUPLICATE KEY UPDATE id=id;

-- 판매자 후기 답글 예시
INSERT INTO review_replies (id,review_id,seller_id,author_user_id,content,status) VALUES
 (1,107,1,2,'불편을 드려 죄송합니다. 발열 증상은 안전과 관련된 사항이라 고객센터를 통해 회수 검사를 진행하겠습니다.','PUBLISHED'),
 (2,111,2,3,'파손된 상품으로 실망을 드려 죄송합니다. 포장 완충재를 보강했고 파손 상품은 재발송해 드렸습니다.','PUBLISHED')
ON DUPLICATE KEY UPDATE id=id;
