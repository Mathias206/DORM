import functools

from django.conf import settings
from django.utils.module_loading import import_string


class BaseRenderer:
    """Stub renderer: form validation works, HTML rendering is not available."""

    form_template_name = "django/forms/div.html"
    formset_template_name = "django/forms/formsets/div.html"
    field_template_name = "django/forms/field.html"
    bound_field_class = None

    def get_template(self, template_name):
        raise NotImplementedError(
            "Template rendering is not available in the extracted ORM."
        )

    def render(self, template_name, context, request=None):
        raise NotImplementedError(
            "Template rendering is not available in the extracted ORM."
        )


class DjangoTemplates(BaseRenderer):
    pass


class Jinja2(BaseRenderer):
    pass


class TemplatesSetting(BaseRenderer):
    pass


@functools.lru_cache
def get_default_renderer():
    renderer_class = import_string(settings.FORM_RENDERER)
    return renderer_class()
