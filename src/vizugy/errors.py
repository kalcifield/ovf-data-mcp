class VizugyError(Exception):
    """Base expected error."""


class UpstreamError(VizugyError):
    pass


class NotFoundError(VizugyError):
    pass
