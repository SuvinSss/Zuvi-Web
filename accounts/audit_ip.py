"""Safe client IP resolution for audit metadata."""


def get_client_ip(request):
    """
    Return the peer IP from REMOTE_ADDR only.

    Do not trust X-Forwarded-For here: clients can spoof it unless a trusted
    reverse proxy strips/rewrites the header, which this MVP does not configure.
    """
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR")
