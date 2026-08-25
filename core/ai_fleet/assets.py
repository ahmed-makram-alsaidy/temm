from enum import Enum
from pathlib import Path
from typing import Dict,Optional

class AssetType(str,Enum): RASTER="raster"; VECTOR="vector"; DESIGN="design"; FONT="font"; AUDIO="audio"; VIDEO="video"; MOTION="motion"; MODEL_3D="3d"; DOCUMENT="document"; DATA="data"; CODE="code"; UNKNOWN="unknown"
EXTENSIONS={".png":AssetType.RASTER,".jpg":AssetType.RASTER,".jpeg":AssetType.RASTER,".webp":AssetType.RASTER,".svg":AssetType.VECTOR,".fig":AssetType.DESIGN,".sketch":AssetType.DESIGN,".ttf":AssetType.FONT,".otf":AssetType.FONT,".woff":AssetType.FONT,".woff2":AssetType.FONT,".mp3":AssetType.AUDIO,".wav":AssetType.AUDIO,".mp4":AssetType.VIDEO,".webm":AssetType.VIDEO,".json":AssetType.DATA,".csv":AssetType.DATA,".pdf":AssetType.DOCUMENT,".md":AssetType.DOCUMENT,".py":AssetType.CODE,".ts":AssetType.CODE,".tsx":AssetType.CODE,".js":AssetType.CODE,".glb":AssetType.MODEL_3D,".gltf":AssetType.MODEL_3D,".lottie":AssetType.MOTION}
def classify_asset(filename:str,mime:Optional[str])->Dict[str,object]:
 extension=Path(filename).suffix.lower(); declared=EXTENSIONS.get(extension,AssetType.UNKNOWN); major=(mime or "").split("/",1)[0]; observed=AssetType.UNKNOWN
 if major=="image": observed=AssetType.VECTOR if mime=="image/svg+xml" else AssetType.RASTER
 elif major=="audio": observed=AssetType.AUDIO
 elif major=="video": observed=AssetType.VIDEO
 elif major=="font": observed=AssetType.FONT
 elif mime in {"application/pdf","text/markdown"}: observed=AssetType.DOCUMENT
 elif mime in {"application/json","text/csv"}: observed=AssetType.DATA
 conflict=declared!=AssetType.UNKNOWN and observed!=AssetType.UNKNOWN and declared!=observed
 return {"extension":extension,"extension_type":declared.value,"mime":mime,"mime_type":observed.value,"canonical_type":None if conflict else (observed if observed!=AssetType.UNKNOWN else declared).value,"conflict":conflict,"state":"conflict" if conflict else "classified" if observed!=AssetType.UNKNOWN or declared!=AssetType.UNKNOWN else "unknown"}
