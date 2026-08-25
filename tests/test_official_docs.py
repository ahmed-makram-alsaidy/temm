import unittest
from datetime import datetime,timedelta
from core.ai_fleet.services.official_docs import OfficialDocsConnector
from core.ai_fleet.url_safety import UrlSafetyService
class OfficialDocsTests(unittest.IsolatedAsyncioTestCase):
 async def test_bounded_attributed_fetch_citation_and_cache(self):
  calls=[]
  async def fetch(url,timeout,max_bytes): calls.append(url);return {"body":b"Official version 2.0 docs","content_type":"text/plain","title":"Docs","redirect_chain":[url]}
  connector=OfficialDocsConnector(fetch,UrlSafetyService(lambda h:["93.184.216.34"]),["docs.example.com"],60);now=datetime(2026,1,1)
  one=await connector.fetch("https://docs.example.com/guide",now);two=await connector.fetch("https://docs.example.com/guide",now+timedelta(seconds=10));citation=connector.cite(one,"version 2.0","line 1")
  self.assertEqual(one["cache"],"miss");self.assertEqual(two["cache"],"hit");self.assertEqual(len(calls),1);self.assertEqual(one["attribution"]["source_type"],"official_docs");self.assertEqual(citation["content_hash"],one["content_hash"])
 async def test_domain_redirect_type_and_citation_controls(self):
  async def fetch(url,timeout,max_bytes):return {"body":b"x","content_type":"application/octet-stream","redirect_chain":[url]}
  connector=OfficialDocsConnector(fetch,UrlSafetyService(lambda h:["93.184.216.34"]),["docs.example.com"])
  with self.assertRaises(Exception):await connector.fetch("https://evil.example.com")
  with self.assertRaises(Exception):await connector.fetch("https://docs.example.com")
  with self.assertRaises(Exception):connector.cite({"content":"abc"},"missing")
if __name__=="__main__":unittest.main()
