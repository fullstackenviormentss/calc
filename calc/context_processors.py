from django.conf import settings
from django.utils.safestring import mark_safe

from .site_utils import get_canonical_url


def canonical_url(request):
    '''Include the request's canonical URL in all request contexts'''
    return {'canonical_url': get_canonical_url(request)}


def show_debug_ui(request):
    '''Include show_debug_ui in all request contexts'''
    return {'show_debug_ui': settings.DEBUG and not settings.HIDE_DEBUG_UI}


def google_analytics_tracking_id(request):
    '''Include GA_TRACKING_ID in all request contexts'''
    return {'GA_TRACKING_ID': settings.GA_TRACKING_ID}


def help_email(request):
    '''Include HELP_EMAIL in all request contexts'''
    return {'HELP_EMAIL': settings.HELP_EMAIL}


def non_prod_instance_name(request):
    '''Include NON_PROD_INSTANCE_NAME in all request contexts'''
    value = mark_safe(settings.NON_PROD_INSTANCE_NAME)  # nosec
    return {'NON_PROD_INSTANCE_NAME': value}
