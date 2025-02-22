"""Base classes for implementing extensions."""

import locale
import logging
import os
from email.parser import FeedParser

import pkg_resources
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.templatetags.static import static
from django.urls import get_mod_func
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _

from djblets.extensions.errors import InstallExtensionMediaError
from djblets.extensions.settings import ExtensionSettings
from djblets.util.decorators import cached_property


logger = logging.getLogger(__name__)


class JSExtension(object):
    """Base class for a JavaScript extension.

    This can be subclassed to provide the information needed to initialize
    a JavaScript extension.

    The JSExtension subclass is expected to define a :py:attr:`model_class`
    attribute naming its JavaScript counterpart. This would be the variable
    name for the (uninitialized) model for the extension, defined in a
    JavaScript bundle.

    It may also define :py:attr:`apply_to`, which is a list of URL names that
    the extension will be initialized on. If not provided, the extension will
    be initialized on all pages.

    To provide additional data to the model instance, the JSExtension subclass
    can implement :py:meth:`get_model_data` and return a dictionary of data
    to pass. You may also override the :py:meth:`get_settings` method to
    return, a dict of settings to the :py:attr:`model_class`. By default, the
    associated extension's settings are returned.
    """

    #: The name of the JavaScript model class to instantiate.
    #:
    #: This class will be instantiated on the page. It should be a subclass of
    #: :js:class:`Djblets.Extension`.
    model_class = None

    #: The list of URL names to load this extension on.
    #:
    #: If not provided, this will be loaded on all pages.
    apply_to = None

    def __init__(self, extension):
        """Initialize the JavaScript extension.

        Args:
            extension (Extension):
                The main extension that owns this JavaScript extension.
        """
        self.extension = extension

    def applies_to(self, url_name):
        """Return whether this extension applies to the given URL name.

        Args:
            url_name (unicode):
                The name of the URL.

        Returns:
            bool:
            ``True`` if this JavaScript extension should load on the page
            with the given URL name. ``False`` if it should not load.
        """
        return self.apply_to is None or url_name in self.apply_to

    def get_model_data(self, request, **kwargs):
        """Return model data for the Extension model instance in JavaScript.

        Subclasses can override this to return custom data to pass to
        the extension class defined in :js:attr:`model_class`. This data must
        be JSON-serializable.

        Args:
            request (django.http.HttpRequest):
                The HTTP request from the client.

        Returns:
            dict:
            Model data to pass to the constructor of the JavaScript extension
            class.
        """
        return {}

    def get_settings(self):
        """Return the settings for the JS Extension.

        By default, this is the associated :py:class:`Extension` object's
        settings. Subclasses may override this method to provide different
        settings.

        These settings will be provided to the :py:attr:`model_class` as a
        ``settings`` key in its initialization options.

        Returns:
            dict:
            The extension settings.
        """
        return self.extension.settings


class Extension(object):
    """Base class for an extension.

    Extensions must subclass this class. They'll automatically have support for
    settings, adding hooks, and plugging into the administration UI.

    For information on writing extensions, see :ref:`writing-extensions`.

    Attributes:
        admin_site (django.contrib.admin.AdminSite):
            The database administration site set for the extension. This will
            be set automatically if :py:attr:`has_admin_site`` is ``True``.

        extension_manager (djblets.extensions.manager.ExtensionManager):
            The extension manager that manages this extension.

        hooks (set of djblets.extensions.hooks.ExtensionHook):
            The hooks currently registered and enabled for the extension.

        middleware_classes (list of callable):
            The list of new-style (Django 1.10+) middleware classses.

            Version Added:
                2.2.4

        settings (djblets.extensions.settings.ExtensionSettings):
            The settings for the extension.
    """

    #: Metadata describing the package.
    #:
    #: This is used to set the name, version, and other information for the
    #: extension. This data defaults to coming from the extension's Python
    #: package metadata, but can be set on the extension itself. You would
    #: want to use this if shipping multiple extensions in a single package,
    #: if you want to include a space in the package name, or if you want
    #: the version to be set independently of the package, for example.
    #:
    #: The following keys are supported:
    #:
    #: * ``Name``: The displayed name of the extension.
    #: * ``Version``: The version of the extension.
    #: * ``Summary``: A summary of the extension.
    #: * ``Description``: A more detailed description of the extension.
    #: * ``License``: The license the extension was released under.
    #: * ``Author``: The name of the author writing/maintaining the extension.
    #: * ``Author-email``: The e-mail address of the author writing/maintaining
    #:   the extension.
    #: * ``Author-home-page``: The URL of the author writing/maintaining the
    #:   extension.
    #: * ``Home-page``: The URL of the extension's home/product/company page.
    metadata = None

    #: Whether or not the extension is user-configurable.
    #:
    #: If ``True``, the extension will have a :guilabel:`Configure` link in
    #: the extension list that will take the user to a page for modifying
    #: extension settings. The extension must provide a :file:`admin_urls.py`
    #: file defining a top-level URL (:regexp:`^$`) pointing to a view that
    #: will handle configuration.
    is_configurable = False

    #: Default settings for the extension.
    #:
    #: These values will be used when looking up keys in :py:attr:`settings`
    #: that don't have custom values saved in the database.
    default_settings = {}

    #: Whether or not the extension has a database administration site.
    #:
    #: If ``True``, the extension will have a :guilabel:`Database` link in
    #: the extension list that will take the user to a page for adding/editing
    #: any database models registered by the extension.
    has_admin_site = False

    #: A list of any extension IDs to enable when this extension is enabled.
    #:
    #: This is used to ensure that another extension is enabled before this
    #: one. It's primarily for extensions that are augmenting or depending on
    #: another extension's functionality.
    requirements = []

    #: A list of API resource instances offered by this extension.
    #:
    #: Each entry in the list is an instance of a custom
    #: :py:class:`~djblets.webapi.resources.WebAPIResource`. These resources
    #: will appear underneath the extension's own resource.
    resources = []

    #: A list of Django application module paths to load.
    #:
    #: Each of these will be added to :django:setting:`INSTALLED_APPS` while
    #: the extension is enabled. It follows the same format as that setting.
    apps = []

    #: A list of Django context processors to load.
    #:
    #: Each of these will be added to
    #: :django:setting:`TEMPLATE_CONTEXT_PROCESSORS` while the extension is
    #: enabled. It follows the same format as that setting.
    context_processors = []

    #: A list of Django middleware to load.
    #:
    #: Each of these will be run as if they were part of
    #: :django:setting:`MIDDLEWARE` depending on your setup) while the
    #: extension is enabled. It follows the same format as that setting.
    middleware = []

    #: A dictionary of CSS bundles to include in the package.
    #:
    #: These will be automatically packaged along with the extension, and can
    #: be loaded in templates using :py:func:`{% ext_css_bundle %}
    #: <djblets.extensions.templatetags.djblets_extensions.ext_css_bundle>`.
    #:
    #: Each key in the dictionary is the name of the bundle, and the
    #: value is a dictionary containing a ``source_filenames`` key pointing
    #: to a list of CSS/LessCSS files.
    #:
    #: A special bundle ID of ``default`` will cause the CSS to be loaded on
    #: every page.
    css_bundles = {}

    #: A dictionary of JavaScript bundles to include in the package.
    #:
    #: These will be automatically packaged along with the extension, and can
    #: be loaded in templates using :py:func:`{% ext_js_bundle %}
    #: <djblets.extensions.templatetags.djblets_extensions.ext_js_bundle>`.
    #:
    #: Each key in the dictionary is the name of the bundle, and the
    #: value is a dictionary containing a ``source_filenames`` key pointing
    #: to a list of JavaScript files.
    #:
    #: A special bundle ID of ``default`` will cause the JavaScript to be
    #: loaded on every page.
    js_bundles = {}

    #: A list of JavaScript extension classes to enable on pages.
    #:
    #: Each entry in the list is a :py:class:`JSExtension` subclass to load.
    js_extensions = []

    def __init__(self, extension_manager):
        """Initialize the extension.

        Subclasses should not override this. Instead, they should override
        :py:meth:`initialize`.

        Args:
            extension_manager (djblets.extensions.manager.ExtensionManager):
                The extension manager that manages this extension.
        """
        self.extension_manager = extension_manager
        self.hooks = set()
        self.settings = ExtensionSettings(self)
        self.admin_site = None

        self.middleware_classes = []

        for middleware_path in self.middleware:
            self.middleware_classes.append(import_string(middleware_path))

        self.initialize()

    def initialize(self):
        """Initialize the extension.

        Subclasses can override this to provide any custom initialization.
        They do not need to call the parent function, as it does nothing.
        """
        pass

    def shutdown(self):
        """Shut down the extension.

        By default, this calls shutdown_hooks.

        Subclasses should override this if they need custom shutdown behavior.
        """
        self.shutdown_hooks()

    def shutdown_hooks(self):
        """Shut down all hooks for the extension."""
        for hook in self.hooks.copy():
            if hook.initialized:
                hook.disable_hook()

    def get_static_url(self, path):
        """Return the URL to a static media file for this extension.

        This takes care of resolving the static media path name to a path
        relative to the web server. If a versioned media file is found, it
        will be used, so that browser-side caching can be used.

        Args:
            path (unicode):
                The path within the static directory for the extension.

        Returns:
            unicode:
            The resulting static media URL.
        """
        return static('ext/%s/%s' % (self.id, path))

    def get_bundle_id(self, name):
        """Return the ID for a CSS or JavaScript bundle.

        This ID should be used when manually referencing the bundle in a
        template. The ID will be unique across all extensions.

        Args:
            name (unicode):
                The name of the bundle to reference.

        Returns:
            unicode:
            The ID of the bundle corresponding to the name.
        """
        return '%s-%s' % (self.id, name)

    @cached_property
    def admin_urlconf(self):
        """The module defining URLs for the extension's admin site."""
        try:
            name = '%s.%s' % (get_mod_func(self.__class__.__module__)[0],
                              'admin_urls')
            return __import__(name, {}, {}, [''])
        except Exception as e:
            raise ImproperlyConfigured(
                "Error while importing extension's admin URLconf %r: %s" %
                (name, e))


class ExtensionInfo(object):
    """Information on an extension.

    This class stores the information and metadata on an extension. This
    includes the name, version, author information, where it can be downloaded,
    whether or not it's enabled or installed, and anything else that may be
    in the Python package for the extension.
    """

    encodings = ['utf-8', locale.getpreferredencoding(False), 'latin1']

    @classmethod
    def create_from_entrypoint(cls, entrypoint, ext_class):
        """Create a new ExtensionInfo from a Python EntryPoint.

        This will pull out information from the EntryPoint and return a new
        ExtensionInfo from it.

        It handles pulling out metadata from the older :file:`PKG-INFO` files
        and the newer :file:`METADATA` files.

        Args:
            entrypoint (pkg_resources.EntryPoint):
                The EntryPoint pointing to the extension class.

            ext_class (type):
                The extension class (subclass of :py:class:`Extension`).

        Returns:
            ExtensionInfo:
            An ExtensionInfo instance, populated with metadata from the
            package.
        """
        metadata = cls._get_metadata_from_entrypoint(entrypoint, ext_class.id)

        return cls(ext_class=ext_class,
                   package_name=metadata.get('Name', ext_class.id),
                   metadata=metadata)

    @classmethod
    def _get_metadata_from_entrypoint(cls, entrypoint, extension_id):
        """Return metadata information from an entrypoint.

        This is used internally to parse and validate package information from
        an entrypoint for use in ExtensionInfo.

        Args:
            entrypoint (pkg_resources.EntryPoint):
                The EntryPoint pointing to the extension class.

            extension_id (unicode):
                The extension's ID.

        Returns:
            dict:
            The resulting metadata dictionary.
        """
        dist = entrypoint.dist

        try:
            # Wheel, or other modern package.
            lines = list(dist.get_metadata_lines('METADATA'))
        except IOError:
            try:
                # Egg, or other legacy package.
                lines = list(dist.get_metadata_lines('PKG-INFO'))
            except IOError:
                lines = []
                logger.error('No METADATA or PKG-INFO found for the package '
                             'containing the %s extension. Information on '
                             'the extension may be missing.',
                             extension_id)

        # pkg_resources on Python 3 will always give us back Unicode strings,
        # but Python 2 may give us back either Unicode or byte strings.
        if lines and isinstance(lines[0], bytes):
            data = b'\n'.join(lines)

            # Try to decode the PKG-INFO content. If no decoding method is
            # successful then the PKG-INFO content will remain unchanged and
            # processing will continue with the parsing.
            for enc in cls.encodings:
                try:
                    data = data.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                logger.warning('Failed decoding PKG-INFO content for '
                               'extension %s',
                               entrypoint.name)
        else:
            data = '\n'.join(lines)

        p = FeedParser()
        p.feed(data)
        pkg_info = p.close()

        # Convert from a Message to a dictionary.
        return dict(pkg_info.items())

    def __init__(self, ext_class, package_name, metadata={}):
        """Instantiate the ExtensionInfo using metadata and an extension class.

        This will set information about the extension based on the metadata
        provided by the caller and the extension class itself.

        Args:
            ext_class (type):
                The extension class (subclass of :py:class:`Extension`).

            package_name (unicode):
                The package name owning the extension.

            metadata (dict, optional):
                Optional metadata for the extension. If the extension provides
                its own metadata, that will take precedence.

        Raises:
            TypeError:
                The parameters passed were invalid (they weren't a new-style
                call or a legacy entrypoint-related call).
        """
        try:
            issubclass(ext_class, Extension)
        except TypeError:
            logger.error('Unexpected parameters passed to '
                         'ExtensionInfo.__init__: ext_class=%r, '
                         'package_name=%r, metadata=%r',
                         ext_class, package_name, metadata)

            raise TypeError(
                _('Invalid parameters passed to ExtensionInfo.__init__'))

        # Set the base information from the extension and the package.
        self.package_name = package_name
        self.module_name = ext_class.__module__
        self.app_name = '.'.join(ext_class.__module__.split('.')[:-1])
        self.is_configurable = ext_class.is_configurable
        self.has_admin_site = ext_class.has_admin_site
        self.installed_htdocs_path = \
            os.path.join(settings.MEDIA_ROOT, 'ext', self.package_name)
        self.installed_static_path = \
            os.path.join(settings.STATIC_ROOT, 'ext', ext_class.id)

        # State set by ExtensionManager.
        self.enabled = False
        self.installed = False
        self.requirements = []
        self.apps_registered = False
        self.context_processors_registered = False

        # Set information from the provided metadata.
        if ext_class.metadata is not None:
            metadata.update(ext_class.metadata)

        self.metadata = metadata
        self.name = metadata.get('Name', package_name)
        self.version = metadata.get('Version')
        self.summary = metadata.get('Summary')
        self.description = metadata.get('Description')
        self.author = metadata.get('Author')
        self.author_email = metadata.get('Author-email')
        self.license = metadata.get('License')
        self.url = metadata.get('Home-page')
        self.author_url = metadata.get('Author-home-page', self.url)

    @cached_property
    def installed_static_version_path(self):
        """The path to the static media version file.

        This file records the version of the extension used when last
        installing the static media files.

        Type:
            unicode
        """
        return os.path.join(self.installed_static_path, '.version')

    def has_resource(self, path):
        """Return whether an extension has a resource in its package.

        A resource is a file or directory that exists within an extension's
        package.

        Args:
            path (unicode):
                The ``/``-delimited path to the resource within the package.

        Returns:
            bool:
            ``True`` if the resource exits. ``False`` if it does not.
        """
        return pkg_resources.resource_exists(self.module_name, path)

    def extract_resource(self, path):
        """Return the filesystem path to an extracted resource.

        A resource is a file or directory that exists within an extension's
        package.

        This will extract the resource from the package, if the package is
        compressed, and then return the local path to the file on the
        filesystem.

        Args:
            path (unicode):
                The ``/``-delimited path to the resource within the package.

        Returns:
            unicode:
            The local filesystem path to the resource, or ``None`` if it
            could not be found.
        """
        if self.has_resource(path):
            return pkg_resources.resource_filename(self.module_name, path)

        return None

    def write_installed_static_version(self):
        """Write the extension's current static media version to disk.

        This will write the extension's current version in its static media
        directory, creating that directory if necessary. This will allow
        the extension manager to check if new media files need to be installed.

        Raises:
            djblets.extensions.errors.InstallExtensionMediaError:
                There was an error writing the version to the static media
                directory. Details are in the error message.
        """
        version_path = self.installed_static_version_path
        parent_path = os.path.dirname(version_path)

        try:
            if not os.path.exists(parent_path):
                os.makedirs(parent_path, 0o755)

            with open(version_path, 'w') as fp:
                fp.write('%s\n' % self.version)
        except Exception:
            raise InstallExtensionMediaError(
                _('Unable to write the extension static media version '
                  'file "%(path)s". Please make sure the file and its parent '
                  'directory are owned by the web server.')
                % {
                    'path': version_path,
                })

    def get_installed_static_version(self):
        """Return the extension's locally-written static media version.

        Returns:
            unicode:
            The extension version written to disk, or ``None`` if it didn't
            exist or couldn't be read.
        """
        try:
            with open(self.installed_static_version_path, 'r') as fp:
                return fp.read().strip()
        except IOError:
            return None

    def __str__(self):
        return '%s %s (enabled = %s)' % (self.name, self.version, self.enabled)
