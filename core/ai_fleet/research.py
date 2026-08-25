from abc import ABC,abstractmethod
from dataclasses import dataclass,field
from enum import Enum
from typing import Any,Dict,FrozenSet,List

class ResearchCapability(str,Enum): SEARCH="search"; FETCH="fetch"; PARSE="parse"; CITE="cite"
@dataclass(frozen=True)
class ResearchConnectorPolicy:
 network_permission:str
 requests_per_minute:int
 max_results:int=20
 allowed_domains:List[str]=field(default_factory=list)
 def validate(self):
  if self.network_permission not in {"none","approval_required","allowed"} or not 1<=self.requests_per_minute<=1000 or not 1<=self.max_results<=100: raise ValueError("Research connector policy is invalid.")
  return self
class ResearchConnector(ABC):
 connector_id:str; protocol_version="1.0"; capabilities:FrozenSet[ResearchCapability]=frozenset(); policy:ResearchConnectorPolicy
 def validate(self):
  if not self.connector_id or self.protocol_version!="1.0" or not self.capabilities: raise ValueError("Research connector identity is invalid.")
  self.policy.validate()
  if ResearchCapability.FETCH in self.capabilities and self.policy.network_permission=="none": raise ValueError("Fetch capability requires network permission.")
  return self
 @abstractmethod
 async def search(self,query:str)->List[Dict[str,Any]]: raise NotImplementedError
 @abstractmethod
 async def fetch(self,url:str)->Dict[str,Any]: raise NotImplementedError
 @abstractmethod
 async def parse(self,document:Dict[str,Any])->Dict[str,Any]: raise NotImplementedError
 @abstractmethod
 async def cite(self,document:Dict[str,Any],excerpt:str)->Dict[str,Any]: raise NotImplementedError
