import unittest
from core.ai_fleet.services.general_search import GeneralSearchConnector
from core.ai_fleet.url_safety import UrlSafetyService
class GeneralSearchTests(unittest.IsolatedAsyncioTestCase):
 async def test_results_are_not_facts_before_or_after_retrieval(self):
  async def search(q,l):return [{"url":"https://a.example/doc","title":"A","snippet":"claim"},{"url":"https://b.example/doc","title":"B"}]
  async def fetch(u):return {"content":"retrieved","hash":"a"*64}
  connector=GeneralSearchConnector(search,fetch,UrlSafetyService(lambda h:["93.184.216.34"]));results=await connector.search("topic",2)
  self.assertEqual([x["provider_rank"] for x in results],[1,2]);self.assertTrue(all(x["state"]=="unretrieved_candidate" and not x["verified_claim"] for x in results));retrieved=await connector.retrieve(results[0]);self.assertEqual(retrieved["state"],"retrieved_source");self.assertFalse(retrieved["verified_claim"])
 async def test_unsafe_results_are_filtered(self):
  async def search(q,l):return [{"url":"https://safe.example"},{"url":"http://unsafe.example"}]
  async def fetch(u):return {}
  results=await GeneralSearchConnector(search,fetch,UrlSafetyService(lambda h:["93.184.216.34"])).search("x");self.assertEqual(len(results),1)
if __name__=="__main__":unittest.main()
