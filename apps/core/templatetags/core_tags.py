from django import template

register = template.Library()

@register.filter
def attribute_lookup(dictionary, key):
    """
    Look up a key in a dictionary.
    Usage: {{ my_dict|attribute_lookup:"my_key" }}
    """
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None
