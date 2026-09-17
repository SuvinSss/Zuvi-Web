"""Private, local import staging. Never use the public storage backend here."""
import io
import os
from pathlib import Path
import stat
import warnings

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image

from .import_contract import ImportProblem, digest
from .validators import ALLOWED_IMAGE_EXTENSIONS, MAX_PRODUCT_IMAGE_SIZE_BYTES, validate_product_image

MAX_BUNDLE_BYTES = 2 * 1024 * 1024 * 1024


def validate_filename(name):
    if not name or len(name) > 200 or name in ('.', '..') or '..' in name or any(c in name for c in '/\\:') or any(ord(c) < 32 or ord(c) == 127 for c in name) or Path(name).suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
        raise ImportProblem('IMAGE_FILENAME', 'Use an exact flat JPEG, PNG or WebP filename, without paths, URLs or control characters.', 'image_1')


def staging_root():
    value = getattr(settings, 'CATALOG_IMPORT_ROOT', '')
    if not value:
        raise ImportProblem('STAGING_UNAVAILABLE', 'Private staging is unavailable. Await operator preparation; nothing is executing.')
    root = Path(value)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ImportProblem('STAGING_UNAVAILABLE', 'The operator must configure an existing private staging directory.')
    root = root.resolve()
    forbidden = [settings.BASE_DIR, settings.MEDIA_ROOT, settings.STATIC_ROOT, *getattr(settings, 'STATICFILES_DIRS', [])]
    if any(root == Path(p).resolve() or root.is_relative_to(Path(p).resolve()) for p in forbidden) or root.stat().st_mode & 0o077:
        raise ImportProblem('STAGING_UNAVAILABLE', 'Staging must be private and separate from repository, media and static directories.')
    return root


def staging_available():
    try:
        staging_root()
        return True
    except ImportProblem:
        return False


def directory_fd(root, parts):
    """Traverse each component with O_NOFOLLOW, retaining a directory handle."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            if part in ('', '.', '..'):
                raise OSError('Invalid directory component')
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_regular(fd, filename):
    descriptor = None
    try:
        descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_PRODUCT_IMAGE_SIZE_BYTES:
            raise ImportProblem('IMAGE_SIZE', 'Each image must be a regular file no larger than 5 MiB.', 'image_1')
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None
            content = stream.read(MAX_PRODUCT_IMAGE_SIZE_BYTES + 1)
        if len(content) > MAX_PRODUCT_IMAGE_SIZE_BYTES:
            raise ImportProblem('IMAGE_SIZE', 'Each image must be no larger than 5 MiB.', 'image_1')
        return content
    except OSError:
        raise ImportProblem('IMAGE_MISSING', 'A required image is missing, unreadable or unsafe. Ask the operator to check exact filenames.', 'image_1')
    finally:
        if descriptor is not None:
            os.close(descriptor)


def image_metadata(content, filename):
    validate_filename(filename)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            validate_product_image(ContentFile(content, name=filename))
            with Image.open(io.BytesIO(content)) as picture:
                image_format = picture.format
    except Exception:
        raise ImportProblem('IMAGE_CONTENT', 'Image content must be valid JPEG, PNG or WebP matching its extension and safe to decode.', 'image_1')
    return {'sha256': digest(content), 'size': len(content), 'format': image_format, 'suffix': Path(filename).suffix.lower()}


def prepare_bundle(job, image_dir, filenames):
    root = staging_root()
    source = Path(image_dir)
    incoming = root / 'incoming'
    if not source.is_absolute() or not source.is_relative_to(incoming):
        raise ImportProblem('IMAGE_DIRECTORY', 'The operator image folder must be inside the configured private incoming directory.')
    source_fd = bundle_fd = None
    try:
        source_fd = directory_fd(root, source.relative_to(root).parts)
        names = os.listdir(source_fd)
        folded = [name.casefold() for name in names]
        if len(folded) != len(set(folded)) or any(stat.S_ISLNK(os.stat(n, dir_fd=source_fd, follow_symlinks=False).st_mode) for n in names):
            raise ImportProblem('UNSAFE_DIRECTORY', 'Remove symlinks and ambiguous filename-case collisions from the prepared folder.')
        bundle_fd = directory_fd(root, [])
        for part in ('snapshots', str(job.image_bundle_key)):
            try:
                os.mkdir(part, mode=0o700, dir_fd=bundle_fd)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=bundle_fd)
            os.close(bundle_fd)
            bundle_fd = child
        manifest, hashes, total = {}, set(), 0
        for filename in sorted(set(filenames)):
            validate_filename(filename)
            if filename not in names:
                raise ImportProblem('IMAGE_MISSING', 'A required exact filename is missing from the prepared folder.', 'image_1')
            content = read_regular(source_fd, filename)
            metadata = image_metadata(content, filename)
            if metadata['sha256'] not in hashes:
                total += len(content)
                hashes.add(metadata['sha256'])
            if total > MAX_BUNDLE_BYTES:
                raise ImportProblem('BUNDLE_SIZE', 'Prepared distinct image content must not exceed 2 GiB per job.')
            key = metadata['sha256'] + metadata['suffix']
            try:
                output_fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=bundle_fd)
            except FileExistsError:
                if digest(read_regular(bundle_fd, key)) != metadata['sha256']:
                    raise ImportProblem('INPUT_CHANGED', 'A prepared snapshot has changed. Use a new job and approval.')
            else:
                with os.fdopen(output_fd, 'wb') as output:
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
            manifest[filename] = metadata
        return manifest
    except OSError:
        raise ImportProblem('STAGING_UNAVAILABLE', 'Private staging could not be prepared. Check access and free disk space; no products were imported.')
    finally:
        for fd in (source_fd, bundle_fd):
            if fd is not None:
                os.close(fd)


def read_bundle_image(job, filename):
    root = staging_root()
    try:
        validate_filename(filename)
        metadata = job.image_manifest[filename]
        hash_value, suffix = metadata['sha256'], metadata['suffix']
        if len(hash_value) != 64 or any(c not in '0123456789abcdef' for c in hash_value) or suffix not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValueError
        fd = directory_fd(root, ['snapshots', str(job.image_bundle_key)])
        try:
            content = read_regular(fd, hash_value + suffix)
        finally:
            os.close(fd)
        if digest(content) != hash_value or len(content) != metadata['size']:
            raise ValueError
        return content
    except (OSError, KeyError, TypeError, ValueError, ImportProblem):
        raise ImportProblem('INPUT_CHANGED', 'Prepared image bytes are missing or changed. No replacement bytes may run under this approval.', 'image_1')


def verify_bundle(job):
    staging_root()
    for filename in job.image_manifest:
        read_bundle_image(job, filename)
