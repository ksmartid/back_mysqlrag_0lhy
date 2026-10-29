import os
import httpx
from fastapi import HTTPException

URL=os.getenv('OLLAMA_URL','http://127.0.0.1:11434').rstrip('/')

def embed_model() -> str:
    return os.getenv('OLLAMA_EMBED_MODEL','nomic-embed-text')

async def embed(text: str) -> list[float]:
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r=await client.post(f'{URL}/api/embed',json={'model':embed_model(),'input':text})
            r.raise_for_status()
            vector=r.json()['embeddings'][0]
            if len(vector)!=768: raise ValueError('PostgreSQL REAL[] 스키마는 768차원 임베딩을 요구한다.')
            return vector
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(503,f'임베딩 실패: {exc}') from exc

async def complete(prompt: str, provider: str|None=None) -> str:
    provider=(provider or os.getenv('LLM_PROVIDER','local')).lower()
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            if provider=='local':
                r=await client.post(f'{URL}/api/chat',json={'model':os.getenv('OLLAMA_CHAT_MODEL','qwen2.5:3b'),'stream':False,'messages':[{'role':'system','content':'한국어로 답한다. 제공된 근거에 없는 내용은 추측하지 않는다. 개인정보를 불필요하게 반복하지 않는다.'},{'role':'user','content':prompt}]})
                r.raise_for_status(); return r.json()['message']['content']
            if provider=='openai':
                key=os.getenv('OPENAI_API_KEY')
                if not key: raise ValueError('OPENAI_API_KEY 설정 필요')
                r=await client.post('https://api.openai.com/v1/chat/completions',headers={'Authorization':f'Bearer {key}'},json={'model':os.getenv('OPENAI_MODEL','gpt-4o-mini'),'messages':[{'role':'user','content':prompt}]})
                r.raise_for_status(); return r.json()['choices'][0]['message']['content']
            if provider=='gemini':
                key=os.getenv('GEMINI_API_KEY')
                if not key: raise ValueError('GEMINI_API_KEY 설정 필요')
                model=os.getenv('GEMINI_MODEL','gemini-3.8-flash')
                r=await client.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',headers={'x-goog-api-key':key},json={'contents':[{'parts':[{'text':prompt}]}]})
                r.raise_for_status(); return r.json()['candidates'][0]['content']['parts'][0]['text']
            raise ValueError('LLM_PROVIDER 값은 local, openai, gemini 중 하나')
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise HTTPException(503,f'LLM 호출 실패: {exc}') from exc
