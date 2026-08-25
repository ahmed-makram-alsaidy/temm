import ipaddress
import socket
from dataclasses import dataclass
from typing import Callable, List
from urllib.parse import urlparse


@dataclass(frozen=True)
class UrlSafetyPolicy:
    max_redirects: int = 5
    max_bytes: int = 10 * 1024 * 1024
    timeout_seconds: float = 20
    allowed_content_types: tuple[str, ...] = ("text/html", "text/plain", "application/json", "application/pdf")


class UrlSafetyService:
    def __init__(self, resolver: Callable[[str], List[str]] | None = None): self._resolver = resolver or self._resolve
    def validate(self, url: str, policy: UrlSafetyPolicy = UrlSafetyPolicy()):
        parsed=urlparse(url)
        if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None,443}: raise ValueError("URL scheme, host, credentials, or port is not allowed.")
        host=parsed.hostname.rstrip(".").lower()
        if host in {"localhost","localhost.localdomain","metadata.google.internal"} or host.endswith((".local",".internal",".localhost")): raise ValueError("Internal host is blocked.")
        try: addresses=[str(ipaddress.ip_address(host))]
        except ValueError: addresses=self._resolver(host)
        if not addresses: raise ValueError("URL host did not resolve.")
        for value in addresses:
            ip=ipaddress.ip_address(value)
            if not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified: raise ValueError("Private or non-global IP address is blocked.")
            if str(ip) in {"169.254.169.254","100.100.100.200"}: raise ValueError("Metadata endpoint is blocked.")
        if not 0<=policy.max_redirects<=10 or not 1<=policy.max_bytes<=100*1024*1024 or not 0.1<=policy.timeout_seconds<=120: raise ValueError("URL safety limits are invalid.")
        return {"url":url,"host":host,"addresses":addresses,"max_redirects":policy.max_redirects,"max_bytes":policy.max_bytes,"timeout_seconds":policy.timeout_seconds,"allowed_content_types":list(policy.allowed_content_types)}
    def validate_redirect_chain(self, urls: List[str], policy: UrlSafetyPolicy = UrlSafetyPolicy()):
        if len(urls)-1>policy.max_redirects: raise ValueError("Redirect limit exceeded.")
        return [self.validate(url,policy) for url in urls]
    def validate_response(self, content_type: str, content_length: int|None, policy: UrlSafetyPolicy = UrlSafetyPolicy()):
        media=content_type.split(";",1)[0].strip().lower()
        if media not in policy.allowed_content_types: raise ValueError("Response content type is not allowed.")
        if content_length is not None and (content_length<0 or content_length>policy.max_bytes): raise ValueError("Response size exceeds policy.")
        return True
    def _resolve(self,host): return sorted({item[4][0] for item in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)})

url_safety_service=UrlSafetyService()
