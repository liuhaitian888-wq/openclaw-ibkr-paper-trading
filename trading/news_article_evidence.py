"""Bounded retained broker text, with separate identity, content and occurrence."""
from datetime import timedelta
import hashlib
import json

MAX_ARTICLE_BYTES=24_000
ARTICLE_TTL_SECONDS=300


def retain(text, *, provider, article_id, article_type, retrieved_at, published_at):
    raw=text.encode('utf-8');source_hash=hashlib.sha256(raw).hexdigest()
    identity=hashlib.sha256(json.dumps(['IBKR_NEWS',provider,article_id],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    occurrence=hashlib.sha256(json.dumps([identity,source_hash,retrieved_at.isoformat()],separators=(',',':')).encode()).hexdigest()
    key=hashlib.sha256(json.dumps(['IBKR_NEWS',provider,article_id,source_hash],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    result={'article_sha256':source_hash,'article_bytes':len(raw),'article_type':article_type,
            'article_id':article_id,'article_provider_code':provider,'article_content_key':key,
            'article_identity_key':identity,'article_revision_id':source_hash,'article_occurrence_key':occurrence,
            'article_revision_at':None,'article_revision_time_state':'PROVIDER_REVISION_TIME_UNAVAILABLE',
            'article_retrieved_at':retrieved_at.isoformat(),'article_published_at':str(published_at),
            'article_expires_at':(retrieved_at+timedelta(seconds=ARTICLE_TTL_SECONDS)).isoformat(),
            'article_untrusted_evidence':True}
    if article_type!=0:
        return {**result,'article_body_state':'UNSUPPORTED_ARTICLE_TYPE'}
    retained=raw[:MAX_ARTICLE_BYTES].decode('utf-8',errors='ignore')
    return {**result,'article_text':retained,'article_text_sha256':hashlib.sha256(retained.encode()).hexdigest(),
            'article_body_complete':len(raw)<=MAX_ARTICLE_BYTES,
            'article_body_state':'TEXT_AVAILABLE' if len(raw)<=MAX_ARTICLE_BYTES else 'TEXT_TRUNCATED'}
