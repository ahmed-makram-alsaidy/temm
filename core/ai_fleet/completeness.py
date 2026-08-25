from dataclasses import asdict,dataclass
from typing import List
@dataclass(frozen=True)
class CompletenessRule:
 rule_id:str;version:str;project_types:List[str];severity:str;evidence_type:str;description:str
 def validate(self):
  if not self.rule_id or not self.version or not self.project_types or self.severity not in {"info","low","medium","high","critical"} or not self.evidence_type:return False
  return True
RULES=[CompletenessRule("todo_markers","1.0",["all"],"medium","file_scan","No unresolved TODO markers"),CompletenessRule("placeholder_content","1.0",["all"],"high","file_scan","No placeholder content"),CompletenessRule("missing_assets","1.0",["all"],"high","asset_findings","Required assets present"),CompletenessRule("missing_fonts","1.0",["website","design"],"medium","asset_findings","Required fonts present"),CompletenessRule("broken_imports","1.0",["software","website","business_system"],"high","build","Imports resolve"),CompletenessRule("broken_links","1.0",["website"],"high","crawler","Links resolve"),CompletenessRule("favicon","1.0",["website"],"low","file_scan","Favicon present"),CompletenessRule("metadata","1.0",["website"],"medium","markup","Metadata complete"),CompletenessRule("tests","1.0",["software","website","business_system"],"high","run","Tests pass"),CompletenessRule("build","1.0",["software","website","business_system"],"critical","run","Build passes"),CompletenessRule("accessibility","1.0",["website"],"high","gate","Accessibility reviewed"),CompletenessRule("performance","1.0",["website","software"],"medium","measurement","Performance budget met"),CompletenessRule("blockers","1.0",["all"],"critical","graph","No unresolved blockers")]
def rules_for(project_type):return [asdict(rule) for rule in RULES if rule.validate() and ("all" in rule.project_types or project_type in rule.project_types)]
