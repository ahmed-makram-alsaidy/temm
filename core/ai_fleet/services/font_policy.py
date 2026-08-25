from typing import Dict,List
class FontPolicyService:
 def authorize(self,operation:str,license_record:Dict,available_tools:List[str]):
  if operation not in {"metadata","subset","convert"}:raise ValueError("Font operation is invalid.")
  restrictions=set(license_record.get("restrictions",[]));approved=license_record.get("approval_status")=="approved" and license_record.get("confidence") in {"high","verified"}
  if operation=="metadata":return {"allowed":True,"reason":"metadata_only","tool_required":None}
  if not approved:return {"allowed":False,"reason":"license_not_approved","tool_required":None}
  if operation in restrictions or f"no_{operation}" in restrictions:return {"allowed":False,"reason":"license_restriction","tool_required":None}
  tool="fonttools" if operation=="subset" else "font_converter"
  if tool not in available_tools:return {"allowed":False,"reason":"tool_unavailable","tool_required":tool}
  return {"allowed":True,"reason":"approved_license_and_tool","tool_required":tool}
font_policy_service=FontPolicyService()
