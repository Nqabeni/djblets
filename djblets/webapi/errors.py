"""Error classes and codes for WebAPI."""


class WebAPIError(object):
    """
    An API error, containing an error code and human readable message.
    """
    def __init__(self, code, msg, http_status=400, headers={}):
        self.code = code
        self.msg = msg
        self.http_status = http_status
        self.headers = headers

    def __repr__(self):
        return '<API Error %d, HTTP %d: %s>' % (self.code, self.http_status,
                                                self.msg)

    def with_overrides(self, msg=None, headers=None):
        """Overrides the default message and/or headers for an error."""
        if headers is None:
            headers = self.headers

        return WebAPIError(self.code, msg or self.msg, self.http_status,
                           headers)

    def with_message(self, msg):
        """
        Overrides the default message for a WebAPIError with something
        more context specific.

        Example:
        return ENABLE_EXTENSION_FAILED.with_message('some error message')
        """
        return self.with_overrides(msg)


class WebAPITokenGenerationError(Exception):
    """An error generating a Web API token."""


def _get_auth_headers(request):
    from djblets.webapi.auth.backends import get_auth_backends

    headers = {}
    www_auth_schemes = []

    for auth_backend_cls in get_auth_backends():
        auth_backend = auth_backend_cls()

        if auth_backend.www_auth_scheme:
            www_auth_schemes.append(auth_backend.www_auth_scheme)

        headers.update(auth_backend.get_auth_headers(request))

    if www_auth_schemes:
        headers['WWW-Authenticate'] = ', '.join(www_auth_schemes)

    return headers


#
# Standard error messages
#
NO_ERROR = WebAPIError(
    0,
    "If you see this, yell at the developers")

SERVICE_NOT_CONFIGURED = WebAPIError(
    1,
    "The web service has not yet been configured",
    http_status=503)

DOES_NOT_EXIST = WebAPIError(
    100,
    "Object does not exist",
    http_status=404)

PERMISSION_DENIED = WebAPIError(
    101,
    "You don't have permission for this",
    http_status=403)

INVALID_ATTRIBUTE = WebAPIError(
    102,
    "Invalid attribute",
    http_status=400)

NOT_LOGGED_IN = WebAPIError(
    103,
    "You are not logged in",
    http_status=401,
    headers=_get_auth_headers)

LOGIN_FAILED = WebAPIError(
    104,
    "The username or password was not correct",
    http_status=401,
    headers=_get_auth_headers)

INVALID_FORM_DATA = WebAPIError(
    105,
    "One or more fields had errors",
    http_status=400)

MISSING_ATTRIBUTE = WebAPIError(
    106,
    "Missing value for the attribute",
    http_status=400)

ENABLE_EXTENSION_FAILED = WebAPIError(
    107,
    "There was a problem enabling the extension",
    http_status=500)  # 500 Internal Server Error

DISABLE_EXTENSION_FAILED = WebAPIError(
    108,
    "There was a problem disabling the extension",
    http_status=500)  # 500 Internal Server Error

EXTENSION_INSTALLED = WebAPIError(
    109,
    "This extension has already been installed.",
    http_status=409)

INSTALL_EXTENSION_FAILED = WebAPIError(
    110,
    "An error occurred while installing the extension",
    http_status=409)

DUPLICATE_ITEM = WebAPIError(
    111,
    "An entry for this item or its unique key(s) already exists",
    http_status=409)

OAUTH_MISSING_SCOPE_ERROR = WebAPIError(
    112,
    'Your OAuth2 token lacks the necessary scopes for this request.',
    http_status=403,  # 403 Forbidden
)

OAUTH_ACCESS_DENIED_ERROR = WebAPIError(
    113,
    'OAuth2 token access for this resource is prohibited.',
    http_status=403,  # 403 Forbidden
)

RATE_LIMIT_EXCEEDED = WebAPIError(
    114,
    'API rate limit has been exceeded.',
    http_status=429,  # 429 Too Many Requests
)
