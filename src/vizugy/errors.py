class VizugyError(Exception):
    """Base expected error."""


class UpstreamError(VizugyError):
    pass


class NotFoundError(VizugyError):
    pass


class AccessDeniedError(UpstreamError):
    """Upstream resource exists but requires authentication; retrying cannot help."""
