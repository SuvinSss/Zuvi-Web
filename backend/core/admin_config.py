from django.contrib.admin.apps import AdminConfig


class ZuuviAdminConfig(AdminConfig):
    default_site = "core.admin_site.ZuuviAdminSite"
