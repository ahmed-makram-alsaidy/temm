import hashlib
from datetime import datetime,timedelta
from typing import Any,Awaitable,Callable,Dict
from urllib.parse import urlparse
from ..errors import DomainError
from ..url_safety import UrlSafetyPolicy,UrlSafetyService

Fetcher=Callable[[str,float,int],Awaitable[Dict[str,Any]]]
class OfficialDocsConnector:
 def __init__(self,fetcher:Fetcher,safety:UrlSafetyService,allowed_domains:list[str],cache_ttl_seconds:int=300):
  self.fetcher=fetcher;self.safety=safety;self.allowed={x.lower() for x in allowed_domains};self.ttl=cache_ttl_seconds;self.cache={}
  if not self.allowed or not 10<=cache_ttl_seconds<=86400: raise ValueError("Official docs connector configuration is invalid.")
 async def fetch(self,url:str,now:datetime|None=None):
  now=now or datetime.utcnow();host=(urlparse(url).hostname or "").lower()
  if host not in self.allowed: raise DomainError("permission_denied",message="Domain is not in the official documentation allowlist.")
  self.safety.validate(url);cached=self.cache.get(url)
  if cached and cached["expires_at"]>now:return {**cached["document"],"cache":"hit"}
  response=await self.fetcher(url,20,10*1024*1024)
  chain=response.get("redirect_chain",[url]);self.safety.validate_redirect_chain(chain);body=response.get("body",b"")
  if isinstance(body,str):body=body.encode()
  self.safety.validate_response(response.get("content_type",""),len(body));
  if len(body)>10*1024*1024:raise DomainError("validation_failed",message="Official document exceeds size limit.")
  document={"url":chain[-1],"requested_url":url,"title":response.get("title") or chain[-1],"content":body.decode("utf-8",errors="replace"),"content_type":response["content_type"].split(";",1)[0],"content_hash":hashlib.sha256(body).hexdigest(),"retrieved_at":now.isoformat(),"attribution":{"domain":urlparse(chain[-1]).hostname,"source_type":"official_docs"},"cache":"miss"}
  self.cache[url]={"document":document,"expires_at":now+timedelta(seconds=self.ttl)};return document
 def cite(self,document,excerpt,locator=None):
  if excerpt not in document["content"]:raise DomainError("validation_failed",message="Citation excerpt is not present in the document.")
  return {"url":document["url"],"title":document["title"],"excerpt":excerpt,"locator":locator,"content_hash":document["content_hash"],"retrieved_at":document["retrieved_at"],"attribution":document["attribution"]}
