import asyncio
import base64
import json
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.settings import Settings
from app.integrations.alipay import (
    AlipayGatewayError,
    AlipayPrecreateRequest,
    AlipayRefundRequest,
    AlipaySandboxAdapter,
    AlipayUnavailableError,
    AlipayWapPaymentRequest,
    TradeRefundResult,
    UnavailableAlipayAdapter,
    get_alipay_adapter,
)


@pytest.fixture
def key_pair() -> tuple[rsa.RSAPrivateKey, str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return private_key, private_pem, public_pem


def _settings(private_key: str, public_key: str) -> Settings:
    return Settings(
        app_env="test",
        alipay_app_id="sandbox-app-id",
        alipay_app_private_key=private_key,
        alipay_public_key=public_key,
        alipay_gateway_url="https://sandbox.example.test/gateway.do",
        alipay_notify_base_url="https://api.example.test",
        alipay_return_base_url="https://web.example.test",
    )


def _sign(private_key: rsa.RSAPrivateKey, values: dict[str, str]) -> str:
    canonical = "&".join(f"{key}={value}" for key, value in sorted(values.items()) if key not in {"sign", "sign_type"} and value)
    return base64.b64encode(private_key.sign(canonical.encode(), padding.PKCS1v15(), hashes.SHA256())).decode("ascii")


def test_adapter_is_disabled_until_every_public_and_secret_setting_is_present() -> None:
    adapter = get_alipay_adapter(Settings(
        app_env="test",
        alipay_app_id="only-this",
        alipay_app_private_key="",
        alipay_public_key="",
        alipay_gateway_url="",
        alipay_notify_base_url="",
        alipay_return_base_url="",
    ))

    assert isinstance(adapter, UnavailableAlipayAdapter)
    with pytest.raises(AlipayUnavailableError):
        asyncio.run(adapter.query_trade("order-1"))


def test_wap_redirect_uses_fixed_alipay_fields_and_rsa2_signature(key_pair: tuple[rsa.RSAPrivateKey, str, str]) -> None:
    private_key, private_pem, public_pem = key_pair
    adapter = AlipaySandboxAdapter(_settings(private_pem.replace("\n", "\\n"), public_pem))

    redirect = asyncio.run(adapter.create_wap_redirect(AlipayWapPaymentRequest("order-1", Decimal("12.5"), "Travel order")))
    query = parse_qs(urlparse(redirect.url).query)
    signed_values = {key: values[0] for key, values in query.items()}

    assert urlparse(redirect.url).scheme == "https"
    assert query["method"] == ["alipay.trade.wap.pay"]
    assert query["format"] == ["JSON"]
    assert query["charset"] == ["utf-8"]
    assert query["sign_type"] == ["RSA2"]
    assert query["notify_url"] == ["https://api.example.test/api/v1/payments/alipay/callback"]
    assert query["return_url"] == ["https://web.example.test/payments/alipay/return"]
    assert json.loads(query["biz_content"][0]) == {
        "out_trade_no": "order-1",
        "total_amount": "12.50",
        "subject": "Travel order",
        "product_code": "QUICK_WAP_WAY",
    }
    private_key.public_key().verify(base64.b64decode(query["sign"][0]), _canonical_request(signed_values).encode(), padding.PKCS1v15(), hashes.SHA256())


def test_callback_verification_rejects_tampering(key_pair: tuple[rsa.RSAPrivateKey, str, str]) -> None:
    private_key, private_pem, public_pem = key_pair
    adapter = AlipaySandboxAdapter(_settings(private_pem, public_pem))
    callback = {
        "out_trade_no": "order-1",
        "trade_no": "20260001",
        "trade_status": "TRADE_SUCCESS",
        "total_amount": "12.50",
        "sign_type": "RSA2",
    }
    callback["sign"] = _sign(private_key, callback)

    verified = asyncio.run(adapter.verify_callback(callback))
    callback["total_amount"] = "99.99"

    assert verified is not None
    assert verified.total_amount == Decimal("12.50")
    assert asyncio.run(adapter.verify_callback(callback)) is None


def test_query_verifies_the_exact_signed_response_object(key_pair: tuple[rsa.RSAPrivateKey, str, str]) -> None:
    private_key, private_pem, public_pem = key_pair
    response_object = '{"code":"10000","out_trade_no":"order-1","trade_no":"20260001","trade_status":"TRADE_SUCCESS","total_amount":"12.50"}'
    signature = base64.b64encode(private_key.sign(response_object.encode(), padding.PKCS1v15(), hashes.SHA256())).decode("ascii")
    body = f'{{"alipay_trade_query_response":{response_object},"sign":"{signature}"}}'
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body)))
    adapter = AlipaySandboxAdapter(_settings(private_pem, public_pem), http_client=client)

    result = asyncio.run(adapter.query_trade("order-1"))
    asyncio.run(client.aclose())

    assert result.gateway_code == "10000"
    assert result.trade_status == "TRADE_SUCCESS"
    assert result.total_amount == Decimal("12.50")


def test_query_verifies_signed_chinese_response_using_declared_gbk_charset(key_pair: tuple[rsa.RSAPrivateKey, str, str]) -> None:
    private_key, private_pem, public_pem = key_pair
    response_object = '{"code":"40004","msg":"Business Failed","sub_code":"ACQ.TRADE_NOT_EXIST","sub_msg":"交易不存在"}'
    signature = base64.b64encode(private_key.sign(response_object.encode("gbk"), padding.PKCS1v15(), hashes.SHA256())).decode("ascii")
    body = f'{{"alipay_trade_query_response":{response_object},"sign":"{signature}"}}'.encode("gbk")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body, headers={"content-type": "text/html;charset=GBK"})))
    adapter = AlipaySandboxAdapter(_settings(private_pem, public_pem), http_client=client)

    result = asyncio.run(adapter.query_trade("order-1"))
    asyncio.run(client.aclose())

    assert result.gateway_code == "40004"
    assert result.trade_status is None


def test_precreate_signs_request_and_returns_only_verified_qr_code(key_pair: tuple[rsa.RSAPrivateKey, str, str]) -> None:
    private_key, private_pem, public_pem = key_pair
    response_object = '{"code":"10000","qr_code":"https://qr.alipay.com/example"}'
    signature = base64.b64encode(private_key.sign(response_object.encode(), padding.PKCS1v15(), hashes.SHA256())).decode("ascii")
    body = f'{{"alipay_trade_precreate_response":{response_object},"sign":"{signature}"}}'

    def gateway(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        signed_values = {key: values[0] for key, values in form.items()}
        assert form["method"] == ["alipay.trade.precreate"]
        assert form["notify_url"] == ["https://api.example.test/api/v1/payments/alipay/callback"]
        assert json.loads(form["biz_content"][0]) == {
            "out_trade_no": "MP202608130001", "total_amount": "19.90", "subject": "AI planning membership",
            "timeout_express": "10m", "product_code": "FACE_TO_FACE_PAYMENT",
        }
        private_key.public_key().verify(base64.b64decode(form["sign"][0]), _canonical_request(signed_values).encode(), padding.PKCS1v15(), hashes.SHA256())
        return httpx.Response(200, text=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(gateway))
    adapter = AlipaySandboxAdapter(_settings(private_pem, public_pem), http_client=client)
    result = asyncio.run(adapter.create_precreate(AlipayPrecreateRequest("MP202608130001", Decimal("19.90"), "AI planning membership", "10m")))
    asyncio.run(client.aclose())

    assert result.qr_code == "https://qr.alipay.com/example"
    assert result.gateway_code == "10000"


@pytest.mark.parametrize(
    ("response_object", "signature", "message"),
    [
        ('{"code":"40004"}', "valid", "failed"),
        ('{"code":"10000"}', "valid", "missing qr_code"),
        ("not-json", "valid", "invalid"),
        ('{"code":"10000","qr_code":"https://qr.alipay.com/example"}', "invalid", "signature"),
    ],
)
def test_precreate_rejects_unusable_or_unverified_responses(key_pair: tuple[rsa.RSAPrivateKey, str, str], response_object: str, signature: str, message: str) -> None:
    private_key, private_pem, public_pem = key_pair
    signed_signature = base64.b64encode(private_key.sign(response_object.encode(), padding.PKCS1v15(), hashes.SHA256())).decode("ascii") if signature == "valid" and response_object != "not-json" else "aW52YWxpZA=="
    body = response_object if response_object == "not-json" else f'{{"alipay_trade_precreate_response":{response_object},"sign":"{signed_signature}"}}'
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body)))
    adapter = AlipaySandboxAdapter(_settings(private_pem, public_pem), http_client=client)

    with pytest.raises(AlipayGatewayError, match=message):
        asyncio.run(adapter.create_precreate(AlipayPrecreateRequest("order-1", Decimal("19.90"), "Membership", "10m")))
    asyncio.run(client.aclose())


def test_query_rejects_response_with_invalid_signature(key_pair: tuple[rsa.RSAPrivateKey, str, str]) -> None:
    _private_key, private_pem, public_pem = key_pair
    body = '{"alipay_trade_query_response":{"code":"10000"},"sign":"aW52YWxpZA=="}'
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body)))
    adapter = AlipaySandboxAdapter(_settings(private_pem, public_pem), http_client=client)

    with pytest.raises(AlipayGatewayError, match="signature"):
        asyncio.run(adapter.query_trade("order-1"))
    asyncio.run(client.aclose())


def test_refund_posts_signed_request_and_verifies_response(key_pair: tuple[rsa.RSAPrivateKey, str, str]) -> None:
    private_key, private_pem, public_pem = key_pair
    response_object = '{"code":"10000","out_trade_no":"order-1","trade_no":"20260001","out_request_no":"refund-1","refund_fee":"12.50","fund_change":"Y"}'
    signature = base64.b64encode(private_key.sign(response_object.encode(), padding.PKCS1v15(), hashes.SHA256())).decode("ascii")
    body = f'{{"alipay_trade_refund_response":{response_object},"sign":"{signature}"}}'

    def gateway(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        signed_values = {key: values[0] for key, values in form.items()}
        assert form["method"] == ["alipay.trade.refund"]
        assert json.loads(form["biz_content"][0]) == {
            "out_trade_no": "order-1",
            "refund_amount": "12.50",
            "out_request_no": "refund-1",
            "refund_reason": "Customer cancelled",
        }
        private_key.public_key().verify(base64.b64decode(form["sign"][0]), _canonical_request(signed_values).encode(), padding.PKCS1v15(), hashes.SHA256())
        return httpx.Response(200, text=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(gateway))
    adapter = AlipaySandboxAdapter(_settings(private_pem, public_pem), http_client=client)
    result = asyncio.run(adapter.refund_trade(AlipayRefundRequest("order-1", Decimal("12.5"), "refund-1", "Customer cancelled")))
    asyncio.run(client.aclose())

    assert result == TradeRefundResult(
        out_trade_no="order-1",
        trade_no="20260001",
        out_request_no="refund-1",
        refund_fee=Decimal("12.50"),
        fund_change="Y",
        gateway_code="10000",
    )


def test_refund_rejects_response_with_invalid_signature(key_pair: tuple[rsa.RSAPrivateKey, str, str]) -> None:
    _private_key, private_pem, public_pem = key_pair
    body = '{"alipay_trade_refund_response":{"code":"10000"},"sign":"aW52YWxpZA=="}'
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body)))
    adapter = AlipaySandboxAdapter(_settings(private_pem, public_pem), http_client=client)

    with pytest.raises(AlipayGatewayError, match="signature"):
        asyncio.run(adapter.refund_trade(AlipayRefundRequest("order-1", Decimal("12.50"), "refund-1")))
    asyncio.run(client.aclose())


def test_unwrapped_base64_der_keys_are_supported(key_pair: tuple[rsa.RSAPrivateKey, str, str]) -> None:
    _private_key, private_pem, public_pem = key_pair
    private_der = serialization.load_pem_private_key(private_pem.encode(), password=None).private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_der = serialization.load_pem_public_key(public_pem.encode()).public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    adapter = AlipaySandboxAdapter(_settings(base64.b64encode(private_der).decode(), base64.b64encode(public_der).decode()))

    assert isinstance(adapter, AlipaySandboxAdapter)


def _canonical(values: dict[str, str]) -> str:
    return "&".join(f"{key}={value}" for key, value in sorted(values.items()) if key not in {"sign", "sign_type"} and value)


def _canonical_request(values: dict[str, str]) -> str:
    return "&".join(f"{key}={value}" for key, value in sorted(values.items()) if key != "sign" and value)
