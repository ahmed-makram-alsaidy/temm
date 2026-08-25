from typing import Any,Awaitable,Callable,Dict,List
from ..errors import DomainError
from ..url_safety import UrlSafetyService
class GeneralSearchConnector:
 def __init__(self,searcher:Callable[[str,int],Awaitable[List[Dict[str,Any]]]],fetcher:Callable[[str],Awaitable[Dict[str,Any]]],safety:UrlSafetyService):self.searcher=searcher;self.fetcher=fetcher;self.safety=safety
 async def search(self,query:str,limit:int=10):
  if not query.strip() or not 1<=limit<=50:raise DomainError("validation_failed",message="Search query or limit is invalid.")
  raw=await self.searcher(query,limit);results=[]
  for index,item in enumerate(raw[:limit]):
   try:self.safety.validate(item["url"])
   except (ValueError,KeyError):continue
   results.append({"result_id":f"result-{index+1}","url":item["url"],"title":item.get("title") or item["url"],"snippet":item.get("snippet",""),"provider_rank":index+1,"state":"unretrieved_candidate","verified_claim":False})
  return results
 async def retrieve(self,result):
  if result.get("state")!="unretrieved_candidate":raise DomainError("validation_failed",message="Search result is not a retrieval candidate.")
  self.safety.validate(result["url"]);document=await self.fetcher(result["url"])
  return {**result,"state":"retrieved_source","verified_claim":False,"document":document}
