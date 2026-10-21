"""Private file storage for sensitive uploads (evidence, attachments)."""
from django.core.files.storage import storages


def private_storage():
    """Callable storage so migrations do not freeze a concrete backend."""
    return storages["private"]
