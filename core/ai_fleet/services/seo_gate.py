import re
from typing import Dict,List
class SeoContentGateService:
 def assess(self,project_type:str,html:str,files:set[str],link_results:List[Dict]|None=None):
  if project_type!="website":return {"applicable":False,"findings":[],"passed":True,"reason":"project_type_not_website"}
  findings=[]
  checks=[("title_missing",r"<title>\s*[^<]+</title>","high"),("description_missing",r"<meta[^>]+name=['\"]description['\"][^>]+content=['\"][^'\"]+", "medium"),("canonical_missing",r"<link[^>]+rel=['\"]canonical['\"]", "medium")]
  for code,pattern,severity in checks:
   if not re.search(pattern,html,re.I):findings.append({"rule":code,"severity":severity,"evidence":"markup_missing"})
  for name in ["sitemap.xml","robots.txt"]:
   if name not in files:findings.append({"rule":f"{name}_missing","severity":"medium","evidence":"file_missing"})
  if re.search(r"\b(?:lorem ipsum|todo|placeholder)\b",html,re.I):findings.append({"rule":"placeholder_content","severity":"high","evidence":"bounded_marker_scan"})
  for item in link_results or []:
   if item.get("status",200)>=400:findings.append({"rule":"broken_link","severity":"high","evidence":{"url":item.get("url"),"status":item.get("status")}})
  return {"applicable":True,"findings":findings,"passed":not any(x["severity"]=="high" for x in findings),"gate_version":"1.0"}
seo_content_gate_service=SeoContentGateService()
