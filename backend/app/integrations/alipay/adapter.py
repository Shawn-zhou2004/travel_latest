"""Alipay Sandbox WAP adapter.

Environment key values may be PEM with literal ``\\n`` escapes, normal PEM
newlines, or unwrapped standard Base64 DER. URL-safe Base64 is intentionally
not accepted, so malformed or ambiguously encoded credentials fail closed.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Mapping, Protocol
from urllib.parse import urlencode, urljoin

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.settings import Settings

_REQUEST_SIGNATURE_EXCLUDED_FIELDS = frozenset({"sign"})
_CALLBACK_SIGNATURE_EXCLUDED_FIELDS = frozenset({"sign", "sign_type"})
_NOTIFY_PATH = "/api/v1/payments/alipay/callback"
_RETURN_PATH = "/payments/alipay/return"


class AlipayConfigurationError(ValueError):
    """Configured Alipay credentials are invalid or incomplete."""


class AlipayUnavailableError(RuntimeError):
    """Alipay is not configured for this environment."""


class AlipayGatewayError(RuntimeError):
    """The gateway could not return a verified trade response."""


@dataclass(frozen=True)
class AlipayWapPaymentRequest:
    out_trade_no: str
    total_amount: Decimal
    subject: str
    timeout_express: str | None = None
    return_url: str | None = None


@dataclass(frozen=True)
class AlipayWapRedirect:
    url: str


@dataclass(frozen=True)
class AlipayPrecreateRequest:
    out_trade_no: str
    total_amount: Decimal
    subject: str
    timeout_express: str


@dataclass(frozen=True)
class AlipayPrecreateResponse:
    qr_code: str
    gateway_code: str


@dataclass(frozen=True)
class VerifiedAlipayCallback:
    out_trade_no: str
    trade_no: str
    trade_status: str
    total_amount: Decimal


@dataclass(frozen=True)
class TradeQueryResult:
    out_trade_no: str | None
    trade_no: str | None
    trade_status: str | None
    total_amount: Decimal | None
    gateway_code: str


@dataclass(frozen=True)
class AlipayRefundRequest:
    out_trade_no: str
    refund_amount: Decimal
    out_request_no: str
    refund_reason: str | None = None


@dataclass(frozen=True)
class TradeRefundResult:
    out_trade_no: str | None
    trade_no: str | None
    out_request_no: str | None
    refund_fee: Decimal | None
    fund_change: str | None
    gateway_code: str


class AlipayAdapter(Protocol):
    @property
    def app_id(self) -> str: ...

    async def create_wap_redirect(self, request: AlipayWapPaymentRequest) -> AlipayWapRedirect: ...

    async def create_precreate(self, request: AlipayPrecreateRequest) -> AlipayPrecreateResponse: ...

    async def verify_callback(self, parameters: Mapping[str, str]) -> VerifiedAlipayCallback | None: ...

    async def query_trade(self, out_trade_no: str) -> TradeQueryResult: ...

    async def refund_trade(self, request: AlipayRefundRequest) -> TradeRefundResult: ...


class UnavailableAlipayAdapter:
    """Explicit injection target when a complete Alipay configuration is absent."""

    async def create_wap_redirect(self, request: AlipayWapPaymentRequest) -> AlipayWapRedirect:
        raise AlipayUnavailableError("Alipay Sandbox is not configured")

    async def create_precreate(self, request: AlipayPrecreateRequest) -> AlipayPrecreateResponse:
        raise AlipayUnavailableError("Alipay Sandbox is not configured")

    async def verify_callback(self, parameters: Mapping[str, str]) -> VerifiedAlipayCallback | None:
        raise AlipayUnavailableError("Alipay Sandbox is not configured")

    async def query_trade(self, out_trade_no: str) -> TradeQueryResult:
        raise AlipayUnavailableError("Alipay Sandbox is not configured")

    async def refund_trade(self, request: AlipayRefundRequest) -> TradeRefundResult:
        raise AlipayUnavailableError("Alipay Sandbox is not configured")


class AlipaySandboxAdapter:
    """Stateless RSA2 adapter; an optional injected client supports async test transports."""

    def __init__(self, settings: Settings, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._app_id = _required_setting(settings.alipay_app_id, "alipay_app_id")
        self._gateway_url = _required_setting(settings.alipay_gateway_url, "alipay_gateway_url")
        self._notify_url = _join_public_url(_required_setting(settings.alipay_notify_base_url, "alipay_notify_base_url"), _NOTIFY_PATH)
        self._return_url = _join_public_url(_required_setting(settings.alipay_return_base_url, "alipay_return_base_url"), _RETURN_PATH)
        self._private_key = _load_private_key(_required_setting(settings.alipay_app_private_key, "alipay_app_private_key"))
        self._public_key = _load_public_key(_required_setting(settings.alipay_public_key, "alipay_public_key"))
        self._http_client = http_client

    @property
    def app_id(self) -> str:
        return self._app_id

    async def create_wap_redirect(self, request: AlipayWapPaymentRequest) -> AlipayWapRedirect:
        biz_content: dict[str, str] = {
            "out_trade_no": request.out_trade_no,
            "total_amount": _format_amount(request.total_amount),
            "subject": request.subject,
            "product_code": "QUICK_WAP_WAY",
        }
        if request.timeout_express:
            biz_content["timeout_express"] = request.timeout_express
        parameters = self._base_parameters("alipay.trade.wap.pay")
        parameters["notify_url"] = self._notify_url
        parameters["return_url"] = request.return_url or self._return_url
        parameters["biz_content"] = json.dumps(biz_content, ensure_ascii=False, separators=(",", ":"))
        parameters["sign"] = self._sign(parameters)
        return AlipayWapRedirect(url=f"{self._gateway_url}?{urlencode(parameters)}")

    async def create_precreate(self, request: AlipayPrecreateRequest) -> AlipayPrecreateResponse:
        parameters = self._base_parameters("alipay.trade.precreate")
        parameters["notify_url"] = self._notify_url
        parameters["biz_content"] = json.dumps(
            {
                "out_trade_no": request.out_trade_no,
                "total_amount": _format_amount(request.total_amount),
                "subject": request.subject,
                "timeout_express": request.timeout_express,
                "product_code": "FACE_TO_FACE_PAYMENT",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        parameters["sign"] = self._sign(parameters)
        body, response_encoding = await self._post_gateway(parameters, "trade-precreate")
        response_data, response_raw, signature = _extract_signed_response(body, "alipay_trade_precreate_response")
        if not _verify_bytes(self._public_key, response_raw.encode(response_encoding), signature):
            raise AlipayGatewayError("Alipay trade-precreate response signature is invalid")
        try:
            gateway_code = str(response_data["code"])
            qr_code = _optional_string(response_data.get("qr_code"))
        except (KeyError, TypeError) as exc:
            raise AlipayGatewayError("Alipay trade-precreate response is invalid") from exc
        if gateway_code != "10000":
            raise AlipayGatewayError(f"Alipay trade-precreate failed with code {gateway_code}")
        if qr_code is None:
            raise AlipayGatewayError("Alipay trade-precreate response is missing qr_code")
        return AlipayPrecreateResponse(qr_code=qr_code, gateway_code=gateway_code)

    async def verify_callback(self, parameters: Mapping[str, str]) -> VerifiedAlipayCallback | None:
        if parameters.get("sign_type") != "RSA2" or not self._verify(parameters):
            return None
        try:
            return VerifiedAlipayCallback(
                out_trade_no=parameters["out_trade_no"],
                trade_no=parameters["trade_no"],
                trade_status=parameters["trade_status"],
                total_amount=Decimal(parameters["total_amount"]),
            )
        except (KeyError, ValueError):
            return None

    async def query_trade(self, out_trade_no: str) -> TradeQueryResult:
        parameters = self._base_parameters("alipay.trade.query")
        parameters["biz_content"] = json.dumps({"out_trade_no": out_trade_no}, separators=(",", ":"))
        parameters["sign"] = self._sign(parameters)
        body, response_encoding = await self._post_gateway(parameters, "trade-query")
        response_data, response_raw, signature = _extract_signed_response(body, "alipay_trade_query_response")
        if not _verify_bytes(self._public_key, response_raw.encode(response_encoding), signature):
            raise AlipayGatewayError("Alipay trade-query response signature is invalid")
        try:
            return TradeQueryResult(
                out_trade_no=_optional_string(response_data.get("out_trade_no")),
                trade_no=_optional_string(response_data.get("trade_no")),
                trade_status=_optional_string(response_data.get("trade_status")),
                total_amount=_optional_decimal(response_data.get("total_amount")),
                gateway_code=str(response_data["code"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise AlipayGatewayError("Alipay trade-query response is invalid") from exc

    async def refund_trade(self, request: AlipayRefundRequest) -> TradeRefundResult:
        biz_content: dict[str, str] = {
            "out_trade_no": request.out_trade_no,
            "refund_amount": _format_refund_amount(request.refund_amount),
            "out_request_no": request.out_request_no,
        }
        if request.refund_reason:
            biz_content["refund_reason"] = request.refund_reason
        parameters = self._base_parameters("alipay.trade.refund")
        parameters["biz_content"] = json.dumps(biz_content, ensure_ascii=False, separators=(",", ":"))
        parameters["sign"] = self._sign(parameters)
        body, response_encoding = await self._post_gateway(parameters, "trade-refund")
        response_data, response_raw, signature = _extract_signed_response(body, "alipay_trade_refund_response")
        if not _verify_bytes(self._public_key, response_raw.encode(response_encoding), signature):
            raise AlipayGatewayError("Alipay trade-refund response signature is invalid")
        try:
            return TradeRefundResult(
                out_trade_no=_optional_string(response_data.get("out_trade_no")),
                trade_no=_optional_string(response_data.get("trade_no")),
                out_request_no=_optional_string(response_data.get("out_request_no")),
                refund_fee=_optional_decimal(response_data.get("refund_fee")),
                fund_change=_optional_string(response_data.get("fund_change")),
                gateway_code=str(response_data["code"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise AlipayGatewayError("Alipay trade-refund response is invalid") from exc

    def _base_parameters(self, method: str) -> dict[str, str]:
        return {
            "app_id": self._app_id,
            "method": method,
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
        }

    def _sign(self, parameters: Mapping[str, str]) -> str:
        signature = self._private_key.sign(
            _canonicalize(parameters, excluded_fields=_REQUEST_SIGNATURE_EXCLUDED_FIELDS).encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("ascii")

    def _verify(self, parameters: Mapping[str, str]) -> bool:
        signature = parameters.get("sign")
        if not signature:
            return False
        try:
            signature_bytes = base64.b64decode(signature, validate=True)
        except (binascii.Error, ValueError):
            return False
        return _verify_bytes(
            self._public_key,
            _canonicalize(parameters, excluded_fields=_CALLBACK_SIGNATURE_EXCLUDED_FIELDS).encode("utf-8"),
            signature_bytes,
        )

    async def _post_gateway(self, parameters: Mapping[str, str], operation: str) -> tuple[str, str]:
        if self._http_client is not None:
            response = await self._http_client.post(self._gateway_url, data=parameters)
            return _response_text(response, operation)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self._gateway_url, data=parameters)
            return _response_text(response, operation)


def get_alipay_adapter(settings: Settings) -> AlipayAdapter:
    required = (
        settings.alipay_app_id,
        settings.alipay_app_private_key,
        settings.alipay_public_key,
        settings.alipay_gateway_url,
        settings.alipay_notify_base_url,
        settings.alipay_return_base_url,
    )
    if not all(value and value.strip() for value in required):
        return UnavailableAlipayAdapter()
    return AlipaySandboxAdapter(settings)


def _canonicalize(parameters: Mapping[str, str], *, excluded_fields: frozenset[str]) -> str:
    return "&".join(
        f"{key}={value}"
        for key, value in sorted(parameters.items())
        if key not in excluded_fields and value is not None and value != ""
    )


def _required_setting(value: str | None, name: str) -> str:
    if not value or not value.strip():
        raise AlipayConfigurationError(f"Missing Alipay configuration: {name}")
    return value.strip()


def _join_public_url(base_url: str, path: str) -> str:
    if not base_url.startswith(("https://", "http://")):
        raise AlipayConfigurationError("Alipay public URLs must use HTTP or HTTPS")
    return urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))


def _load_private_key(value: str) -> rsa.RSAPrivateKey:
    try:
        key_bytes, is_pem = _key_bytes(value)
        key = (
            serialization.load_pem_private_key(key_bytes, password=None)
            if is_pem
            else serialization.load_der_private_key(key_bytes, password=None)
        )
    except (TypeError, ValueError) as exc:
        raise AlipayConfigurationError("Invalid Alipay application private key") from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise AlipayConfigurationError("Alipay application private key must be RSA")
    return key


def _load_public_key(value: str) -> rsa.RSAPublicKey:
    try:
        key_bytes, is_pem = _key_bytes(value)
        key = serialization.load_pem_public_key(key_bytes) if is_pem else serialization.load_der_public_key(key_bytes)
    except (TypeError, ValueError) as exc:
        raise AlipayConfigurationError("Invalid Alipay public key") from exc
    if not isinstance(key, rsa.RSAPublicKey):
        raise AlipayConfigurationError("Alipay public key must be RSA")
    return key


def _key_bytes(value: str) -> tuple[bytes, bool]:
    normalized = value.strip().replace("\\n", "\n")
    if "-----BEGIN" in normalized:
        return normalized.encode("ascii"), True
    try:
        return base64.b64decode("".join(normalized.split()), validate=True), False
    except (binascii.Error, ValueError) as exc:
        raise AlipayConfigurationError("Alipay key must be PEM or standard Base64 DER") from exc


def _verify_bytes(public_key: rsa.RSAPublicKey, message: bytes, signature: bytes) -> bool:
    try:
        public_key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        return False
    return True


def _response_text(response: httpx.Response, operation: str) -> tuple[str, str]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AlipayGatewayError(f"Alipay {operation} request failed") from exc
    encoding = response.encoding or "utf-8"
    try:
        return response.content.decode(encoding), encoding
    except (LookupError, UnicodeDecodeError) as exc:
        raise AlipayGatewayError(f"Alipay {operation} response encoding is invalid") from exc


def _extract_signed_response(body: str, response_key: str) -> tuple[dict[str, Any], str, bytes]:
    decoder = json.JSONDecoder()
    index = _skip_whitespace(body, 0)
    if index >= len(body) or body[index] != "{":
        raise AlipayGatewayError("Alipay signed response is invalid")
    index += 1
    raw_response: str | None = None
    parsed_response: dict[str, Any] | None = None
    signature: str | None = None
    while True:
        index = _skip_whitespace(body, index)
        if index < len(body) and body[index] == "}":
            index += 1
            break
        try:
            key, index = decoder.raw_decode(body, index)
            index = _skip_whitespace(body, index)
            if body[index] != ":":
                raise ValueError
            value_start = _skip_whitespace(body, index + 1)
            value, index = decoder.raw_decode(body, value_start)
        except (IndexError, ValueError, json.JSONDecodeError) as exc:
            raise AlipayGatewayError("Alipay signed response is invalid") from exc
        if key == response_key and isinstance(value, dict):
            parsed_response = value
            raw_response = body[value_start:index]
        elif key == "sign" and isinstance(value, str):
            signature = value
        index = _skip_whitespace(body, index)
        if index < len(body) and body[index] == ",":
            index += 1
            continue
        if index < len(body) and body[index] == "}":
            index += 1
            break
        raise AlipayGatewayError("Alipay signed response is invalid")
    if _skip_whitespace(body, index) != len(body) or parsed_response is None or raw_response is None or signature is None:
        raise AlipayGatewayError("Alipay signed response is invalid")
    try:
        return parsed_response, raw_response, base64.b64decode(signature, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AlipayGatewayError("Alipay trade-query response signature is invalid") from exc


def _skip_whitespace(value: str, index: int) -> int:
    while index < len(value) and value[index].isspace():
        index += 1
    return index


def _format_amount(amount: Decimal) -> str:
    if amount <= 0:
        raise ValueError("Alipay payment amount must be positive")
    return format(amount.quantize(Decimal("0.01")), "f")


def _format_refund_amount(amount: Decimal) -> str:
    if amount <= 0:
        raise ValueError("Alipay refund amount must be positive")
    return format(amount.quantize(Decimal("0.01")), "f")


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))
