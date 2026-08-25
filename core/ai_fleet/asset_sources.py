from abc import ABC,abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any,Dict,FrozenSet,List
class AssetSourceCapability(str,Enum):SEARCH="search";INSPECT="inspect";DOWNLOAD="download";LICENSE="license"
@dataclass(frozen=True)
class AssetDownloadPolicy:
 network_allowed:bool;approval_id:str|None;workspace_id:str|None;max_bytes:int
 def validate(self):
  if not self.network_allowed or not self.approval_id or not self.workspace_id or not 1<=self.max_bytes<=100*1024*1024:raise ValueError("Asset download policy is invalid.")
  return self
class AssetSource(ABC):
 source_id:str;protocol_version="1.0";capabilities:FrozenSet[AssetSourceCapability]
 def validate(self):
  if not self.source_id or self.protocol_version!="1.0" or not self.capabilities:raise ValueError("Asset source is invalid.")
  return self
 @abstractmethod
 async def search(self,query:str)->List[Dict[str,Any]]:raise NotImplementedError
 @abstractmethod
 async def inspect(self,asset_id:str)->Dict[str,Any]:raise NotImplementedError
 @abstractmethod
 async def download(self,asset_id:str,policy:AssetDownloadPolicy)->Dict[str,Any]:raise NotImplementedError
 @abstractmethod
 async def license(self,asset_id:str)->Dict[str,Any]:raise NotImplementedError
