from typing import Annotated, Callable

from fastapi import Depends, Header

from app.modules.auth.service import AccessClaims, AuthError, AuthService, InMemoryTTLStore


_default_auth_service = AuthService(InMemoryTTLStore())


def get_auth_service() -> AuthService:
    return _default_auth_service


def get_bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
    if authorization is None or not authorization.startswith("Bearer "):
        raise AuthError(401, "AUTHENTICATION_REQUIRED", "A bearer access token is required.")
    return authorization.removeprefix("Bearer ")


def current_consumer_claims(
    token: Annotated[str, Depends(get_bearer_token)], service: Annotated[AuthService, Depends(get_auth_service)]
) -> AccessClaims:
    return service.parse_access_token(token, "consumer")


def optional_consumer_claims(
    authorization: Annotated[str | None, Header()] = None,
    service: Annotated[AuthService, Depends(get_auth_service)] = None,
) -> AccessClaims | None:
    if authorization is None:
        return None
    if not authorization.startswith("Bearer "):
        raise AuthError(401, "AUTHENTICATION_REQUIRED", "A bearer access token is required.")
    return service.parse_access_token(authorization.removeprefix("Bearer "), "consumer")


def current_admin_claims(
    token: Annotated[str, Depends(get_bearer_token)], service: Annotated[AuthService, Depends(get_auth_service)]
) -> AccessClaims:
    claims = service.parse_access_token(token, "admin")
    if "platform_admin" not in claims.roles:
        raise AuthError(403, "FORBIDDEN", "Platform admin role is required to access this endpoint.")
    return claims


def current_backoffice_claims(
    token: Annotated[str, Depends(get_bearer_token)], service: Annotated[AuthService, Depends(get_auth_service)]
) -> AccessClaims:
    claims = service.parse_access_token(token, "admin")
    if not {"platform_admin", "provider_admin", "provider_staff"}.intersection(claims.roles):
        raise AuthError(403, "FORBIDDEN", "A backoffice role is required to access this endpoint.")
    return claims


def current_authenticated_claims(
    token: Annotated[str, Depends(get_bearer_token)], service: Annotated[AuthService, Depends(get_auth_service)]
) -> AccessClaims:
    try:
        return service.parse_access_token(token, "consumer")
    except AuthError as error:
        if error.code != "INVALID_TOKEN_AUDIENCE":
            raise
        return service.parse_access_token(token, "admin")


CurrentConsumer = Annotated[AccessClaims, Depends(current_consumer_claims)]
CurrentAdmin = Annotated[AccessClaims, Depends(current_admin_claims)]
CurrentBackoffice = Annotated[AccessClaims, Depends(current_backoffice_claims)]
CurrentAuthenticated = Annotated[AccessClaims, Depends(current_authenticated_claims)]
OptionalCurrentConsumer = Annotated[AccessClaims | None, Depends(optional_consumer_claims)]


def require_roles(*roles: str) -> Callable[..., AccessClaims]:
    def guard(claims: CurrentAdmin) -> AccessClaims:
        if not set(roles).intersection(claims.roles):
            raise AuthError(403, "FORBIDDEN", "This role is not permitted to access this endpoint.")
        return claims

    return guard
