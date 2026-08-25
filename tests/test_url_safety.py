import unittest
from core.ai_fleet.url_safety import UrlSafetyPolicy,UrlSafetyService

class UrlSafetyTests(unittest.TestCase):
 def test_public_https_is_allowed_with_bounds(self):
  result=UrlSafetyService(lambda host:["93.184.216.34"]).validate("https://example.com/docs")
  self.assertEqual(result["host"],"example.com"); self.assertEqual(result["max_redirects"],5)
 def test_private_metadata_credentials_ports_and_schemes_blocked(self):
  cases=[(lambda h:["127.0.0.1"],"https://example.com"),(lambda h:["169.254.169.254"],"https://metadata.example.com"),(lambda h:["10.0.0.1"],"https://example.com"),(lambda h:["93.184.216.34"],"http://example.com"),(lambda h:["93.184.216.34"],"https://user:pass@example.com"),(lambda h:["93.184.216.34"],"https://example.com:8443")]
  for resolver,url in cases:
   with self.assertRaises(ValueError): UrlSafetyService(resolver).validate(url)
 def test_redirects_revalidate_every_host_and_limit(self):
  resolver=lambda host:["93.184.216.34"] if host=="public.example" else ["127.0.0.1"]
  with self.assertRaises(ValueError): UrlSafetyService(resolver).validate_redirect_chain(["https://public.example","https://internal.example"])
  with self.assertRaises(ValueError): UrlSafetyService(lambda h:["93.184.216.34"]).validate_redirect_chain(["https://public.example"]*3,UrlSafetyPolicy(max_redirects=1))
 def test_response_type_and_size_are_bounded(self):
  service=UrlSafetyService(lambda h:["93.184.216.34"]); policy=UrlSafetyPolicy(max_bytes=100)
  self.assertTrue(service.validate_response("text/html; charset=utf-8",99,policy))
  with self.assertRaises(ValueError): service.validate_response("application/octet-stream",1,policy)
  with self.assertRaises(ValueError): service.validate_response("text/plain",101,policy)

if __name__=="__main__": unittest.main()
